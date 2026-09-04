"""Tests for point-in-time match feature tracking."""

import sys
from pathlib import Path

import pandas as pd

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

from feature_engineering import (  # noqa: E402
    DEFAULT_PLAYER_STATS,
    MatchFeatureTracker,
    build_live_feature_tracker,
)
from vlr_ingest import repair_vlr_player_stats  # noqa: E402


def test_h2h_is_undirected_across_seat_order():
    tracker = MatchFeatureTracker()
    tracker.record(
        tournament="VCT 2026: Americas Stage 1",
        stage="Regular Season",
        match_type="Week 1",
        team_a="Alpha",
        team_b="Beta",
        team_a_won=True,
        score_a=2,
        score_b=0,
    )

    rate_ab, rate_ba, n_ab = tracker._h2h_rate("Alpha", "Beta")
    rate_ba2, rate_ab2, n_ba = tracker._h2h_rate("Beta", "Alpha")

    assert n_ab == 1
    assert n_ba == 1
    assert rate_ab == rate_ab2
    assert rate_ba == rate_ba2
    assert rate_ab > 50
    assert rate_ba < 50

    wins_ab, losses_ab, n_rec = tracker.h2h_record("Alpha", "Beta")
    wins_ba, losses_ba, n_rec_ba = tracker.h2h_record("Beta", "Alpha")
    assert n_rec == 1
    assert n_rec_ba == 1
    assert wins_ab == 1 and losses_ab == 0
    assert wins_ba == 0 and losses_ba == 1


def test_map_pool_strength_is_point_in_time():
    maps = pd.DataFrame(
        [
            {
                "Tournament": "VCT 2026: Americas Stage 1",
                "Stage": "Regular Season",
                "Match Type": "Week 1",
                "Map": "Ascent",
                "Team A": "Alpha",
                "Team B": "Beta",
                "Team A Score": 13,
                "Team B Score": 5,
            }
        ]
    )
    tracker = MatchFeatureTracker()
    tracker.index_map_scores(maps)

    before = tracker.features_for("Alpha", "Beta", tournament="VCT 2026: Americas Stage 1")
    assert before["Team A Map Pool Strength"] == 50.0
    assert before["Team B Map Pool Strength"] == 50.0
    assert before["Team A Map Pool Differential"] == 0.0

    tracker.record(
        tournament="VCT 2026: Americas Stage 1",
        stage="Regular Season",
        match_type="Week 1",
        team_a="Alpha",
        team_b="Beta",
        team_a_won=True,
        score_a=2,
        score_b=0,
    )
    after = tracker.features_for("Alpha", "Gamma", tournament="VCT 2026: Americas Stage 1")
    assert after["Team A Map Pool Strength"] > 50.0


def test_seed_map_stats_live_strength_not_stuck_at_50():
    """RAM-safe live path: seed from map_team lookup instead of replaying map scores."""
    lookup = {
        ("Alpha", "Ascent"): {"wins": 8, "played": 10},
        ("Alpha", "Bind"): {"wins": 6, "played": 10},
        ("Beta", "Ascent"): {"wins": 2, "played": 10},
        ("Beta", "Bind"): {"wins": 3, "played": 10},
    }
    scores = pd.DataFrame(
        [
            {
                "Tournament": "VCT 2026: Americas Stage 1",
                "Stage": "Regular Season",
                "Match Type": "Week 1",
                "Team A": "Alpha",
                "Team B": "Beta",
                "Match Result": "Team A",
                "Team A Score": 2,
                "Team B Score": 0,
            }
        ]
    )
    tracker = build_live_feature_tracker(
        scores,
        pd.DataFrame(),
        map_lookup=lookup,
        map_scores=pd.DataFrame(),
    )
    feat = tracker.features_for("Alpha", "Beta")
    assert feat["Team A Map Pool Strength"] != 50.0
    assert feat["Team B Map Pool Strength"] != 50.0
    assert feat["Team A Map Pool Strength"] > feat["Team B Map Pool Strength"]
    assert feat["Map pool strength delta"] != 0.0


def test_same_week_player_stats_consume_bucket_once():
    players = pd.DataFrame(
        [
            {
                "Tournament": "VCT 2026: Americas Stage 1",
                "Stage": "Regular Season",
                "Match Type": "Week 1",
                "Player": "p1",
                "Teams": "Alpha",
                "Agents": "Jett",
                "Rating": 2.0,
                "Kills:Deaths": 2.0,
                "Average Damage Per Round": 200.0,
                "Average Combat Score": 300.0,
                "First Kills": 10.0,
                "First Deaths Per Round": 0.1,
                "Kill, Assist, Trade, Survive %": 80.0,
                "Clutch Success %": 40.0,
            }
        ]
    )
    tracker = MatchFeatureTracker()
    tracker.index_player_stats(players)

    before = tracker.features_for("Alpha", "Beta")
    assert before["Team A Rating"] == DEFAULT_PLAYER_STATS["Rating"]

    tracker.record(
        tournament="VCT 2026: Americas Stage 1",
        stage="Regular Season",
        match_type="Week 1",
        team_a="Alpha",
        team_b="Beta",
        team_a_won=True,
        score_a=2,
        score_b=1,
    )
    after_first = tracker.features_for("Alpha", "Gamma")
    assert after_first["Team A Rating"] == 2.0
    assert len(tracker._player_history["Alpha"]) == 1

    tracker.record(
        tournament="VCT 2026: Americas Stage 1",
        stage="Regular Season",
        match_type="Week 1",
        team_a="Alpha",
        team_b="Delta",
        team_a_won=True,
        score_a=2,
        score_b=0,
    )
    # Same week bucket must not be appended twice.
    assert len(tracker._player_history["Alpha"]) == 1


def test_repair_vlr_player_stats_joins_to_score_keys():
    raw = pd.DataFrame(
        [
            {
                "Tournament": "VCT 2026",
                "Stage": "China Stage 2 Group Stage",
                "Match Type": "Week 1",
                "Player": "zzz",
                "Teams": "EDward Gaming",
                "Agents": "Omen",
            },
            {
                "Tournament": "VCT 2026",
                "Stage": "Pacific Kickoff Playoffs",
                "Match Type": "Upper Final",
                "Player": "yyy",
                "Teams": "Paper Rex",
                "Agents": "Raze",
            },
        ]
    )
    repaired = repair_vlr_player_stats(raw)
    assert repaired.iloc[0]["Tournament"] == "VCT 2026: China Stage 2"
    assert repaired.iloc[0]["Stage"] == "Group Stage"
    assert repaired.iloc[1]["Tournament"] == "VCT 2026: Pacific Kickoff"
    assert repaired.iloc[1]["Stage"] == "Playoffs"

    score_keys = {
        ("VCT 2026: China Stage 2", "Group Stage", "Week 1", "EDward Gaming"),
        ("VCT 2026: Pacific Kickoff", "Playoffs", "Upper Final", "Paper Rex"),
    }
    join_keys = {
        (str(r["Tournament"]), str(r["Stage"]), str(r["Match Type"]), str(r["Teams"]))
        for _, r in repaired.iterrows()
    }
    assert join_keys == score_keys


def test_score_dedupe_keeps_same_score_rematches():
    from vlr_ingest import score_dedupe_key

    mr3 = {
        "Tournament": "VCT 2026: Americas Kickoff",
        "Stage": "Main Event",
        "Match Type": "Middle Round 3",
        "Team A": "NRG",
        "Team B": "100 Thieves",
        "Team A Score": 2,
        "Team B Score": 0,
    }
    lr5 = {
        **mr3,
        "Match Type": "Lower Round 5",
    }
    assert score_dedupe_key(mr3) != score_dedupe_key(lr5)
    flipped = {**mr3, "Team A": "100 Thieves", "Team B": "NRG"}
    assert score_dedupe_key(mr3) == score_dedupe_key(flipped)
