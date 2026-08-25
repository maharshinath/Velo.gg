"""Fetch current team rosters (players + coaches) from the VLR API."""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd
import requests

SERVER_DIR = Path(__file__).resolve().parent
KAGGLE_DIR = SERVER_DIR / "data" / "kaggle"
VLR_TEAM_IDS_PATH = SERVER_DIR / "data" / "vlr_team_ids.json"
PLAYER_STATS_MERGED = SERVER_DIR / "csv" / "player_stats_merged.csv"
VLR_PLAYER_STATS = SERVER_DIR / "data" / "vlr_player_stats.csv"
ROSTER_CACHE_PATH = SERVER_DIR / "data" / "team_rosters.json"
VLR_TEAM_API = "https://vlr.orlandomm.net/api/v1/teams/{team_id}"

TEAM_ALIASES = {
    "Mega Minors": "NRG",
    "NRG Esports": "NRG",
    "Talon Esports": "TALON",
    "Envy": "ENVY",
}

CACHE_TTL_SECONDS = 6 * 60 * 60
_memory_cache: dict[str, tuple[float, dict]] = {}


def normalize_team(name: str) -> str:
    return TEAM_ALIASES.get(name.strip(), name.strip())


def build_vlr_id_lookup() -> dict[str, int]:
    """Map team name to VLR id. Prefer shipped JSON (Render has no Kaggle dump)."""
    lookup: dict[str, int] = {}
    if VLR_TEAM_IDS_PATH.exists():
        try:
            raw = json.loads(VLR_TEAM_IDS_PATH.read_text(encoding="utf-8"))
            lookup.update({str(k): int(v) for k, v in raw.items()})
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass
    if not KAGGLE_DIR.is_dir():
        return lookup
    best_year: dict[str, int] = {}
    for path in sorted(KAGGLE_DIR.glob("vct_*/ids/teams_ids.csv")):
        year_match = re.search(r"vct_(\d{4})", path.as_posix())
        if not year_match:
            continue
        year = int(year_match.group(1))
        df = pd.read_csv(path)
        df = df.dropna(subset=["Team ID"])
        for team, team_id in zip(df["Team"], df["Team ID"]):
            name = str(team).strip()
            tid = int(team_id)
            for key in (name, normalize_team(name)):
                if year >= best_year.get(key, 0):
                    best_year[key] = year
                    lookup[key] = tid
    return lookup


def _person_label(entry: dict) -> dict:
    ign = (entry.get("user") or "").strip()
    full_name = (entry.get("name") or "").strip()
    return {
        "ign": ign or full_name,
        "name": full_name if full_name and full_name != ign else None,
    }


def _parse_vlr_payload(payload: dict) -> dict:
    data = payload.get("data", {})
    players = [_person_label(p) for p in data.get("players", [])]
    coaches = []
    for member in data.get("staff", []):
        tag = str(member.get("tag") or "").lower()
        if "coach" not in tag:
            continue
        person = _person_label(member)
        person["role"] = member.get("tag")
        coaches.append(person)
    return {
        "players": players,
        "coaches": coaches,
        "source": "vlr",
    }


def _players_from_stats_csv(path: Path, team: str) -> list[dict]:
    if not path.exists():
        return []
    try:
        df = pd.read_csv(path, usecols=["Player", "Teams"])
    except (ValueError, OSError):
        return []
    df["Teams"] = df["Teams"].astype(str).map(normalize_team)
    filtered = df[df["Teams"] == team]
    if filtered.empty:
        return []
    players = []
    seen: set[str] = set()
    for player in reversed(filtered["Player"].tolist()):
        name = str(player).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        players.append({"ign": name, "name": None})
        if len(players) == 5:
            break
    return players


def _roster_from_player_stats(team: str) -> dict:
    """Fallback when VLR is unreachable: latest players from shipped CSVs, then Kaggle."""
    for path in (VLR_PLAYER_STATS, PLAYER_STATS_MERGED):
        players = _players_from_stats_csv(path, team)
        if players:
            return {"players": players, "coaches": [], "source": "dataset"}
    if KAGGLE_DIR.is_dir():
        year_dirs = sorted(
            (p for p in KAGGLE_DIR.iterdir() if p.is_dir() and p.name.startswith("vct_")),
            key=lambda p: p.name,
            reverse=True,
        )
        for season_dir in year_dirs:
            players = _players_from_stats_csv(
                season_dir / "players_stats" / "players_stats.csv", team
            )
            if players:
                return {"players": players, "coaches": [], "source": "dataset"}
    return {"players": [], "coaches": [], "source": "unavailable"}


def _load_disk_cache() -> dict[str, dict]:
    if not ROSTER_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(ROSTER_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_disk_cache(cache: dict[str, dict]) -> None:
    ROSTER_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROSTER_CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def get_team_roster(team: str) -> dict:
    canonical = normalize_team(team)
    now = time.time()

    cached = _memory_cache.get(canonical)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    disk = _load_disk_cache()
    disk_entry = disk.get(canonical)
    if disk_entry and now - disk_entry.get("_cached_at", 0) < CACHE_TTL_SECONDS:
        roster = {k: v for k, v in disk_entry.items() if not k.startswith("_")}
        _memory_cache[canonical] = (now, roster)
        return roster

    vlr_ids = build_vlr_id_lookup()
    team_id = vlr_ids.get(canonical) or vlr_ids.get(team)
    roster: dict
    if team_id:
        try:
            resp = requests.get(
                VLR_TEAM_API.format(team_id=team_id),
                timeout=20,
                headers={"User-Agent": "Velo.gg roster (https://velo-gg.onrender.com)"},
            )
            resp.raise_for_status()
            roster = _parse_vlr_payload(resp.json())
        except (requests.RequestException, ValueError, KeyError):
            roster = _roster_from_player_stats(canonical)
    else:
        roster = _roster_from_player_stats(canonical)

    roster = {"team": team, **roster}
    _memory_cache[canonical] = (now, roster)
    if roster.get("players") or roster.get("source") == "vlr":
        disk[canonical] = {**roster, "_cached_at": now}
        _save_disk_cache(disk)
    return roster
