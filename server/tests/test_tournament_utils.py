"""Tests for tournament utilities."""

import sys
from pathlib import Path

import pandas as pd

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

from tournament_utils import (  # noqa: E402
    is_international_tournament,
    is_pro_event_name,
    normalize_tournament_name,
    parse_match_date,
    shrink_rate,
    sort_scores_chronologically,
)


def test_normalize_ewc_tournament():
    assert normalize_tournament_name("Valorant at Esports World Cup 2025") == "Esports World Cup 2025"
    assert is_pro_event_name("Esports World Cup 2025")
    assert is_international_tournament("Esports World Cup 2025")


def test_normalize_champions_2026_variants():
    expected = "Valorant Champions 2026"
    assert normalize_tournament_name("Valorant Champions 2026") == expected
    assert normalize_tournament_name("Champions 2026") == expected
    assert normalize_tournament_name("Champions Shanghai 2026") == expected
    assert normalize_tournament_name("VALORANT Champions Shanghai 2026") == expected
    assert normalize_tournament_name("Valorant Champions 2026: Shanghai") == expected
    assert normalize_tournament_name("Champions Shanghai") == expected
    assert normalize_tournament_name("Valorant Champions Tour 2026") == "Valorant Champions Tour 2026"
    assert is_pro_event_name(expected)
    assert is_international_tournament(expected)
    assert is_pro_event_name("Champions Shanghai 2026")


def test_shrink_sparse_h2h():
    assert shrink_rate(100.0, 1) == 66.66666666666666
    assert shrink_rate(100.0, 3) == 100.0
    assert shrink_rate(50.0, 0) == 50.0


def test_parse_match_date_injects_tournament_year_for_vlr_weekday():
    parsed = parse_match_date(
        "Thursday, July 9 1:30 PM IST",
        tournament="VCT 2026: Pacific Stage 2",
    )
    assert parsed is not None
    assert parsed.year == 2026
    assert parsed.month == 7
    assert parsed.day == 9


def test_parse_match_date_rejects_yearless_without_tournament():
    assert parse_match_date("Thursday, July 9 1:30 PM") is None


def test_sort_scores_chronologically_orders_yearless_vlr_dates():
    df = pd.DataFrame(
        [
            {
                "Tournament": "VCT 2026: Americas Stage 2",
                "Stage": "Regular Season",
                "Match Type": "Week 2",
                "Match Name": "Later vs Match",
                "Team A": "Later",
                "Team B": "Match",
                "Team A Score": 2,
                "Team B Score": 0,
                "Match Result": "Later won",
                "Match Date": "Friday, July 17 8:00 PM",
            },
            {
                "Tournament": "VCT 2025: Americas Stage 2",
                "Stage": "Regular Season",
                "Match Type": "Week 1",
                "Match Name": "Earlier vs Match",
                "Team A": "Earlier",
                "Team B": "Match",
                "Team A Score": 2,
                "Team B Score": 1,
                "Match Result": "Earlier won",
                "Match Date": "Thursday, July 9 1:30 PM IST",
            },
        ]
    )
    sorted_df = sort_scores_chronologically(df)
    assert sorted_df.iloc[0]["Team A"] == "Earlier"
    assert sorted_df.iloc[1]["Team A"] == "Later"


def test_sort_scores_chronologically_adds_match_date_column():
    df = pd.DataFrame(
        [
            {
                "Tournament": "VCT 2026: Americas Stage 1",
                "Stage": "Playoffs",
                "Match Type": "Grand Final",
                "Match Name": "A vs B",
                "Team A": "A",
                "Team B": "B",
                "Team A Score": 3,
                "Team B Score": 1,
                "Match Result": "A won",
                "Match Date": "2026-06-01",
            },
            {
                "Tournament": "Valorant Masters London 2026",
                "Stage": "Playoffs",
                "Match Type": "Grand Final",
                "Match Name": "C vs D",
                "Team A": "C",
                "Team B": "D",
                "Team A Score": 3,
                "Team B Score": 2,
                "Match Result": "C won",
                "Match Date": "2026-06-15",
            },
        ]
    )
    sorted_df = sort_scores_chronologically(df)
    assert sorted_df.iloc[0]["Team A"] == "A"
    assert sorted_df.iloc[1]["Team A"] == "C"
    assert "Match Date" in sorted_df.columns


def test_homepage_includes_champions_2026_cards():
    from today_matches import _is_vct_2026

    assert _is_vct_2026("Valorant Champions 2026")
    assert _is_vct_2026("Champions Shanghai")
    assert _is_vct_2026("Champions Shanghai 2026")
    assert not _is_vct_2026("VCT 2025: Americas Stage 2")


def test_group_stage_en_dash_match_type():
    from vlr_ingest import _stage_match_type_from_event_card

    stage, match_type = _stage_match_type_from_event_card("Group Stage–Opening (A)")
    assert stage == "Group Stage"
    assert match_type == "Opening (A)"
