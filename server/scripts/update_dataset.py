"""
Download (optional) and rebuild VCT CSVs + Random Forest model from Kaggle raw data.

Usage (from server/):
  python scripts/update_dataset.py
  python scripts/update_dataset.py --download   # fetch latest Kaggle zip first
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

from feature_engineering import (  # noqa: E402
    PLAYER_STAT_KEYS,
    PLAYER_STAT_SOURCE_COLUMNS,
    build_live_feature_tracker,
    build_match_feature_rows,
    team_profile_from_tracker,
)
from model_training import (  # noqa: E402
    FEATURE_COLS,
    create_order_invariant_data,
    evaluate_time_ordered_accuracy,
    load_model_bundle,
    save_model_bundle,
    score_time_ordered_holdout,
    train_match_model,
)
import vct_config  # noqa: E402

CSV_DIR = SERVER_DIR / "csv"
MODEL_DIR = SERVER_DIR / "models"
MODEL_PATH = MODEL_DIR / "rf.pkl"
KAGGLE_DIR = SERVER_DIR / "data" / "kaggle"
RAW_DIR = SERVER_DIR / "data" / "raw"
VLR_PLAYER_STATS_PATH = SERVER_DIR / "data" / "vlr_player_stats.csv"
# Candidate must beat deployed model on the same holdout by at least this much.
PROMOTION_MARGIN = 0.5


def deployed_holdout_on_matches(filtered_matches: pd.DataFrame) -> float | None:
    """Deployed model accuracy on the current time-ordered holdout."""
    if not MODEL_PATH.exists():
        return None
    deployed, feature_cols = load_model_bundle(MODEL_PATH)
    return score_time_ordered_holdout(
        deployed, filtered_matches, feature_cols, test_size=0.2
    )

TEAM_ALIASES = {
    "Mega Minors": "NRG",
    "NRG Esports": "NRG",
    "Talon Esports": "TALON",
    "Envy": "ENVY",
}

LOGO_FILE_OVERRIDES = {
    "EDward Gaming": "edward-gaming-logo.png",
    "KRÜ Esports": "kru-logo.png",
    "LEVIATÁN": "leviatan-logo.png",
    "Gen.G": "gen.g-logo.png",
    "Xi Lai Gaming": "xilai-logo.png",
    "JDG Esports": "jd-gaming-logo.png",
    "Made in Thailand": "made-in-thailand-logo.png",
}

# Showmatch / all-star teams to drop from the dropdown
EXCLUDED_TEAMS = {
    "Team Alpha",
    "Team Omega",
    "Team EMEA",
    "Team France",
    "Team International",
    "Team Thailand",
    "Team World",
    "Glory Once Again",
    "Pure Aim",
    "Precise Defeat",
}

PRO_TOURNAMENT_PATTERN = r"Valorant Champions|Valorant Masters|Esports World Cup|VCT \d{4}:"
DEFAULT_MIN_YEAR = 2021

# Teams that only appear in global events (Masters/Champions) without a regional VCT tag
TEAM_REGION_OVERRIDES = {
    "Acend": "EMEA",
    "Crazy Raccoon": "Pacific",
    "F4Q": "Pacific",
    "Gambit Esports": "EMEA",
    "Giants Gaming": "EMEA",
    "Guild Esports": "EMEA",
    "Keyd Stars": "AMER",
    "Liberty": "AMER",
    "Ninjas In Pyjamas": "EMEA",
    "NORTHEPTION": "Pacific",
    "NUTURN": "Pacific",
    "OpTic Gaming": "AMER",
    "Papara SuperMassive": "EMEA",
    "Sharks Esports": "AMER",
    "The Guard": "AMER",
    "Team Vikings": "AMER",
    "Version1": "AMER",
    "Vision Strikers": "Pacific",
    "X10 Esports": "Pacific",
    "XERXIA Esports": "Pacific",
    "XSET": "AMER",
}

from map_predictions import load_merged_map_scores, refresh_map_csvs  # noqa: E402
from tournament_utils import (  # noqa: E402
    ensure_scores_columns,
    is_pro_tournament,
    sort_scores_chronologically,
)


def download_kaggle_dataset() -> None:
    KAGGLE_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "kaggle",
            "datasets",
            "download",
            "-d",
            "ryanluong1/valorant-champion-tour-2021-2023-data",
            "-p",
            str(KAGGLE_DIR),
            "--unzip",
        ],
        check=True,
    )


def find_year_dirs(base: Path, min_year: int | None = None) -> list[Path]:
    if not base.exists():
        return []
    dirs = sorted(p for p in base.iterdir() if p.is_dir() and p.name.startswith("vct_"))
    if min_year is not None:
        dirs = [p for p in dirs if int(p.name.split("_")[1]) >= min_year]
    return dirs


def load_concat_csv(year_dirs: list[Path], *parts: str) -> pd.DataFrame:
    frames = []
    for year_dir in year_dirs:
        path = year_dir.joinpath(*parts)
        if path.exists():
            frames.append(pd.read_csv(path))
    if not frames:
        raise FileNotFoundError(f"No files found for {'/'.join(parts)} under {year_dirs[0].parent}")
    combined = pd.concat(frames, ignore_index=True)
    return combined.drop_duplicates()


def normalize_team(name: str) -> str:
    if pd.isna(name):
        return name
    name = str(name).strip()
    return TEAM_ALIASES.get(name, name)


def filter_pro_matches(df: pd.DataFrame) -> pd.DataFrame:
    mask = df["Tournament"].astype(str).map(is_pro_tournament)
    out = df.loc[mask].copy()
    for col in ("Team A", "Team B"):
        out = out[~out[col].isin(EXCLUDED_TEAMS)]
    return out


def normalize_scores(df: pd.DataFrame) -> pd.DataFrame:
    out = filter_pro_matches(df.copy())
    for col in ("Team A", "Team B"):
        out[col] = out[col].map(normalize_team)

    def fix_result(row):
        result = str(row["Match Result"])
        for alias, canonical in TEAM_ALIASES.items():
            if result == f"{alias} won":
                return f"{canonical} won"
        return result

    out["Match Result"] = out.apply(fix_result, axis=1)
    out["Match Name"] = out["Team A"] + " vs " + out["Team B"]
    if "Match Date" not in out.columns:
        out["Match Date"] = None
    return ensure_scores_columns(out)


def load_merged_player_stats(min_year: int | None = None) -> pd.DataFrame:
    """Kaggle base player stats merged with repaired VLR supplements."""
    from vlr_ingest import repair_vlr_player_stats

    year_dirs = find_year_dirs(KAGGLE_DIR, min_year=min_year)
    if not year_dirs:
        year_dirs = find_year_dirs(RAW_DIR, min_year=min_year)
    if not year_dirs:
        cached = CSV_DIR / "player_stats_merged.csv"
        if cached.exists():
            repaired = repair_vlr_player_stats(pd.read_csv(cached))
            return repaired
        raise FileNotFoundError("No Kaggle player stats and no cached player_stats_merged.csv")

    player_stats = load_concat_csv(year_dirs, "players_stats", "players_stats.csv")
    if VLR_PLAYER_STATS_PATH.exists():
        vlr = repair_vlr_player_stats(pd.read_csv(VLR_PLAYER_STATS_PATH))
        VLR_PLAYER_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        vlr.to_csv(VLR_PLAYER_STATS_PATH, index=False)
        player_stats = pd.concat([player_stats, vlr], ignore_index=True)
        player_stats = player_stats.drop_duplicates(
            subset=["Tournament", "Stage", "Match Type", "Player", "Teams", "Agents"],
            keep="last",
        )
    player_stats["Teams"] = player_stats["Teams"].astype(str).str.strip()
    return player_stats


def aggregate_player_stats(player_stats: pd.DataFrame) -> pd.DataFrame:
    from feature_engineering import aggregate_player_rows

    stats = player_stats.copy()
    stats["Teams"] = stats["Teams"].astype(str).str.strip()
    records: list[dict] = []
    for team, group in stats.groupby("Teams", sort=False):
        row = aggregate_player_rows(group)
        if row:
            records.append({"Team": team, **row})
    grouped = pd.DataFrame(records)
    for key in PLAYER_STAT_KEYS:
        if key not in grouped.columns:
            grouped[key] = None
    return grouped


def get_average_player_stats(player_stats: pd.DataFrame, team: str) -> dict | None:
    filtered = player_stats[player_stats["Teams"] == team]
    if filtered.empty:
        return None
    from feature_engineering import aggregate_player_rows

    return aggregate_player_rows(filtered)


def slugify_team(team: str) -> str:
    slug = team.lower().replace(".", "").replace("'", "")
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def logo_filename(team: str) -> str:
    if team in LOGO_FILE_OVERRIDES:
        return LOGO_FILE_OVERRIDES[team]
    return f"{slugify_team(team)}-logo.png"


def load_existing_logo_map() -> dict[str, str]:
    path = CSV_DIR / "team_data.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    logo_map = {}
    for team, image_path in zip(df["Team"], df["Image Path"]):
        if isinstance(image_path, str) and image_path.startswith("/static/"):
            logo_map[team] = image_path
    return logo_map


def active_teams(scores: pd.DataFrame) -> set[str]:
    return set(scores["Team A"]) | set(scores["Team B"])


def region_from_tournament(tournament: str) -> str | None:
    name = str(tournament)
    if re.search(r"VCT \d{4}: Americas|: Americas", name):
        return "AMER"
    if re.search(r"VCT \d{4}: EMEA|: EMEA", name):
        return "EMEA"
    if re.search(r"VCT \d{4}: Pacific|: Pacific", name):
        return "Pacific"
    if re.search(r"VCT \d{4}: China|: China", name):
        return "CN"
    return None


def build_team_regions(scores: pd.DataFrame, teams: set[str]) -> dict[str, str]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for _, row in scores.iterrows():
        region = region_from_tournament(row["Tournament"])
        if not region:
            continue
        for team in (row["Team A"], row["Team B"]):
            if team in teams:
                counts[team][region] += 1

    regions: dict[str, str] = {}
    for team in teams:
        if counts[team]:
            regions[team] = counts[team].most_common(1)[0][0]
        elif team in TEAM_REGION_OVERRIDES:
            regions[team] = TEAM_REGION_OVERRIDES[team]
    return regions


def build_team_data(scores: pd.DataFrame, player_stats: pd.DataFrame) -> pd.DataFrame:
    player_stats = player_stats.copy()
    player_stats["Teams"] = player_stats["Teams"].map(normalize_team)
    teams = active_teams(scores)
    tracker = build_live_feature_tracker(scores, player_stats)

    logo_map = load_existing_logo_map()
    logos_dir = SERVER_DIR / "static" / "logos"
    team_regions = build_team_regions(scores, teams)

    records = []
    for team in sorted(teams):
        profile = team_profile_from_tracker(tracker, team)
        records.append(
            {
                "Team": team,
                **profile,
                "Image Path": resolve_image_path(team, logo_map, logos_dir),
                "Region": team_regions.get(team),
            }
        )

    stat_rows = pd.DataFrame(records)
    stat_rows = stat_rows.sort_values("Team").reset_index(drop=True)
    stat_rows["id"] = range(1, len(stat_rows) + 1)
    return stat_rows


def resolve_image_path(team: str, logo_map: dict[str, str], logos_dir: Path) -> str:
    preferred = logo_filename(team)
    if (logos_dir / preferred).exists():
        return f"/static/logos/{preferred}"
    legacy = logo_map.get(team)
    if legacy and (logos_dir / Path(legacy).name).exists():
        return legacy
    return f"/static/logos/{preferred}"


def build_match_features(
    scores: pd.DataFrame,
    player_stats: pd.DataFrame,
    *,
    map_scores: pd.DataFrame | None = None,
) -> pd.DataFrame:
    return build_match_feature_rows(scores, player_stats, map_scores=map_scores)


def _persist_elo_tuning(k: float, sweep: float, close: float) -> None:
    """Write selected Elo K/margins into vct_config so live PIT Elo matches training."""
    path = SERVER_DIR / "vct_config.py"
    text = path.read_text(encoding="utf-8")
    replacements = {
        r"^ELO_K_FACTOR = .*$": f"ELO_K_FACTOR = {float(k)}",
        r"^ELO_MARGIN_SWEEP = .*$": f"ELO_MARGIN_SWEEP = {float(sweep)}  # margin >= 2 maps",
        r"^ELO_MARGIN_CLOSE = .*$": f"ELO_MARGIN_CLOSE = {float(close)}  # margin == 1",
    }
    for pattern, repl in replacements.items():
        text, n = re.subn(pattern, repl, text, count=1, flags=re.M)
        if n != 1:
            print(f"Warning: could not persist Elo setting via pattern {pattern!r}", flush=True)
    path.write_text(text, encoding="utf-8")


def rebuild_pipeline(
    scores: pd.DataFrame,
    player_stats: pd.DataFrame,
    *,
    tune: bool = True,
    min_holdout_accuracy: float | None = None,
) -> dict:
    """Rebuild team CSVs, filtered matches, and retrain the match-winner model."""
    model_backup: bytes | None = None
    vct_config_backup: str | None = None
    if MODEL_PATH.exists():
        model_backup = MODEL_PATH.read_bytes()
        vct_config_path = SERVER_DIR / "vct_config.py"
        if vct_config_path.exists():
            vct_config_backup = vct_config_path.read_text(encoding="utf-8")
    scores = sort_scores_chronologically(scores)
    player_stats = player_stats.copy()
    player_stats["Teams"] = player_stats["Teams"].map(normalize_team)

    print("Refreshing map stats...", flush=True)
    refresh_map_csvs()
    try:
        map_scores = load_merged_map_scores()
    except FileNotFoundError:
        map_scores = None

    print("Building team_data.csv...", flush=True)
    team_data = build_team_data(scores, player_stats)

    elo_tune: dict | None = None
    if tune:
        print("Grid-searching Elo K / margin on time-ordered holdout...", flush=True)
        k_grid = [24.0, 32.0, 40.0]
        margin_grid = [
            (1.25, 0.85),
            (1.10, 0.95),
            (1.15, 0.90),
        ]
        best_acc = -1.0
        best_k = float(vct_config.ELO_K_FACTOR)
        best_sweep = float(vct_config.ELO_MARGIN_SWEEP)
        best_close = float(vct_config.ELO_MARGIN_CLOSE)
        best_matches: pd.DataFrame | None = None
        for k in k_grid:
            for sweep, close in margin_grid:
                vct_config.ELO_K_FACTOR = float(k)
                vct_config.ELO_MARGIN_SWEEP = float(sweep)
                vct_config.ELO_MARGIN_CLOSE = float(close)
                candidate = build_match_features(scores, player_stats, map_scores=map_scores)
                acc = evaluate_time_ordered_accuracy(candidate)
                print(
                    f"  K={k:g} sweep={sweep} close={close} -> Elo holdout {acc * 100:.1f}%",
                    flush=True,
                )
                if acc > best_acc:
                    best_acc = acc
                    best_k = float(k)
                    best_sweep = float(sweep)
                    best_close = float(close)
                    best_matches = candidate
        vct_config.ELO_K_FACTOR = best_k
        vct_config.ELO_MARGIN_SWEEP = best_sweep
        vct_config.ELO_MARGIN_CLOSE = best_close
        filtered_matches = best_matches if best_matches is not None else build_match_features(
            scores, player_stats, map_scores=map_scores
        )
        elo_tune = {
            "elo_k": best_k,
            "elo_margin_sweep": best_sweep,
            "elo_margin_close": best_close,
            "elo_grid_holdout_accuracy": round(best_acc * 100, 1),
        }
        print(
            f"Selected Elo config: K={best_k:g} sweep={best_sweep} close={best_close} "
            f"({best_acc * 100:.1f}% Elo holdout)",
            flush=True,
        )
    else:
        print("Building filtered_matches.csv (point-in-time features)...", flush=True)
        filtered_matches = build_match_features(scores, player_stats, map_scores=map_scores)

    deployed_holdout = deployed_holdout_on_matches(filtered_matches)
    if min_holdout_accuracy is not None:
        promotion_target = float(min_holdout_accuracy)
    elif deployed_holdout is not None:
        promotion_target = deployed_holdout + PROMOTION_MARGIN
        print(
            f"Promotion gate: candidate must beat deployed "
            f"({deployed_holdout:.1f}%) by ≥{PROMOTION_MARGIN:.1f}% "
            f"→ {promotion_target:.1f}%",
            flush=True,
        )
    else:
        promotion_target = None

    print("Training model (time-ordered split)...", flush=True)

    CSV_DIR.mkdir(parents=True, exist_ok=True)
    scores.to_csv(CSV_DIR / "scores.csv", index=False)
    player_stats.to_csv(CSV_DIR / "player_stats_merged.csv", index=False)
    team_data.to_csv(CSV_DIR / "team_data.csv", index=False)
    filtered_matches.to_csv(CSV_DIR / "filtered_matches.csv", index=False)

    model, report = train_match_model(filtered_matches, tune=tune, time_ordered=True)
    if elo_tune:
        report.setdefault("best_params", {})
        if isinstance(report["best_params"], dict):
            report["best_params"] = {**report["best_params"], **elo_tune}
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    save_model_bundle(
        MODEL_DIR / "rf.pkl",
        model,
        feature_cols=report.get("feature_cols"),
        algorithm=str(report.get("algorithm") or "elo_anchored"),
        metrics={
            "holdout_test_accuracy": report["test_accuracy"],
            "train_accuracy": report["train_accuracy"],
            "elo_test_accuracy": report.get("elo_test_accuracy"),
            "refit_full": report.get("refit_full", False),
            "algorithm": report.get("algorithm"),
            "best_params": report.get("best_params"),
        },
    )
    new_holdout = float(report["test_accuracy"])
    print(f"Train accuracy: {report['train_accuracy']}%")
    print(f"Holdout test accuracy: {new_holdout}%")
    print(f"Elo-only holdout: {report.get('elo_test_accuracy')}%")
    print(f"Best params: {report['best_params']}")
    print(f"Algorithm: {report.get('algorithm', 'unknown')}")

    promoted = (
        promotion_target is None or new_holdout + 1e-9 >= promotion_target
    )
    report["model_promoted"] = promoted
    report["deployed_holdout_accuracy"] = deployed_holdout
    report["promotion_target"] = promotion_target

    if promoted:
        if elo_tune:
            _persist_elo_tuning(
                float(elo_tune["elo_k"]),
                float(elo_tune["elo_margin_sweep"]),
                float(elo_tune["elo_margin_close"]),
            )
        subprocess.run(
            [sys.executable, "scripts/evaluate_model.py"],
            cwd=SERVER_DIR,
            check=True,
        )
        print(f"Promoted model ({new_holdout}% holdout). Saved to {MODEL_PATH}")
    else:
        if model_backup is not None:
            MODEL_PATH.write_bytes(model_backup)
        if vct_config_backup is not None:
            (SERVER_DIR / "vct_config.py").write_text(
                vct_config_backup, encoding="utf-8"
            )
            print("Rebuilding team CSVs with deployed Elo config...", flush=True)
            filtered_matches = build_match_features(
                scores, player_stats, map_scores=map_scores
            )
            team_data = build_team_data(scores, player_stats)
            filtered_matches.to_csv(CSV_DIR / "filtered_matches.csv", index=False)
            team_data.to_csv(CSV_DIR / "team_data.csv", index=False)
        baseline = (
            f"{deployed_holdout:.1f}% deployed"
            if deployed_holdout is not None
            else f"{promotion_target:.1f}%"
        )
        print(
            f"Holdout {new_holdout:.1f}% did not beat {baseline} "
            f"(need ≥{promotion_target:.1f}%) — CSVs updated; kept deployed model.",
            flush=True,
        )
        subprocess.run(
            [sys.executable, "scripts/evaluate_model.py"],
            cwd=SERVER_DIR,
            check=True,
        )

    print(f"scores.csv: {len(scores)} matches")
    print(f"team_data.csv: {len(team_data)} teams")
    print(f"filtered_matches.csv: {len(filtered_matches)} training rows")
    return report


def main(download: bool, min_year: int) -> None:
    if download:
        print("Downloading Kaggle dataset...")
        download_kaggle_dataset()

    year_dirs = find_year_dirs(KAGGLE_DIR, min_year=min_year)
    if not year_dirs:
        year_dirs = find_year_dirs(RAW_DIR, min_year=min_year)
    if not year_dirs:
        raise SystemExit(
            "No vct_* data folders found. Run with --download or place raw data under server/data/kaggle/"
        )

    print(f"Using {len(year_dirs)} season folders: {[p.name for p in year_dirs]}", flush=True)

    print("Loading match results...", flush=True)
    scores = normalize_scores(
        load_concat_csv(year_dirs, "matches", "scores.csv")
    )
    print("Loading player stats...", flush=True)
    player_stats = load_concat_csv(year_dirs, "players_stats", "players_stats.csv")

    rebuild_pipeline(scores, player_stats, tune=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rebuild VCT dataset and model")
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download latest data from Kaggle before processing",
    )
    parser.add_argument(
        "--min-year",
        type=int,
        default=DEFAULT_MIN_YEAR,
        help=f"Only include seasons from this year onward (default: {DEFAULT_MIN_YEAR})",
    )
    parser.add_argument(
        "--all-years",
        action="store_true",
        help="Include all seasons (2021+) including Challengers data",
    )
    args = parser.parse_args()
    os.chdir(SERVER_DIR)
    min_year = None if args.all_years else args.min_year
    main(download=args.download, min_year=min_year or 2021)
