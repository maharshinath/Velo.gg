"""
Backfill historical pro events (EWC, Masters, etc.) from VLR and retrain.

Usage (from server/):
  python scripts/backfill_pro_events.py
  python scripts/backfill_pro_events.py --no-tune
  python scripts/backfill_pro_events.py --event-ids 2765 1234
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SERVER_DIR / "scripts"))

from update_dataset import CSV_DIR, rebuild_pipeline  # noqa: E402
from tournament_utils import ensure_scores_columns, is_pro_tournament  # noqa: E402
from vlr_ingest import (  # noqa: E402
    SCORE_DEDUPE_COLUMNS,
    _session,
    events_missing_from_scores,
    fetch_new_vlr_data,
    fetch_pro_events,
    repair_vlr_player_stats,
    repair_vlr_scores,
    search_pro_events,
)

KAGGLE_DIR = SERVER_DIR / "data" / "kaggle"
RAW_DIR = SERVER_DIR / "data" / "raw"
VLR_PLAYER_STATS_PATH = SERVER_DIR / "data" / "vlr_player_stats.csv"


def load_kaggle_players() -> pd.DataFrame:
    from update_dataset import load_merged_player_stats

    try:
        return load_merged_player_stats()
    except FileNotFoundError:
        return pd.DataFrame()


def discover_backfill_event_ids(scores: pd.DataFrame) -> list[str]:
    session = _session()
    completed = fetch_pro_events(session, max_pages=25, statuses=("completed",))
    ongoing = fetch_pro_events(session, max_pages=10, statuses=("ongoing",))
    historical = search_pro_events(
        session,
        keywords=("world cup", "ewc", "esports world cup"),
        max_pages=40,
        statuses=("completed",),
    )
    missing = events_missing_from_scores(scores, completed + historical)
    by_id = {e["id"]: e for e in missing}
    for event in ongoing + historical:
        if is_pro_tournament(event["name"]) or "world cup" in event["name"].lower():
            by_id[event["id"]] = event
    seen_names: set[str] = set()
    deduped: list[str] = []
    all_events = list(by_id.values()) + completed + ongoing + historical
    for eid in by_id.keys():
        match = next((e for e in all_events if e["id"] == eid), None)
        if not match:
            continue
        name = match["name"]
        if name in seen_names:
            continue
        seen_names.add(name)
        deduped.append(eid)
    return deduped


def main(tune: bool, event_ids: list[str] | None) -> None:
    scores_path = CSV_DIR / "scores.csv"
    if scores_path.exists():
        scores = ensure_scores_columns(pd.read_csv(scores_path))
        print(f"Loaded scores.csv ({len(scores)} matches)", flush=True)
    else:
        raise SystemExit("scores.csv not found. Run update_dataset.py or sync_vlr_data.py first.")

    if event_ids is None:
        event_ids = discover_backfill_event_ids(scores)
        print(f"Discovered {len(event_ids)} event(s) to scan", flush=True)

    if not event_ids:
        print("No backfill events found.", flush=True)
        return

    kaggle_players = load_kaggle_players()
    vlr_players = (
        pd.read_csv(VLR_PLAYER_STATS_PATH) if VLR_PLAYER_STATS_PATH.exists() else pd.DataFrame()
    )

    new_scores, new_players, new_ids = fetch_new_vlr_data(scores, event_ids=event_ids)
    if new_scores.empty:
        print("No new matches to backfill.", flush=True)
        return

    print(f"Backfilling {len(new_scores)} matches from VLR", flush=True)
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
    VLR_PLAYER_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    vlr_players.to_csv(VLR_PLAYER_STATS_PATH, index=False)
    vlr_players = repair_vlr_player_stats(vlr_players)

    merged_players = pd.concat([kaggle_players, vlr_players], ignore_index=True)
    merged_players = merged_players.drop_duplicates(
        subset=["Tournament", "Stage", "Match Type", "Player", "Teams", "Agents"],
        keep="last",
    )

    rebuild_pipeline(merged_scores, merged_players, tune=tune)
    subprocess.run(
        [sys.executable, "scripts/evaluate_model.py"],
        cwd=SERVER_DIR,
        check=True,
    )
    print(f"Done. Ingested match ids: {sorted(new_ids)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill missing pro events from VLR")
    parser.add_argument("--no-tune", action="store_true")
    parser.add_argument("--event-ids", nargs="+", metavar="ID")
    args = parser.parse_args()
    os.chdir(SERVER_DIR)
    main(tune=not args.no_tune, event_ids=args.event_ids)
