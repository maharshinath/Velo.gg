"""Fetch pro match results and player stats from VLR (vlr.orlandomm.net + vlr.gg)."""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

SERVER_DIR = Path(__file__).resolve().parent
VLR_API = "https://vlr.orlandomm.net/api/v1"
VLR_MATCH_URL = "https://www.vlr.gg/{match_id}/{slug}"
INGESTED_IDS_PATH = SERVER_DIR / "data" / "vlr_ingested_match_ids.json"
REQUEST_DELAY = 0.4
API_TIMEOUT = 90
API_RETRIES = 5


def _safe_print(msg: str) -> None:
    """Print without crashing on Windows consoles that cannot encode team names."""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(msg.encode(encoding, errors="replace").decode(encoding, errors="replace"), flush=True)

TEAM_ALIASES = {
    "Mega Minors": "NRG",
    "NRG Esports": "NRG",
    "Talon Esports": "TALON",
    "Envy": "ENVY",
    "JD Gaming": "JDG Esports",
}

REGION_SHORT = {
    "AMER": "Americas",
    "EMEA": "EMEA",
    "PAC": "Pacific",
    "PACIFIC": "Pacific",
    "CN": "China",
    "CHINA": "China",
}

from tournament_utils import (
    MAPS_SCORES_COLUMNS,
    SCORES_COLUMNS,
    is_pro_event_name,
    normalize_map_name,
    normalize_tournament_name,
)

PLAYER_STATS_COLUMNS = [
    "Tournament",
    "Stage",
    "Match Type",
    "Player",
    "Teams",
    "Agents",
    "Rounds Played",
    "Rating",
    "Average Combat Score",
    "Kills:Deaths",
    "Kill, Assist, Trade, Survive %",
    "Average Damage Per Round",
    "Kills Per Round",
    "Assists Per Round",
    "First Kills Per Round",
    "First Deaths Per Round",
    "Headshot %",
    "Clutch Success %",
    "Clutches (won/played)",
    "Maximum Kills in a Single Map",
    "Kills",
    "Deaths",
    "Assists",
    "First Kills",
    "First Deaths",
]

VLR_MAPS_PATH = SERVER_DIR / "data" / "vlr_maps_scores.csv"


@dataclass
class VlrMatch:
    match_id: str
    url: str
    tournament: str
    team_a: str
    team_b: str
    score_a: int
    score_b: int
    winner: str
    stage: str = "Main Event"
    match_type: str = "Match"
    match_date: str | None = None
    player_rows: list[dict[str, Any]] = field(default_factory=list)
    map_rows: list[dict[str, Any]] = field(default_factory=list)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Velo.gg/1.0 (dataset sync)"})
    return s


def _get_with_retry(
    session: requests.Session,
    url: str,
    *,
    params: dict | None = None,
    timeout: int = API_TIMEOUT,
    retries: int = API_RETRIES,
) -> requests.Response | None:
    last_resp: requests.Response | None = None
    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            last_resp = resp
            # Retry transient upstream failures (VLR mirror flaps with 503 often).
            if resp.status_code in (429, 502, 503, 504) and attempt + 1 < retries:
                time.sleep(REQUEST_DELAY * (attempt + 3))
                continue
            return resp
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt + 1 >= retries:
                raise
            time.sleep(REQUEST_DELAY * (attempt + 2))
    return last_resp


def normalize_team(name: str, canonical: set[str] | None = None) -> str:
    if pd.isna(name):
        return name
    name = TEAM_ALIASES.get(str(name).strip(), str(name).strip())
    if not canonical:
        return name
    if name in canonical:
        return name
    lower = name.lower()
    for team in canonical:
        if team.lower() == lower:
            return team
    for team in canonical:
        if team.lower().replace(" esports", "") == lower.replace(" esports", ""):
            return team
    return name


def normalize_tournament(name: str) -> str:
    return normalize_tournament_name(name)


def _vlrgg_event_title(session: requests.Session, event_id: str) -> str | None:
    """Resolve a human event name when the events API/list scrape misses an id."""
    resp = _get_with_retry(session, f"https://www.vlr.gg/event/{event_id}")
    if resp is None or resp.status_code != 200:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    h1 = soup.select_one("h1")
    if not h1:
        return None
    title = normalize_tournament(h1.get_text(" ", strip=True))
    if not title or title.lower().startswith("vlr event"):
        return None
    return title


def is_pro_event(name: str) -> bool:
    return is_pro_event_name(name)


def load_ingested_ids() -> set[str]:
    if not INGESTED_IDS_PATH.exists():
        return set()
    try:
        data = json.loads(INGESTED_IDS_PATH.read_text(encoding="utf-8"))
        return set(str(x) for x in data.get("match_ids", []))
    except (json.JSONDecodeError, OSError):
        return set()


def save_ingested_ids(ids: set[str]) -> None:
    INGESTED_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    INGESTED_IDS_PATH.write_text(
        json.dumps({"match_ids": sorted(ids)}, indent=2),
        encoding="utf-8",
    )


def fetch_pro_events_from_vlrgg(
    session: requests.Session,
    *,
    statuses: tuple[str, ...] = ("completed", "ongoing"),
) -> list[dict]:
    """Fallback event discovery when the orlandomm events API is unavailable."""
    resp = _get_with_retry(session, "https://www.vlr.gg/events")
    if resp is None or resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    events: list[dict] = []
    seen: set[str] = set()
    for anchor in soup.select('a[href*="/event/"]'):
        href = anchor.get("href") or ""
        m = re.search(r"/event/(\d+)", href)
        if not m:
            continue
        eid = m.group(1)
        if eid in seen:
            continue
        seen.add(eid)
        text = " ".join(anchor.get_text(" ", strip=True).split())
        status = "upcoming"
        lowered = text.lower()
        if "completed" in lowered:
            status = "completed"
        elif "ongoing" in lowered:
            status = "ongoing"
        elif "upcoming" in lowered or "paused" in lowered:
            status = "upcoming"
        if status not in statuses:
            continue
        # Prefer the event title from the slug when the card text is noisy.
        slug_m = re.search(r"/event/\d+/([^/?#]+)", href)
        raw_name = slug_m.group(1).replace("-", " ") if slug_m else text
        # Prefer the leading title before status markers when available.
        title = re.split(
            r"\b(?:ongoing|completed|upcoming|paused)\b",
            text,
            maxsplit=1,
            flags=re.I,
        )[0].strip()
        name = normalize_tournament(title or raw_name)
        if not is_pro_event(name):
            continue
        events.append({"id": eid, "name": name, "status": status})
    return events


def fetch_pro_events(
    session: requests.Session,
    *,
    max_pages: int = 8,
    statuses: tuple[str, ...] = ("completed",),
    event_ids: list[str] | None = None,
) -> list[dict]:
    allowed_ids = {str(eid) for eid in event_ids} if event_ids else None
    events: list[dict] = []
    seen: set[str] = set()
    api_ok = True
    for page in range(1, max_pages + 1):
        resp = _get_with_retry(
            session,
            f"{VLR_API}/events",
            params={"page": page, "limit": 50},
        )
        if resp is None or resp.status_code >= 500:
            api_ok = False
            break
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError:
            api_ok = False
            break
        batch = resp.json().get("data") or []
        if not batch:
            break
        for event in batch:
            eid = str(event.get("id", ""))
            if eid in seen:
                continue
            seen.add(eid)
            status = event.get("status", "")
            if allowed_ids:
                if eid not in allowed_ids:
                    continue
                if not is_pro_event(event.get("name", "")):
                    continue
            elif status not in statuses:
                continue
            elif not is_pro_event(event.get("name", "")):
                continue
            events.append(
                {
                    "id": eid,
                    "name": normalize_tournament(event.get("name", "")),
                    "status": status,
                }
            )
        time.sleep(REQUEST_DELAY)

    if not api_ok and not events:
        print("VLR API events unavailable; falling back to vlr.gg events page...", flush=True)
        scraped = fetch_pro_events_from_vlrgg(session, statuses=statuses)
        if allowed_ids:
            scraped = [e for e in scraped if e["id"] in allowed_ids]
            # Preserve explicit event ids even if scrape missed them.
            scraped_ids = {e["id"] for e in scraped}
            for eid in allowed_ids:
                if eid not in scraped_ids:
                    title = _vlrgg_event_title(session, eid)
                    scraped.append(
                        {
                            "id": eid,
                            "name": title or f"VLR Event {eid}",
                            "status": "ongoing",
                        }
                    )
        return scraped
    return events


def fetch_completed_pro_events(session: requests.Session, max_pages: int = 8) -> list[dict]:
    return fetch_pro_events(session, max_pages=max_pages, statuses=("completed",))


def search_pro_events(
    session: requests.Session,
    *,
    keywords: tuple[str, ...],
    max_pages: int = 40,
    statuses: tuple[str, ...] = ("completed", "ongoing"),
) -> list[dict]:
    """Find pro events whose names contain any keyword (e.g. 'world cup')."""
    lowered = tuple(k.lower() for k in keywords)
    events: list[dict] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        resp = _get_with_retry(
            session,
            f"{VLR_API}/events",
            params={"page": page, "limit": 50},
        )
        if resp is None:
            break
        resp.raise_for_status()
        batch = resp.json().get("data") or []
        if not batch:
            break
        for event in batch:
            eid = str(event.get("id", ""))
            if eid in seen:
                continue
            name = str(event.get("name", ""))
            if not any(keyword in name.lower() for keyword in lowered):
                continue
            if not is_pro_event(name) and "world cup" not in name.lower() and "ewc" not in name.lower():
                continue
            status = event.get("status", "")
            if status not in statuses:
                continue
            seen.add(eid)
            events.append(
                {
                    "id": eid,
                    "name": normalize_tournament(name),
                    "status": status,
                }
            )
        time.sleep(REQUEST_DELAY)
    return events


def _event_team_ids(session: requests.Session, event_id: str) -> list[str]:
    ids: list[str] = []
    page = 1
    while True:
        resp = _get_with_retry(
            session,
            f"{VLR_API}/teams",
            params={"event": event_id, "page": page, "limit": 50},
        )
        if resp is None:
            break
        resp.raise_for_status()
        payload = resp.json()
        batch = payload.get("data") or []
        if not batch:
            break
        ids.extend(str(t["id"]) for t in batch if t.get("id"))
        pagination = payload.get("pagination") or {}
        if not pagination.get("hasNextPage"):
            break
        page += 1
        time.sleep(REQUEST_DELAY)
    return ids


def _stage_match_type_from_event_card(text: str) -> tuple[str, str]:
    """Map a vlr.gg match-item event label onto scores.csv Stage / Match Type."""
    text = " ".join((text or "").split())
    if text.endswith("Playoffs"):
        return "Playoffs", text[: -len("Playoffs")].strip() or "Match"
    if text.endswith("Play-Ins"):
        round_name = text[: -len("Play-Ins")].strip()
        match_type = f"Play-Ins: {round_name}" if round_name else "Play-Ins"
        return "Main Event", match_type
    if "Group Stage" in text:
        rest = text.replace("Group Stage", "").replace(":", "").strip()
        return "Group Stage", rest or "Match"
    return "Main Event", text or "Match"


def _collect_event_match_stubs_from_vlrgg(
    session: requests.Session,
    event_id: str,
    event_name: str,
) -> dict[str, dict]:
    """Fast path: scrape completed match cards from the vlr.gg event matches page."""
    target = normalize_tournament(event_name)
    url = f"https://www.vlr.gg/event/matches/{event_id}/?series_id=all"
    resp = _get_with_retry(session, url)
    if resp is None or resp.status_code != 200:
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    stubs: dict[str, dict] = {}
    for anchor in soup.select("a.match-item"):
        status_el = anchor.select_one(".ml-status")
        status_text = status_el.get_text(strip=True).lower() if status_el else ""
        if status_text and status_text != "completed":
            continue
        if "mod-upcoming" in (anchor.get("class") or []):
            continue

        href = anchor.get("href") or ""
        m = re.match(r"^/(\d+)/", href)
        if not m:
            continue
        mid = m.group(1)

        team_blocks = anchor.select(".match-item-vs-team")
        if len(team_blocks) < 2:
            continue
        teams: list[dict] = []
        for block in team_blocks[:2]:
            name_el = block.select_one(".text-of")
            score_el = block.select_one(".match-item-vs-team-score")
            name = clean_team_display_name(name_el.get_text(" ", strip=True) if name_el else "")
            score = _parse_series_points(score_el.get_text(strip=True) if score_el else None)
            if not name or score is None:
                teams = []
                break
            teams.append(
                {
                    "name": name,
                    "tag": name,
                    "points": str(score),
                    "won": "mod-winner" in (block.get("class") or []),
                }
            )
        if len(teams) != 2 or teams[0]["points"] == teams[1]["points"]:
            continue

        event_el = anchor.select_one(".match-item-event")
        stage, match_type = _stage_match_type_from_event_card(
            event_el.get_text(" ", strip=True) if event_el else ""
        )
        stubs[mid] = {
            "match_id": mid,
            "url": href if href.startswith("http") else f"https://www.vlr.gg{href}",
            "tournament": target,
            "teams": teams,
            "stage": stage,
            "match_type": match_type,
        }
    return stubs


def _collect_event_match_stubs(
    session: requests.Session,
    event_id: str,
    event_name: str,
) -> dict[str, dict]:
    """Return match_id -> stub for completed event matches."""
    stubs = _collect_event_match_stubs_from_vlrgg(session, event_id, event_name)
    if stubs:
        return stubs

    # Fallback: team result feeds (slower, used when event page is unavailable).
    target = normalize_tournament(event_name)
    team_ids = _event_team_ids(session, event_id)
    for team_id in team_ids:
        resp = _get_with_retry(
            session,
            f"{VLR_API}/teams/{team_id}",
            params={"event": event_id},
        )
        if resp is None or resp.status_code != 200:
            time.sleep(REQUEST_DELAY)
            continue
        results = (resp.json().get("data") or {}).get("results") or []
        for row in results:
            evt = normalize_tournament((row.get("event") or {}).get("name", ""))
            if evt != target:
                continue
            match = row.get("match") or {}
            mid = str(match.get("id", ""))
            if not mid:
                continue
            teams = row.get("teams") or []
            if len(teams) != 2:
                continue
            points = [_parse_series_points(t.get("points")) for t in teams]
            if any(p is None for p in points):
                continue
            if points[0] == points[1]:
                continue
            stubs[mid] = {
                "match_id": mid,
                "url": match.get("url") or VLR_MATCH_URL.format(match_id=mid, slug="match"),
                "tournament": target,
                "teams": teams,
            }
        time.sleep(REQUEST_DELAY)
    return stubs


def _parse_both(span) -> float | None:
    if not span:
        return None
    el = span.select_one(".mod-both") or span.select_one(".side.mod-both")
    if not el:
        return None
    text = el.get_text(strip=True).replace("%", "").replace("+", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _parse_series_points(value: Any) -> int | None:
    """Parse map-wins from API stubs; ignore countdowns like '1d 15h'."""
    text = str(value or "").strip()
    if not text or not re.fullmatch(r"-?\d+", text):
        return None
    return int(text)


def _parse_kda_stat(row, col: str) -> float | None:
    el = row.select_one(f'.ovw-kda-stat[data-col="{col}"]')
    return _parse_both(el)


def _parse_ovw_cell(row, col: str) -> float | None:
    cell = row.select_one(f'.ovw-cell[data-col="{col}"]')
    return _parse_both(cell)


def clean_team_display_name(name: str, canonical: set[str] | None = None) -> str:
    """Strip sponsor prefixes; prefer parenthetical canonical name from VLR."""
    if pd.isna(name):
        return name
    name = str(name).strip()
    paren = re.search(r"\(([^)]+)\)\s*$", name)
    if paren:
        name = paren.group(1).strip()
    return normalize_team(name, canonical)


def _parse_stage_match_type(soup: BeautifulSoup, tournament: str) -> tuple[str, str]:
    stage = "Main Event"
    match_type = "Match"
    header = soup.select_one(".match-header-event")
    if not header:
        return stage, match_type
    text = " ".join(header.get_text(" ", strip=True).split())
    if tournament and tournament in text:
        text = text.replace(tournament, "", 1).strip()
    for sep in ("Playoffs:", "Group Stage:", "Main Event:", "Swiss Stage:"):
        if sep in text:
            stage = sep.replace(":", "").strip()
            rest = text.split(sep, 1)[1].strip()
            if rest:
                match_type = rest
            return stage, match_type
    if text:
        match_type = text
    return stage, match_type


def _parse_match_header(soup: BeautifulSoup, fallback_tournament: str) -> tuple[str, str, str]:
    tournament = normalize_tournament(fallback_tournament)
    stage, match_type = _parse_stage_match_type(soup, tournament)
    return tournament, stage, match_type


def _parse_map_player_rows(
    table,
    tournament: str,
    stage: str,
    match_type: str,
    canonical: set[str],
    tag_map: dict[str, str],
) -> list[dict]:
    """Legacy HTML table parser (pre-2026 VLR markup)."""
    rows: list[dict] = []
    for tr in table.select("tbody tr"):
        player_cell = tr.select_one("td.mod-player")
        if not player_cell:
            continue
        ign_el = player_cell.select_one(".text-of")
        tag_el = player_cell.select_one(".ge-text-light")
        if not ign_el:
            continue
        player = ign_el.get_text(strip=True)
        tag = tag_el.get_text(strip=True) if tag_el else ""
        team = tag_map.get(tag) or tag_map.get(tag.upper()) or clean_team_display_name(tag, canonical)
        stat_cells = tr.select("td.mod-stat")
        if len(stat_cells) < 11:
            continue
        rating = _parse_both(stat_cells[0])
        acs = _parse_both(stat_cells[1])
        kills = _parse_both(stat_cells[2])
        deaths = _parse_both(stat_cells[3])
        assists = _parse_both(stat_cells[4])
        adr = _parse_both(stat_cells[7])
        fk = _parse_both(stat_cells[9])
        fd = _parse_both(stat_cells[10])
        if kills is None or deaths is None:
            continue
        kd = kills / deaths if deaths else kills
        agents = ", ".join(
            img.get("title", "") for img in tr.select("td.mod-agents img[title]")
        )
        rows.append(
            {
                "Tournament": tournament,
                "Stage": stage,
                "Match Type": match_type,
                "Player": player,
                "Teams": team,
                "Agents": agents or "unknown",
                "Rounds Played": None,
                "Rating": rating,
                "Average Combat Score": acs,
                "Kills:Deaths": kd,
                "Kill, Assist, Trade, Survive %": None,
                "Average Damage Per Round": adr,
                "Kills Per Round": None,
                "Assists Per Round": None,
                "First Kills Per Round": fk,
                "First Deaths Per Round": fd,
                "Headshot %": _parse_both(stat_cells[8]) if len(stat_cells) > 8 else None,
                "Clutch Success %": None,
                "Clutches (won/played)": None,
                "Maximum Kills in a Single Map": kills,
                "Kills": kills,
                "Deaths": deaths,
                "Assists": assists,
                "First Kills": fk,
                "First Deaths": fd,
            }
        )
    return rows


def _parse_ovw_player_rows(
    soup: BeautifulSoup,
    tournament: str,
    stage: str,
    match_type: str,
    canonical: set[str],
    tag_map: dict[str, str],
) -> list[dict]:
    """Parse current VLR overview scoreboard (div.ovw-table / All Maps panel)."""
    game = None
    for candidate in soup.select("div.vm-stats-game"):
        if candidate.get("data-game-id") == "all":
            game = candidate
            break
    if game is None:
        games = [g for g in soup.select("div.vm-stats-game") if g.select(".ovw-table")]
        game = games[0] if games else None
    if game is None:
        return []

    rows: list[dict] = []
    for table in game.select(".ovw-table"):
        for row in table.select(".ovw-row"):
            classes = row.get("class") or []
            if "mod-head" in classes:
                continue
            player_cell = row.select_one(".mod-player, .ovw-player")
            if not player_cell:
                continue
            ign_el = player_cell.select_one(".ovw-player-name, .text-of")
            tag_el = player_cell.select_one(".ovw-player-tag, .ge-text-light")
            if not ign_el:
                continue
            player = ign_el.get_text(strip=True)
            tag = tag_el.get_text(strip=True) if tag_el else ""
            team = (
                tag_map.get(tag)
                or tag_map.get(tag.upper())
                or clean_team_display_name(tag, canonical)
            )
            kills = _parse_kda_stat(row, "kills")
            deaths = _parse_kda_stat(row, "deaths")
            assists = _parse_kda_stat(row, "assists")
            if kills is None or deaths is None:
                continue
            rating = _parse_ovw_cell(row, "rating2")
            acs = _parse_ovw_cell(row, "acs")
            adr = _parse_ovw_cell(row, "adr")
            fk = _parse_ovw_cell(row, "fb")
            fd = _parse_ovw_cell(row, "fd")
            kast = _parse_ovw_cell(row, "kast")
            hsp = _parse_ovw_cell(row, "hsp")
            kd = kills / deaths if deaths else kills
            agents = ", ".join(
                img.get("title") or img.get("alt") or ""
                for img in player_cell.select("img")
                if img.get("title") or img.get("alt")
            )
            rows.append(
                {
                    "Tournament": tournament,
                    "Stage": stage,
                    "Match Type": match_type,
                    "Player": player,
                    "Teams": team,
                    "Agents": agents or "unknown",
                    "Rounds Played": None,
                    "Rating": rating,
                    "Average Combat Score": acs,
                    "Kills:Deaths": kd,
                    "Kill, Assist, Trade, Survive %": kast,
                    "Average Damage Per Round": adr,
                    "Kills Per Round": None,
                    "Assists Per Round": None,
                    "First Kills Per Round": fk,
                    "First Deaths Per Round": fd,
                    "Headshot %": hsp,
                    "Clutch Success %": None,
                    "Clutches (won/played)": None,
                    "Maximum Kills in a Single Map": kills,
                    "Kills": kills,
                    "Deaths": deaths,
                    "Assists": assists,
                    "First Kills": fk,
                    "First Deaths": fd,
                }
            )
    return rows


def _stub_team_scores(
    teams: list[dict],
    team_a: str,
    team_b: str,
    canonical: set[str],
) -> tuple[int, int, str | None]:
    """Align stub scores to team_a/team_b order (stub order may differ from page header)."""
    by_name: dict[str, tuple[int, bool | None]] = {}
    for entry in teams:
        name = clean_team_display_name(entry.get("name", entry.get("tag", "")), canonical)
        score = _parse_series_points(entry.get("points"))
        if score is None:
            return 0, 0, None
        by_name[name.lower()] = (score, entry.get("won"))

    def lookup(team: str) -> tuple[int, bool | None]:
        key = team.lower()
        if key in by_name:
            return by_name[key]
        for known, values in by_name.items():
            if known in key or key in known:
                return values
        return 0, None

    score_a, won_a = lookup(team_a)
    score_b, won_b = lookup(team_b)
    if won_a:
        winner = team_a
    elif won_b:
        winner = team_b
    elif score_a != score_b:
        winner = team_a if score_a > score_b else team_b
    else:
        winner = None
    return score_a, score_b, winner


def _parse_series_score_from_page(
    soup: BeautifulSoup,
    team_a: str,
    team_b: str,
) -> tuple[int, int, str | None]:
    """Fallback series score from match header when API stub points are missing."""
    score_root = soup.select_one(".match-header-vs-score")
    if not score_root:
        return 0, 0, None
    text = " ".join(score_root.get_text(" ", strip=True).split())
    m = re.search(r"(\d+)\s*:\s*(\d+)", text)
    if not m:
        return 0, 0, None
    score_a, score_b = int(m.group(1)), int(m.group(2))
    if score_a == score_b:
        return score_a, score_b, None
    winner = team_a if score_a > score_b else team_b
    # Header order follows team_a/team_b from _parse_match_teams for completed matches.
    return score_a, score_b, winner


def _parse_match_date(soup: BeautifulSoup) -> str | None:
    date_el = soup.select_one(".match-header-date")
    if not date_el:
        return None
    text = " ".join(date_el.get_text(" ", strip=True).split())
    if not text:
        return None
    return text


def _parse_map_score(text: str) -> int | None:
    cleaned = re.sub(r"[^\d]", "", text or "")
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _parse_map_results(
    soup: BeautifulSoup,
    *,
    tournament: str,
    stage: str,
    match_type: str,
    team_a: str,
    team_b: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for game in soup.select("div.vm-stats-game"):
        if game.get("data-game-id") == "all":
            continue
        map_el = game.select_one("div.map")
        if not map_el:
            continue
        map_name = normalize_map_name(map_el.get_text(" ", strip=True))
        if not map_name:
            continue
        team_blocks = game.select("div.team")
        if len(team_blocks) < 2:
            continue

        def _team_info(block) -> tuple[str, int | None]:
            name_el = block.select_one(".team-name")
            score_el = block.select_one(".score")
            name = clean_team_display_name(
                name_el.get_text(" ", strip=True) if name_el else block.get_text(" ", strip=True)
            )
            score = None
            if score_el:
                try:
                    score = int(score_el.get_text(strip=True))
                except ValueError:
                    score = None
            if score is None:
                score = _parse_map_score(block.get_text(" ", strip=True))
            return name, score

        left_name, left_score = _team_info(team_blocks[0])
        right_name, right_score = _team_info(team_blocks[1])
        if left_score is None or right_score is None or left_score == right_score:
            continue

        if left_name.lower() in team_a.lower() or team_a.lower() in left_name.lower():
            score_a, score_b = left_score, right_score
        elif left_name.lower() in team_b.lower() or team_b.lower() in left_name.lower():
            score_a, score_b = right_score, left_score
        else:
            score_a, score_b = left_score, right_score

        rows.append(
            {
                "Tournament": tournament,
                "Stage": stage,
                "Match Type": match_type,
                "Map": map_name,
                "Team A": team_a,
                "Team B": team_b,
                "Team A Score": score_a,
                "Team B Score": score_b,
            }
        )
    return rows


def load_vlr_maps() -> pd.DataFrame:
    if not VLR_MAPS_PATH.exists():
        return pd.DataFrame(columns=MAPS_SCORES_COLUMNS)
    return pd.read_csv(VLR_MAPS_PATH)


def save_vlr_maps(df: pd.DataFrame) -> None:
    VLR_MAPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(VLR_MAPS_PATH, index=False)


def append_vlr_maps(new_rows: list[dict[str, Any]]) -> None:
    if not new_rows:
        return
    existing = load_vlr_maps()
    incoming = pd.DataFrame(new_rows, columns=MAPS_SCORES_COLUMNS)
    merged = pd.concat([existing, incoming], ignore_index=True)
    merged = merged.drop_duplicates(
        subset=["Tournament", "Stage", "Match Type", "Map", "Team A", "Team B", "Team A Score", "Team B Score"],
        keep="last",
    )
    save_vlr_maps(merged)


def _parse_match_teams(soup: BeautifulSoup, stub: dict, canonical: set[str]) -> tuple[str, str, dict[str, str]]:
    """Return team_a, team_b, and tag -> canonical name map."""
    teams = stub["teams"]
    team_a = clean_team_display_name(teams[0].get("name", teams[0].get("tag", "")), canonical)
    team_b = clean_team_display_name(teams[1].get("name", teams[1].get("tag", "")), canonical)
    tag_map: dict[str, str] = {}
    for entry, full in zip(teams, (team_a, team_b)):
        for key in (entry.get("tag"), entry.get("name")):
            if key:
                tag_map[str(key).strip().upper()] = full
                tag_map[str(key).strip()] = full

    vs = soup.select_one(".match-header-vs")
    if vs:
        text = vs.get_text(" ", strip=True)
        m = re.match(
            r"(.+?)\s+final\s+(\d+)\s*:\s*(\d+)\s+vs\.\s+Bo\d+\s+(.+)$",
            text,
            re.I,
        )
        if m:
            team_a = clean_team_display_name(m.group(1).strip(), canonical)
            team_b = clean_team_display_name(m.group(4).strip(), canonical)
            tag_map[team_a.upper()] = team_a
            tag_map[team_b.upper()] = team_b
    return team_a, team_b, tag_map


def scrape_match(
    stub: dict,
    session: requests.Session,
    canonical: set[str],
) -> VlrMatch | None:
    url = stub["url"]
    if not url.startswith("http"):
        url = f"https://www.vlr.gg{url}"

    resp = _get_with_retry(session, url)
    if resp is None or resp.status_code != 200:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")

    tournament, stage, match_type = _parse_match_header(soup, stub["tournament"])
    match_date = _parse_match_date(soup)

    teams = stub["teams"]
    team_a, team_b, tag_map = _parse_match_teams(soup, stub, canonical)
    score_a, score_b, winner = _stub_team_scores(teams, team_a, team_b, canonical)
    if winner is None:
        score_a, score_b, winner = _parse_series_score_from_page(soup, team_a, team_b)
    if winner is None:
        return None

    player_rows = _parse_ovw_player_rows(
        soup, tournament, stage, match_type, canonical, tag_map
    )
    if not player_rows:
        for table in soup.select("table.wf-table-inset.mod-overview"):
            player_rows.extend(
                _parse_map_player_rows(
                    table, tournament, stage, match_type, canonical, tag_map
                )
            )

    map_rows = _parse_map_results(
        soup,
        tournament=tournament,
        stage=stage,
        match_type=match_type,
        team_a=team_a,
        team_b=team_b,
    )

    return VlrMatch(
        match_id=stub["match_id"],
        url=url,
        tournament=tournament,
        team_a=team_a,
        team_b=team_b,
        score_a=score_a,
        score_b=score_b,
        winner=winner,
        stage=stage,
        match_type=match_type,
        match_date=match_date,
        player_rows=player_rows,
        map_rows=map_rows,
    )


def repair_vlr_scores(scores: pd.DataFrame) -> pd.DataFrame:
    """Fix rows ingested with broken tournament/stage/team fields."""
    out = scores.copy()
    region_re = re.compile(
        r"^(Americas|EMEA|Pacific|China)\s+Stage\s+(\d+)\s+(Group Stage|Playoffs|Main Event|Swiss Stage)$"
    )
    for idx, row in out.iterrows():
        if row["Tournament"] != "VCT 2026":
            continue
        m = region_re.match(str(row["Stage"]))
        if m:
            region, num, stage = m.groups()
            out.at[idx, "Tournament"] = f"VCT 2026: {region} Stage {num}"
            out.at[idx, "Stage"] = stage
        for col in ("Team A", "Team B"):
            cleaned = clean_team_display_name(row[col])
            out.at[idx, col] = cleaned
        a, b = out.at[idx, "Team A"], out.at[idx, "Team B"]
        out.at[idx, "Match Name"] = f"{a} vs {b}"
        winner = str(row["Match Result"]).replace(" won", "")
        winner = clean_team_display_name(winner)
        if winner in (a, b):
            out.at[idx, "Match Result"] = f"{winner} won"
    return out


def repair_vlr_player_stats(players: pd.DataFrame) -> pd.DataFrame:
    """Normalize VLR tournament/stage keys so they join to scores.csv rows."""
    out = players.copy()
    if out.empty:
        return out

    # "VCT 2026" + "China Stage 2 Group Stage" -> "VCT 2026: China Stage 2" / "Group Stage"
    region_stage_re = re.compile(
        r"^(Americas|EMEA|Pacific|China)\s+(Kickoff|Stage\s+(\d+))\s+"
        r"(Group Stage|Playoffs|Main Event|Swiss Stage|Regular Season)$",
        re.I,
    )
    # Bare "VCT 2025" / "VCT 2026" with region stage already partially normalized.
    year_only_re = re.compile(r"^VCT\s+(20\d{2})$", re.I)
    # Kickoff without "Stage": "Pacific Kickoff Group Stage"
    kickoff_re = re.compile(
        r"^(Americas|EMEA|Pacific|China)\s+Kickoff\s+"
        r"(Group Stage|Playoffs|Main Event|Swiss Stage|Regular Season)$",
        re.I,
    )

    for idx, row in out.iterrows():
        tournament = str(row.get("Tournament", "")).strip()
        stage = str(row.get("Stage", "")).strip()
        year_m = year_only_re.match(tournament)

        if year_m:
            year = year_m.group(1)
            kick = kickoff_re.match(stage)
            if kick:
                region, stage_name = kick.groups()
                out.at[idx, "Tournament"] = f"VCT {year}: {region} Kickoff"
                out.at[idx, "Stage"] = stage_name
            else:
                m = region_stage_re.match(stage)
                if m:
                    region, phase, stage_num, stage_name = m.group(1), m.group(2), m.group(3), m.group(4)
                    if stage_num:
                        out.at[idx, "Tournament"] = f"VCT {year}: {region} Stage {stage_num}"
                    else:
                        out.at[idx, "Tournament"] = f"VCT {year}: {region} {phase}"
                    out.at[idx, "Stage"] = stage_name

        # Also repair already-year-tagged rows whose Stage still embeds region+phase.
        tagged = re.match(r"^VCT\s+(20\d{2}):", tournament, re.I)
        if tagged:
            m = region_stage_re.match(stage)
            if m:
                region, phase, stage_num, stage_name = m.group(1), m.group(2), m.group(3), m.group(4)
                year = tagged.group(1)
                if stage_num:
                    out.at[idx, "Tournament"] = f"VCT {year}: {region} Stage {stage_num}"
                else:
                    out.at[idx, "Tournament"] = f"VCT {year}: {region} {phase}"
                out.at[idx, "Stage"] = stage_name
            kick = kickoff_re.match(stage)
            if kick:
                region, stage_name = kick.groups()
                out.at[idx, "Tournament"] = f"VCT {tagged.group(1)}: {region} Kickoff"
                out.at[idx, "Stage"] = stage_name

        if "Teams" in out.columns:
            out.at[idx, "Teams"] = clean_team_display_name(row.get("Teams"))
    return out


def match_to_score_row(match: VlrMatch) -> dict:
    return {
        "Tournament": match.tournament,
        "Stage": match.stage,
        "Match Type": match.match_type,
        "Match Name": f"{match.team_a} vs {match.team_b}",
        "Team A": match.team_a,
        "Team B": match.team_b,
        "Team A Score": match.score_a,
        "Team B Score": match.score_b,
        "Match Result": f"{match.winner} won",
        "Match Date": match.match_date,
    }


SCORE_DEDUPE_COLUMNS = ["Tournament", "Stage", "Match Type", "Team A", "Team B"]


def score_dedupe_key(row: dict) -> tuple:
    """Identity for a series. Scores are omitted so rematches with the same
    map-wins (e.g. two 2-0s in one Kickoff) are not collapsed."""
    a, b = sorted([str(row["Team A"]), str(row["Team B"])])
    return (
        str(row.get("Tournament", "")),
        str(row.get("Stage", "")),
        str(row.get("Match Type", "")),
        a,
        b,
    )


def existing_score_keys(scores: pd.DataFrame) -> set[tuple]:
    keys: set[tuple] = set()
    for _, row in scores.iterrows():
        keys.add(score_dedupe_key(row.to_dict()))
    return keys


def events_missing_from_scores(
    scores: pd.DataFrame,
    events: list[dict],
) -> list[dict]:
    existing = {normalize_tournament(t) for t in scores["Tournament"].astype(str).unique()}
    return [e for e in events if e["name"] not in existing]


def fetch_new_vlr_data(
    scores: pd.DataFrame,
    *,
    event_ids: list[str] | None = None,
    verbose: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, set[str]]:
    """
    Fetch matches from VLR not already present in scores.csv.
    Returns (new_score_rows, new_player_stats_rows, ingested_match_ids).
    """
    session = _session()
    canonical = set(scores["Team A"]).union(scores["Team B"])
    canonical = {normalize_team(t, None) for t in canonical}

    ingested = load_ingested_ids()
    existing_keys = existing_score_keys(scores)

    if event_ids:
        events = fetch_pro_events(
            session,
            statuses=("completed", "ongoing"),
            event_ids=[str(eid) for eid in event_ids],
        )
    else:
        completed = fetch_completed_pro_events(session)
        ongoing = fetch_pro_events(session, statuses=("ongoing",))
        by_id = {e["id"]: e for e in events_missing_from_scores(scores, completed)}
        for event in ongoing:
            by_id[event["id"]] = event
        events = list(by_id.values())

    if verbose:
        print(f"VLR: {len(events)} pro event(s) to scan for new matches", flush=True)

    stubs: dict[str, dict] = {}
    for event in events:
        if verbose:
            print(f"  Scanning {event['name']} (id {event['id']})...", flush=True)
        found = _collect_event_match_stubs(session, event["id"], event["name"])
        recovered = 0
        for mid, stub in found.items():
            if mid not in ingested:
                stubs[mid] = stub
                continue
            # Same-score rematches can be marked ingested after colliding with an
            # earlier series, then never land in scores.csv. Retry those IDs.
            teams = stub.get("teams") or []
            if len(teams) != 2 or not stub.get("stage") or not stub.get("match_type"):
                continue
            team_a = normalize_team(teams[0].get("name", ""), canonical)
            team_b = normalize_team(teams[1].get("name", ""), canonical)
            key = (
                stub.get("tournament") or event["name"],
                stub["stage"],
                stub["match_type"],
                *sorted([team_a, team_b]),
            )
            if key not in existing_keys:
                stubs[mid] = stub
                recovered += 1
        if verbose:
            extra = f", {recovered} ingested-id retries" if recovered else ""
            print(
                f"    {len(found)} matches, {len(stubs)} pending after dedupe{extra}",
                flush=True,
            )

    new_scores: list[dict] = []
    new_players: list[dict] = []
    new_maps: list[dict] = []
    new_ids: set[str] = set()

    for i, (mid, stub) in enumerate(sorted(stubs.items()), start=1):
        if verbose:
            print(f"  Scraping match {i}/{len(stubs)} ({mid})...", flush=True)
        try:
            parsed = scrape_match(stub, session, canonical)
        except Exception as exc:  # noqa: BLE001 - keep ingesting remaining matches
            if verbose:
                print(f"    Skipped {mid}: scrape error ({exc})", flush=True)
            time.sleep(REQUEST_DELAY)
            continue
        time.sleep(REQUEST_DELAY)
        if not parsed:
            continue
        row = match_to_score_row(parsed)
        key = score_dedupe_key(row)
        if key in existing_keys:
            ingested.add(mid)
            continue
        if not parsed.player_rows:
            if verbose:
                print(f"    Skipped {mid}: no player stats", flush=True)
            continue
        new_scores.append(row)
        new_players.extend(parsed.player_rows)
        new_maps.extend(parsed.map_rows)
        new_ids.add(mid)
        existing_keys.add(key)
        ingested.add(mid)
        canonical.update({row["Team A"], row["Team B"]})
        if verbose:
            _safe_print(
                f"    Added {row['Team A']} {row['Team A Score']}-{row['Team B Score']} {row['Team B']}"
            )

    save_ingested_ids(ingested)
    append_vlr_maps(new_maps)

    scores_df = pd.DataFrame(new_scores, columns=SCORES_COLUMNS) if new_scores else pd.DataFrame(columns=SCORES_COLUMNS)
    players_df = (
        pd.DataFrame(new_players, columns=PLAYER_STATS_COLUMNS)
        if new_players
        else pd.DataFrame(columns=PLAYER_STATS_COLUMNS)
    )
    return scores_df, players_df, new_ids
