"""Tests for betting EV helper and VLR odds HTML parsing."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

from odds_vlr import parse_betting_books, parse_odds_from_html, parse_post_match_odds
from prediction_extras import build_betting_insight, decimal_ev, implied_prob_from_decimal


SAMPLE_VLR_BETTING_HTML = """
<html><body>
  <div style="margin: 16px 0;">
    <div class="wf-label">Betting</div>
    <a class="wf-card mod-dark match-bet-item" href="/rr/bet/1">
      <div class="match-bet-item-half mod-1">
        <img class="mod-ggbet" src="/img/pd/ggbet.png"/>
        <span class="match-bet-item-team text-of">
          <span class="match-bet-item-team-name">LEVIATÁN</span>
          <span class="match-bet-item-team-tag">LEV</span>
        </span>
        <span class="match-bet-item-odds mod-down mod-1">1.71</span>
      </div>
      <div class="ge-text-light match-bet-item-vs">vs</div>
      <div class="match-bet-item-half mod-2">
        <span class="match-bet-item-odds mod-up mod-2">2.07</span>
        <span class="match-bet-item-team text-of">
          <span class="match-bet-item-team-name">MIBR</span>
          <span class="match-bet-item-team-tag">MIBR</span>
        </span>
        <div class="ge-text-light match-bet-item-note">Live</div>
      </div>
    </a>
    <a class="wf-card mod-dark match-bet-item" href="/rr/bet/2">
      <div class="match-bet-item-half mod-1">
        <img class="mod-rainbet" src="/img/pd/rainbet.png"/>
        <span class="match-bet-item-team text-of">
          <span class="match-bet-item-team-name">LEVIATÁN</span>
        </span>
        <span class="match-bet-item-odds mod-1">1.59</span>
      </div>
      <div class="match-bet-item-half mod-2">
        <span class="match-bet-item-odds mod-2">2.30</span>
        <span class="match-bet-item-team text-of">
          <span class="match-bet-item-team-name">MIBR</span>
        </span>
        <div class="ge-text-light match-bet-item-note">Pre-match</div>
      </div>
    </a>
  </div>
</body></html>
"""


def test_implied_and_ev_math():
    assert implied_prob_from_decimal(2.0) == 0.5
    assert decimal_ev(0.6, 2.0) == pytest.approx(0.2)


def test_parse_betting_books_table():
    books = parse_betting_books(SAMPLE_VLR_BETTING_HTML)
    assert len(books) == 2
    assert books[0]["bookie"] == "GG.BET"
    assert books[0]["team1_odds"] == 1.71
    assert books[0]["team2_odds"] == 2.07
    assert books[0]["status"] == "Live"
    assert books[1]["bookie"] == "Rainbet"
    assert books[1]["status"] == "Pre-match"


def test_parse_odds_averages_books():
    rows = parse_odds_from_html(SAMPLE_VLR_BETTING_HTML)
    lev = next(o for n, o in rows if "leviat" in n.lower())
    mibr = next(o for n, o in rows if "mibr" in n.lower())
    assert lev == pytest.approx(1.65)
    assert mibr == pytest.approx(2.185)


def test_betting_needs_odds_without_prices():
    insight = build_betting_insight("A", "B", 0.70)
    assert insight["recommendation"] == "pass"
    assert insight["odds_available"] is False
    assert "book" in insight["recommendation_label"].lower()


def test_betting_value_even_below_old_65_gate():
    # Model only 58% on A, but books price A like a bigger underdog → value
    odds = {"team1_odds": 2.20, "team2_odds": 1.70}
    insight = build_betting_insight("A", "B", 0.58, odds=odds)
    assert insight["odds_available"] is True
    assert insight["recommendation"] == "bet"
    assert insight["tip_team"] == "A"
    assert insight["tip_model_pct"] > insight["tip_book_pct"]


def test_betting_pass_when_no_edge():
    # Model 60%/40% but juice prices both sides so neither clears 1/odds
    odds = {"team1_odds": 1.55, "team2_odds": 2.40}
    insight = build_betting_insight("A", "B", 0.60, odds=odds)
    assert insight["recommendation"] == "pass"
    assert insight["edge_pp"] is not None
    assert insight["edge_pp"] <= 0


def test_betting_can_tip_underdog():
    # Books price B too short for an underdog; model likes B more than 1/odds
    odds = {"team1_odds": 1.40, "team2_odds": 3.10}
    insight = build_betting_insight("A", "B", 0.40, odds=odds)
    # implied B ≈ 32.3%; model 40% → value on B
    assert insight["tip_team"] == "B"
    assert insight["recommendation"] == "bet"


SAMPLE_POST_ODDS_HTML = """
<html><body>
  <div class="wf-label">Betting</div>
  <a href="/rr/bet/1" class="wf-card mod-dark match-bet-item mod-post-odds">
    <div class="match-bet-item-return">
      <div class="match-bet-item-return-msg">
        <span class="match-bet-item-odds">$100</span> on
        <span class="match-bet-item-teamzzz">100 Thieves</span>
        returned <span class="match-bet-item-odds">$139</span>
        at pre-match odds
      </div>
      <div class="match-bet-item-return-short">
        <span class="match-bet-item-odds">1.39</span>
        <span class="match-bet-item-teamzzz">100T</span>
        odds pre-match
      </div>
    </div>
  </a>
</body></html>
"""


def test_parse_post_match_winner_price():
    rows = parse_post_match_odds(SAMPLE_POST_ODDS_HTML)
    assert rows
    name, price = rows[0]
    assert "100" in name
    assert price == pytest.approx(1.39)


def test_betting_keeps_one_sided_post_match_price():
    odds = {"team1_odds": 1.39, "method": "vlr_post_odds", "source_url": "https://www.vlr.gg/1"}
    insight = build_betting_insight("100 Thieves", "LOUD", 0.65, odds=odds)
    assert insight["odds_available"] is False
    assert insight["team1_odds"] == 1.39
    assert "one pre-match price" in insight["recommendation_label"].lower()
