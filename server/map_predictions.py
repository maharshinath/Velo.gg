"""Per-map win probability: if a given map is played, who is more likely to win?"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd

from tournament_utils import is_pro_tournament, shrink_probability
from vct_config import COMP_POOL_MAPS, H2H_MIN_TRUST_MATCHES
from vlr_ingest import VLR_MAPS_PATH, load_vlr_maps

SERVER_DIR = Path(__file__).resolve().parent
CSV_DIR = SERVER_DIR / "csv"
KAGGLE_DIR = SERVER_DIR / "data" / "kaggle"
RAW_DIR = SERVER_DIR / "data" / "raw"
MAP_STATS_PATH = CSV_DIR / "map_team_stats.csv"
MAP_H2H_PATH = CSV_DIR / "map_h2h_stats.csv"

STANDARD_MAPS = [
    "Ascent",
    "Bind",
    "Breeze",
    "Corrode",
    "Fracture",
    "Haven",
    "Icebox",
    "Lotus",
    "Pearl",
    "Split",
    "Summit",
    "Sunset",
    "Abyss",
]

TEAM_ALIASES = {
    "Mega Minors": "NRG",
    "NRG Esports": "NRG",
    "Talon Esports": "TALON",
    "Envy": "ENVY",
    "JD Gaming": "JDG Esports",
}


def normalize_team(name: str) -> str:
    if pd.isna(name):
        return name
    return TEAM_ALIASES.get(str(name).strip(), str(name).strip())


def find_year_dirs(base: Path, min_year: int = 2021) -> list[Path]:
    if not base.exists():
        return []
    dirs = sorted(p for p in base.iterdir() if p.is_dir() and p.name.startswith("vct_"))
    return [p for p in dirs if int(p.name.split("_")[1]) >= min_year]


def load_maps_scores(year_dirs: list[Path]) -> pd.DataFrame:
    frames = []
    for year_dir in year_dirs:
        path = year_dir / "matches" / "maps_scores.csv"
        if path.exists():
            frames.append(pd.read_csv(path))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates()


def filter_pro_map_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    mask = df["Tournament"].astype(str).map(is_pro_tournament)
    out = df.loc[mask].copy()
    out = out[out["Map"].isin(STANDARD_MAPS)]
    for col in ("Team A", "Team B"):
        out[col] = out[col].map(normalize_team)
    return out


def load_merged_map_scores(min_year: int = 2021) -> pd.DataFrame:
    frames = []
    year_dirs = find_year_dirs(KAGGLE_DIR, min_year) or find_year_dirs(RAW_DIR, min_year)
    if year_dirs:
        kaggle_maps = load_maps_scores(year_dirs)
        if not kaggle_maps.empty:
            frames.append(kaggle_maps)
    vlr_maps = load_vlr_maps()
    if not vlr_maps.empty:
        frames.append(vlr_maps)
    if not frames:
        raise FileNotFoundError("No map score data found (Kaggle or VLR)")
    merged = pd.concat(frames, ignore_index=True)
    for col in ("Team A", "Team B"):
        merged[col] = merged[col].map(normalize_team)
    merged = merged.drop_duplicates(
        subset=["Tournament", "Stage", "Match Type", "Map", "Team A", "Team B", "Team A Score", "Team B Score"],
        keep="last",
    )
    return filter_pro_map_rows(merged)


def build_map_team_stats(df: pd.DataFrame) -> pd.DataFrame:
    wins: dict[tuple[str, str], int] = defaultdict(int)
    played: dict[tuple[str, str], int] = defaultdict(int)

    for _, row in df.iterrows():
        map_name = row["Map"]
        team_a, team_b = row["Team A"], row["Team B"]
        try:
            score_a, score_b = int(row["Team A Score"]), int(row["Team B Score"])
        except (TypeError, ValueError):
            continue
        if score_a == score_b:
            continue
        winner = team_a if score_a > score_b else team_b
        for team in (team_a, team_b):
            played[(team, map_name)] += 1
        wins[(winner, map_name)] += 1

    rows = [
        {
            "Team": team,
            "Map": map_name,
            "Wins": wins.get((team, map_name), 0),
            "Played": count,
            "Winrate": round(wins.get((team, map_name), 0) / count * 100, 2),
        }
        for (team, map_name), count in played.items()
    ]
    return pd.DataFrame(rows).sort_values(["Map", "Team"]).reset_index(drop=True)


def build_map_h2h_stats(df: pd.DataFrame) -> pd.DataFrame:
    pair_wins: dict[tuple[str, str, str], int] = defaultdict(int)
    pair_played: dict[tuple[str, str, str], int] = defaultdict(int)

    for _, row in df.iterrows():
        map_name = row["Map"]
        team_a, team_b = row["Team A"], row["Team B"]
        try:
            score_a, score_b = int(row["Team A Score"]), int(row["Team B Score"])
        except (TypeError, ValueError):
            continue
        if score_a == score_b:
            continue
        pair = tuple(sorted((team_a, team_b)))
        key = (pair[0], pair[1], map_name)
        pair_played[key] += 1
        winner = team_a if score_a > score_b else team_b
        if winner == pair[0]:
            pair_wins[key] += 1

    rows = [
        {
            "Team A": t1,
            "Team B": t2,
            "Map": map_name,
            "Team A Wins": pair_wins[key],
            "Played": count,
            "Team A Winrate": round(pair_wins[key] / count * 100, 2),
        }
        for key, count in pair_played.items()
        for t1, t2, map_name in [key]
    ]
    return pd.DataFrame(rows).sort_values(["Map", "Team A"]).reset_index(drop=True)


def refresh_map_csvs(min_year: int = 2021) -> None:
    try:
        maps_df = load_merged_map_scores(min_year=min_year)
    except FileNotFoundError:
        if MAP_STATS_PATH.exists() and MAP_H2H_PATH.exists():
            return
        raise
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    build_map_team_stats(maps_df).to_csv(MAP_STATS_PATH, index=False)
    build_map_h2h_stats(maps_df).to_csv(MAP_H2H_PATH, index=False)


def write_map_csvs(min_year: int = 2021) -> None:
    refresh_map_csvs(min_year=min_year)


class MapPredictor:
    def __init__(self) -> None:
        if not MAP_STATS_PATH.exists():
            refresh_map_csvs()
        self.team_stats = pd.read_csv(MAP_STATS_PATH)
        self.h2h_stats = (
            pd.read_csv(MAP_H2H_PATH) if MAP_H2H_PATH.exists() else pd.DataFrame()
        )
        self._team_lookup: dict[tuple[str, str], dict] = {}
        for _, row in self.team_stats.iterrows():
            self._team_lookup[(row["Team"], row["Map"])] = {
                "wins": int(row["Wins"]),
                "played": int(row["Played"]),
                "winrate": float(row["Winrate"]),
            }

    def _smoothed_rate(self, team: str, map_name: str, default: float) -> float:
        entry = self._team_lookup.get((team, map_name))
        if not entry or entry["played"] == 0:
            return default
        return (entry["wins"] + 1) / (entry["played"] + 2)

    def _map_h2h_rate(self, team1: str, team2: str, map_name: str) -> tuple[float | None, int]:
        if self.h2h_stats.empty:
            return None, 0
        pair = tuple(sorted((team1, team2)))
        row = self.h2h_stats[
            (self.h2h_stats["Team A"] == pair[0])
            & (self.h2h_stats["Team B"] == pair[1])
            & (self.h2h_stats["Map"] == map_name)
        ]
        if row.empty:
            return None, 0
        r = row.iloc[0]
        played = int(r["Played"])
        raw = float(r["Team A Winrate"]) / 100.0 if team1 == pair[0] else 1.0 - float(r["Team A Winrate"]) / 100.0
        return shrink_probability(raw, played, H2H_MIN_TRUST_MATCHES), played

    def predict_maps(self, team1: str, team2: str, overall_team1_prob: float) -> list[dict]:
        overall_p1 = overall_team1_prob / 100.0 if overall_team1_prob > 1 else overall_team1_prob
        predictions = []

        for map_name in COMP_POOL_MAPS:
            r1 = self._smoothed_rate(team1, map_name, default=overall_p1)
            r2 = self._smoothed_rate(team2, map_name, default=1.0 - overall_p1)
            map_p = r1 / (r1 + r2) if (r1 + r2) > 0 else 0.5

            h2h_p, h2h_played = self._map_h2h_rate(team1, team2, map_name)
            if h2h_p is not None:
                h2h_weight = min(1.0, h2h_played / H2H_MIN_TRUST_MATCHES) * 0.4
                map_p = (1.0 - h2h_weight) * map_p + h2h_weight * h2h_p

            t1_entry = self._team_lookup.get((team1, map_name), {"played": 0})
            t2_entry = self._team_lookup.get((team2, map_name), {"played": 0})
            weight = min(1.0, (t1_entry["played"] + t2_entry["played"]) / 20.0)
            blended = (1.0 - 0.25 * weight) * map_p + (0.25 * weight) * overall_p1
            p1 = round(blended * 100, 1)
            p2 = round(100.0 - p1, 1)
            s1 = self._team_lookup.get((team1, map_name))
            s2 = self._team_lookup.get((team2, map_name))
            favored = team1 if p1 >= p2 else team2

            predictions.append(
                {
                    "map": map_name,
                    "team1_win_probability": p1,
                    "team2_win_probability": p2,
                    "team1_map_winrate": s1["winrate"] if s1 else None,
                    "team2_map_winrate": s2["winrate"] if s2 else None,
                    "team1_maps_played": t1_entry["played"],
                    "team2_maps_played": t2_entry["played"],
                    "favored_team": favored,
                    "in_comp_pool": map_name in COMP_POOL_MAPS,
                }
            )

        return predictions


if __name__ == "__main__":
    refresh_map_csvs()
    print(f"Wrote {MAP_STATS_PATH} and {MAP_H2H_PATH}")
