import json
import threading
from pathlib import Path

from flask import Flask, request, send_from_directory
from flask_restful import Api, Resource
from flask_cors import CORS
import pandas as pd

from roster import get_team_roster
from vct_config import ALL_STANDARD_MAPS, COMP_POOL_MAPS

SERVER_DIR = Path(__file__).resolve().parent
CLIENT_DIST = SERVER_DIR.parent / "client" / "dist"

app = Flask(__name__, static_url_path="/static", static_folder="static")
CORS(app)
api = Api(app)

_predictor = None
_predictor_lock = threading.Lock()
_team_table = None
METRICS_PATH = SERVER_DIR / "data" / "model_metrics.json"
TEAM_DATA_PATH = SERVER_DIR / "csv" / "team_data.csv"


def load_team_table():
    """Team list for the UI — do not load sklearn/the model for this."""
    global _team_table
    if _team_table is None:
        _team_table = pd.read_csv(TEAM_DATA_PATH)
    return _team_table


def get_predictor():
    """Load sklearn/pandas once. Concurrent first requests used to each reload (~90s) and hang the UI."""
    global _predictor
    if _predictor is not None:
        return _predictor
    with _predictor_lock:
        if _predictor is None:
            print("Loading model and dataset...", flush=True)
            from models.RandomForestPredictor import RandomForestPredictor as Predictor

            _predictor = Predictor()
            print("Model ready.", flush=True)
        return _predictor


def _warm_predictor() -> None:
    try:
        get_predictor()
    except Exception as exc:
        print(f"Model warmup failed: {exc}", flush=True)


def load_model_metrics() -> dict:
    if METRICS_PATH.exists():
        try:
            return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "random_split_accuracy": 72.8,
        "time_ordered_split_accuracy": None,
        "note": "Run python scripts/evaluate_model.py to refresh metrics.",
    }


class TeamData(Resource):
    def get(self, team):
        if not team:
            return {"error": "Query Parameter Required"}
        table = load_team_table()
        rows = table[table["Team"] == team]
        return rows.to_dict(orient="records")


class TeamsData(Resource):
    def get(self):
        return load_team_table().to_dict(orient="records")


class PredictorMatchup(Resource):
    def get(self, team1, team2):
        if not team1 or not team2:
            return {"error": "Both team1 and team2 query parameters are required"}, 400
        # Default: include odds. ?odds=0 skips VLR scrape for faster responses.
        odds_flag = request.args.get("odds", "1").lower()
        include_odds = odds_flag not in ("0", "false", "no")
        try:
            result = get_predictor().predict_match(
                team1, team2, include_odds=include_odds
            )
            return {"team1": team1, "team2": team2, **result}, 200
        except ValueError as e:
            return {"error": str(e)}, 400
        except Exception as e:
            return {"error": f"Prediction failed: {str(e)}"}, 500


class MatchOdds(Resource):
    def get(self, team1, team2):
        if not team1 or not team2:
            return {"error": "Both team1 and team2 are required"}, 400
        from odds_vlr import fetch_match_odds
        from prediction_extras import build_betting_insight

        try:
            p1 = get_predictor()._win_probability_team1(team1, team2)
            odds = fetch_match_odds(team1, team2)
            betting = build_betting_insight(team1, team2, p1, odds=odds)
            return {
                "team1": team1,
                "team2": team2,
                "odds": odds,
                "betting": betting,
            }, 200
        except ValueError as e:
            return {"error": str(e)}, 400
        except Exception as e:
            return {"error": f"Odds lookup failed: {str(e)}"}, 500


class MatchupData(Resource):
    def get(self, team1, team2):
        if not team1 or not team2:
            return {"error": "Both team1 and team2 query parameters are required"}, 400
        try:
            return get_predictor().build_matchup_view(team1, team2)
        except ValueError as e:
            return {"error": str(e)}, 400


class TeamRoster(Resource):
    def get(self, team):
        if not team:
            return {"error": "Team name is required"}, 400
        table = load_team_table()
        rows = table[table["Team"] == team]
        if rows.empty:
            rows = table[table["Team"].astype(str).str.casefold() == str(team).casefold()]
        if rows.empty:
            return {"error": f"Team '{team}' not found"}, 404
        return get_team_roster(str(rows.iloc[0]["Team"])), 200


class MetaData(Resource):
    def get(self):
        match_count = None
        team_count = None
        scores_path = SERVER_DIR / "csv" / "scores.csv"
        try:
            table = load_team_table()
            team_count = len(table)
            if scores_path.exists():
                match_count = len(pd.read_csv(scores_path))
        except Exception:
            pass
        metrics = load_model_metrics()
        if match_count is None and metrics.get("match_count"):
            match_count = metrics["match_count"]
        return {
            "comp_pool_maps": COMP_POOL_MAPS,
            "standard_maps": len(ALL_STANDARD_MAPS),
            "model_metrics": metrics,
            "match_count": match_count,
            "team_count": team_count,
        }, 200


class TodayMatches(Resource):
    def get(self):
        from today_matches import fetch_upcoming_matches

        try:
            payload = fetch_upcoming_matches()
            try:
                known = {
                    str(t).strip().lower()
                    for t in load_team_table()["Team"].astype(str)
                }
            except Exception:
                known = set()

            def can_predict(name: str) -> bool:
                n = (name or "").strip().lower()
                if n in known:
                    return True
                return any(n in k or k in n for k in known if len(n) >= 3)

            for match in payload.get("matches") or []:
                t1 = match.get("team1", {}).get("name")
                t2 = match.get("team2", {}).get("name")
                match["predictable"] = bool(t1 and t2 and can_predict(t1) and can_predict(t2))
            return payload, 200
        except Exception as e:
            return {"error": f"Failed to load upcoming matches: {e}", "matches": []}, 502


api.add_resource(TeamData, "/api/info/<team>")
api.add_resource(TeamsData, "/api/teams")
api.add_resource(PredictorMatchup, "/api/predict/<team1>/<team2>")
api.add_resource(MatchOdds, "/api/odds/<team1>/<team2>")
api.add_resource(MatchupData, "/api/matchup_data/<team1>/<team2>")
api.add_resource(TeamRoster, "/api/roster/<team>")
api.add_resource(MetaData, "/api/meta")
api.add_resource(TodayMatches, "/api/matches/today", "/api/matches/upcoming")



class Health(Resource):
    def get(self):
        ready = _predictor is not None
        return {"status": "ok", "model_loaded": ready}, 200


api.add_resource(Health, "/api/health")


def _spa_enabled() -> bool:
    return (CLIENT_DIST / "index.html").is_file()


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def spa_or_api_root(path: str):
    """Serve the Vite build in production; JSON API index when dist is missing."""
    if path.startswith("api/") or path == "api":
        return {"error": "Not found"}, 404
    if path.startswith("static/"):
        return {"error": "Not found"}, 404

    if _spa_enabled():
        candidate = CLIENT_DIST / path
        if path and candidate.is_file():
            return send_from_directory(CLIENT_DIST, path)
        return send_from_directory(CLIENT_DIST, "index.html")

    if path in ("", "/"):
        return {
            "status": "ok",
            "message": "Velo.gg API",
            "endpoints": [
                "/api/health",
                "/api/teams",
                "/api/predict/<team1>/<team2>",
                "/api/odds/<team1>/<team2>",
                "/api/matches/upcoming",
            ],
        }
    return {"error": "Frontend not built. Run npm run build in client/."}, 404


if __name__ == "__main__":
    threading.Thread(target=_warm_predictor, daemon=True, name="model-warmup").start()
    app.run(debug=True, port=5001, use_reloader=False)
