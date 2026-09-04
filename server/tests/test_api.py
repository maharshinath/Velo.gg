"""API smoke tests. Run from server/: python -m pytest tests/ -q"""

import json
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

from app import app  # noqa: E402


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_teams_list(client):
    r = client.get("/api/teams")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, list)
    assert len(data) >= 50


def test_predict_includes_maps(client):
    r = client.get("/api/predict/Sentinels/LOUD")
    assert r.status_code == 200
    data = r.get_json()
    assert "map_predictions" in data
    assert len(data["map_predictions"]) == 7
    assert "team1_win_probability" in data
    assert "confidence" in data
    assert "series_predictions" in data


def test_matchup_data_includes_raw_h2h(client):
    r = client.get("/api/matchup_data/NRG/100%20Thieves")
    assert r.status_code == 200
    data = r.get_json()
    assert data["Team A"] == "NRG"
    assert data["Team B"] == "100 Thieves"
    assert data["Team A H2H Wins"] + data["Team B H2H Wins"] == data["Team A H2H Count"]
    assert data["Team A H2H Count"] >= 1
    assert abs(data["Team A H2H Winrate"] + data["Team B H2H Winrate"] - 100) < 0.2
    # VLR 2025–26 VCT + EWC (incl. 2025 qualifier): NRG leads 6–4.
    assert data["Team A H2H Wins"] == 6
    assert data["Team B H2H Wins"] == 4
    assert data["Team A H2H Count"] == 10


def test_meta(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data["comp_pool_maps"]) == 7

