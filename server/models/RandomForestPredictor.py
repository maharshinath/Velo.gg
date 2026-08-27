import os
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.join(BASE_DIR, "..")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from feature_engineering import PLAYER_STAT_LOAD_COLUMNS, build_live_feature_tracker
from map_features import load_map_team_lookup
from model_training import add_engineered_features, load_model_bundle
from map_predictions import MapPredictor
from prediction_extras import (
    build_betting_insight,
    build_key_factors,
    compute_agent_diversity,
    compute_recent_form,
    confidence_label,
    simulate_series,
    sort_map_predictions,
)


class RandomForestPredictor:
    def __init__(self):
        import gc

        model_path = os.path.join(BASE_DIR, "rf.pkl")
        self.team_data = pd.read_csv(os.path.join(BASE_DIR, "../csv/team_data.csv"))
        self.match_data = pd.read_csv(os.path.join(BASE_DIR, "../csv/scores.csv"))
        player_stats = self._load_player_stats()
        self.feature_tracker = build_live_feature_tracker(
            self.match_data,
            player_stats,
            regions={
                str(team): str(region)
                for team, region in zip(self.team_data["Team"], self.team_data.get("Region", []))
                if pd.notna(region) and str(region).strip()
            },
            # Seed pool strength from map_team_stats.csv (RAM-safe; no full map replay).
            map_lookup=load_map_team_lookup(),
            map_scores=pd.DataFrame(),
        )
        del player_stats
        gc.collect()
        self.rf_model, self.feature_cols = load_model_bundle(model_path)
        self.map_predictor = MapPredictor()
        self.recent_form = compute_recent_form(self.match_data)
        self.agent_diversity = compute_agent_diversity()
        gc.collect()

    @staticmethod
    def _load_player_stats() -> pd.DataFrame:
        merged = os.path.join(BASE_DIR, "../csv/player_stats_merged.csv")
        vlr = os.path.join(BASE_DIR, "../data/vlr_player_stats.csv")
        path = merged if os.path.exists(merged) else vlr
        if not os.path.exists(path):
            return pd.DataFrame()
        header = pd.read_csv(path, nrows=0)
        usecols = [c for c in PLAYER_STAT_LOAD_COLUMNS if c in header.columns]
        return pd.read_csv(path, usecols=usecols)

    def get_winrate_team1(self, team1, team2):
        """Rolling head-to-head win rate for team1 vs team2 (last N meetings)."""
        feat = self.feature_tracker.features_for(team1, team2, tournament=None)
        return float(feat["Team A Winrate vs B"])

    def build_pred_df(self, teama, teamb):
        if teama not in set(self.team_data["Team"]):
            raise ValueError(f"Team '{teama}' not found in team data")
        if teamb not in set(self.team_data["Team"]):
            raise ValueError(f"Team '{teamb}' not found in team data")

        feat = self.feature_tracker.features_for(teama, teamb, tournament=None)
        df = pd.DataFrame([feat])
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = add_engineered_features(df.fillna(0))
        for col in self.feature_cols:
            if col not in df.columns:
                df[col] = 0.0
        return df[self.feature_cols].fillna(0)

    def _win_probability_team1(self, team1: str, team2: str) -> float:
        df_12 = self.build_pred_df(team1, team2)
        df_21 = self.build_pred_df(team2, team1)
        p1 = float(self.rf_model.predict_proba(df_12)[0][1])
        p2 = float(self.rf_model.predict_proba(df_21)[0][1])
        return (p1 + (1.0 - p2)) / 2.0

    def predict_match(
        self,
        team1: str,
        team2: str,
        threshold: float = 0.5,
        *,
        include_odds: bool = True,
    ) -> dict:
        p1 = self._win_probability_team1(team1, team2)
        p1_pct = round(p1 * 100, 1)
        favored = team1 if p1 >= 0.5 else team2

        feat = self.feature_tracker.features_for(team1, team2, tournament=None)
        feature_row = add_engineered_features(pd.DataFrame([feat]).fillna(0)).iloc[0]
        map_preds = sort_map_predictions(
            [
                m
                for m in self.map_predictor.predict_maps(team1, team2, p1_pct)
                if m.get("in_comp_pool")
            ]
        )

        odds = None
        if include_odds:
            try:
                from odds_vlr import fetch_match_odds

                odds = fetch_match_odds(team1, team2)
            except Exception:
                odds = None

        return {
            "team1_win_probability": p1_pct,
            "team2_win_probability": round((1.0 - p1) * 100, 1),
            "team1_win_prediction": p1 >= threshold,
            "confidence": confidence_label(p1_pct),
            "key_factors": build_key_factors(
                team1,
                team2,
                favored,
                feature_row,
                self.recent_form,
                self.agent_diversity,
            ),
            "map_predictions": map_preds,
            "series_predictions": {
                "bo3": simulate_series(map_preds, best_of=3),
                "bo5": simulate_series(map_preds, best_of=5),
            },
            "recent_form": {
                team1: round(self.recent_form.get(team1, 50.0), 1),
                team2: round(self.recent_form.get(team2, 50.0), 1),
            },
            "betting": build_betting_insight(team1, team2, p1, odds=odds),
        }

    def prediction_probability(self, teama, teamb, threshold=0.5):
        return 1 if self.predict_match(teama, teamb, threshold)["team1_win_prediction"] else 0
