"""
Pull newer pro matches from VLR, merge with the Kaggle base dataset, and retrain.

Usage (from server/):
  python scripts/sync_vlr_data.py
  python scripts/sync_vlr_data.py --no-tune   # faster retrain
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SERVER_DIR / "scripts"))

from update_dataset import (  # noqa: E402
    CSV_DIR,
    DEFAULT_MIN_YEAR,
    find_year_dirs,
    load_concat_csv,
    load_merged_player_stats,
    normalize_scores,
    rebuild_pipeline,
)
from tournament_utils import ensure_scores_columns  # noqa: E402
from vlr_ingest import (  # noqa: E402
    SCORE_DEDUPE_COLUMNS,
    fetch_new_vlr_data,
    repair_vlr_player_stats,
    repair_vlr_scores,
)

KAGGLE_DIR = SERVER_DIR / "data" / "kaggle"
RAW_DIR = SERVER_DIR / "data" / "raw"
VLR_PLAYER_STATS_PATH = SERVER_DIR / "data" / "vlr_player_stats.csv"


def load_kaggle_base(min_year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    year_dirs = find_year_dirs(KAGGLE_DIR, min_year=min_year)
    if not year_dirs:
        year_dirs = find_year_dirs(RAW_DIR, min_year=min_year)
    if not year_dirs:
        raise SystemExit(
            "No vct_* Kaggle folders found. Run scripts/update_dataset.py --download first."
        )
    print(f"Kaggle base: {len(year_dirs)} season folders", flush=True)
    scores = normalize_scores(load_concat_csv(year_dirs, "matches", "scores.csv"))
    player_stats = load_concat_csv(year_dirs, "players_stats", "players_stats.csv")
    return scores, player_stats


def load_vlr_player_stats() -> pd.DataFrame:
    if VLR_PLAYER_STATS_PATH.exists():
        return pd.read_csv(VLR_PLAYER_STATS_PATH)
    return pd.DataFrame()


def save_vlr_player_stats(df: pd.DataFrame) -> None:
    VLR_PLAYER_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(VLR_PLAYER_STATS_PATH, index=False)


def main(tune: bool, min_year: int, event_ids: list[str] | None) -> None:
    if CSV_DIR.joinpath("scores.csv").exists():
        scores = ensure_scores_columns(pd.read_csv(CSV_DIR / "scores.csv"))
        print(f"Loaded existing scores.csv ({len(scores)} matches)", flush=True)
    else:
        scores, _ = load_kaggle_base(min_year)
        print(f"Loaded Kaggle scores ({len(scores)} matches)", flush=True)

    try:
        base_players = load_merged_player_stats(min_year=min_year)
    except FileNotFoundError:
        _, base_players = load_kaggle_base(min_year)
    vlr_players = load_vlr_player_stats()

    print("Fetching new matches from VLR...", flush=True)
    new_scores, new_players, new_ids = fetch_new_vlr_data(scores, event_ids=event_ids)

    if new_scores.empty:
        print("No new VLR matches to add. Retraining on existing data...", flush=True)
        merged_scores = repair_vlr_scores(scores)
        merged_players = base_players
    else:
        print(
            f"Adding {len(new_scores)} matches ({len(new_players)} player stat rows) from VLR",
            flush=True,
        )
        merged_scores = pd.concat([scores, new_scores], ignore_index=True)
        merged_scores = repair_vlr_scores(merged_scores)
        merged_scores = merged_scores.drop_duplicates(
            subset=SCORE_DEDUPE_COLUMNS,
            keep="first",
        )

        if not vlr_players.empty:
            vlr_players = pd.concat([vlr_players, new_players], ignore_index=True)
        else:
            vlr_players = new_players
        save_vlr_player_stats(vlr_players)

        vlr_players = repair_vlr_player_stats(vlr_players)
        # Drop cached VLR rows already in base_players to avoid double-counting
        # when base_players already includes vlr_player_stats.csv.
        merged_players = pd.concat([base_players, vlr_players], ignore_index=True)
        merged_players = merged_players.drop_duplicates(
            subset=["Tournament", "Stage", "Match Type", "Player", "Teams", "Agents"],
            keep="last",
        )

    rebuild_pipeline(merged_scores, merged_players, tune=tune)
    print(f"Done. Ingested VLR match ids: {sorted(new_ids)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync VLR matches and retrain model")
    parser.add_argument(
        "--no-tune",
        action="store_true",
        help="Skip hyperparameter search (faster retrain)",
    )
    parser.add_argument(
        "--min-year",
        type=int,
        default=DEFAULT_MIN_YEAR,
        help=f"Kaggle seasons from this year (default: {DEFAULT_MIN_YEAR})",
    )
    parser.add_argument(
        "--event-ids",
        nargs="+",
        metavar="ID",
        help="Ingest specific VLR event ids (includes ongoing events, e.g. 2765 for Masters London)",
    )
    args = parser.parse_args()
    os.chdir(SERVER_DIR)
    main(tune=not args.no_tune, min_year=args.min_year, event_ids=args.event_ids)
