"""Upcoming (and live) VCT 2026 matches from VLR for the homepage."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup

from vlr_ingest import VLR_API, _get_with_retry, clean_team_display_name

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 90.0
_TIMEOUT = 15
_TARGET_YEAR = 2026


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
        }
    )
    return s


def _is_vct_2026(tournament: str | None) -> bool:
    t = (tournament or "").upper()
    if "VCT" not in t and "CHAMPIONS" not in t and "MASTERS" not in t:
        return False
    return str(_TARGET_YEAR) in t or "2026" in t


def _parse_utc(match: dict) -> datetime | None:
    raw = match.get("utc") or match.get("utcDate")
    if raw:
        try:
            if isinstance(raw, (int, float)):
                return datetime.fromtimestamp(raw, tz=timezone.utc)
            text = str(raw).replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    ts = match.get("timestamp")
    if ts:
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (TypeError, ValueError):
            return None
    return None


def _team_blob(raw: dict) -> dict[str, Any]:
    name = clean_team_display_name(str(raw.get("name") or ""))
    score = raw.get("score")
    score_s = "" if score is None else str(score).strip()
    return {
        "name": name,
        "score": score_s if score_s not in ("", "None", "–", "-") else None,
        "won": bool(raw["won"]) if raw.get("won") is not None else None,
        "logo": raw.get("logo"),
        "id": str(raw.get("id") or "") or None,
    }


def _normalize(match: dict) -> dict[str, Any] | None:
    teams = match.get("teams") or []
    if len(teams) < 2:
        return None
    t1, t2 = _team_blob(teams[0]), _team_blob(teams[1])
    if not t1["name"] or not t2["name"]:
        return None
    if t1["name"].upper() == "TBD" or t2["name"].upper() == "TBD":
        return None
    tournament = str(match.get("tournament") or "")
    if not _is_vct_2026(tournament):
        return None
    status = str(match.get("status") or "").strip() or "Upcoming"
    status_u = status.upper()
    if status_u == "LIVE":
        bucket = "live"
    elif status_u in ("COMPLETED", "COMPLETE", "FINISHED"):
        return None
    else:
        bucket = "upcoming"
    mid = str(match.get("id") or "")
    utc = _parse_utc(match)
    if utc and utc.year != _TARGET_YEAR and "2026" not in tournament:
        return None
    return {
        "id": mid,
        "team1": t1,
        "team2": t2,
        "status": status,
        "bucket": bucket,
        "event": match.get("event"),
        "tournament": tournament,
        "utc": utc.isoformat() if utc else match.get("utc_local"),
        "url": f"https://www.vlr.gg/{mid}" if mid else None,
        "source": match.get("source") or "matches",
    }


def _fetch_api_list(session: requests.Session, path: str, params: dict | None = None) -> list[dict]:
    try:
        resp = _get_with_retry(
            session,
            f"{VLR_API}/{path}",
            params=params or {},
            timeout=_TIMEOUT,
            retries=2,
        )
        if resp is None or resp.status_code != 200:
            return []
        payload = resp.json()
        data = payload.get("data") if isinstance(payload, dict) else payload
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _parse_vlr_date_label(text: str) -> datetime | None:
    # e.g. "Sat, August 22, 2026 Today"
    cleaned = re.sub(r"\b(Today|Tomorrow)\b", "", text, flags=re.I).strip(" ,")
    for fmt in ("%a, %B %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _parse_vlr_clock(text: str) -> tuple[int, int] | None:
    m = re.match(r"^(\d{1,2}):(\d{2})\s*(AM|PM)$", (text or "").strip(), re.I)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2))
    ampm = m.group(3).upper()
    if ampm == "AM":
        if hour == 12:
            hour = 0
    elif hour != 12:
        hour += 12
    return hour, minute


def _extract_tournament(event_el) -> tuple[str | None, str | None]:
    if event_el is None:
        return None, None
    series_el = event_el.select_one(".match-item-event-series")
    series = " ".join(series_el.get_text(" ", strip=True).split()) if series_el else None
    full = " ".join(event_el.get_text(" ", strip=True).split())
    tournament = full
    if series and full.startswith(series):
        tournament = full[len(series) :].strip(" ·|-")
    return tournament or None, series


def _fetch_vlrgg_upcoming(session: requests.Session) -> list[dict[str, Any]]:
    """Scrape live/upcoming cards from vlr.gg/matches when the JSON API is down."""
    resp = _get_with_retry(session, "https://www.vlr.gg/matches", timeout=_TIMEOUT, retries=2)
    if resp is None or resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    rows: list[dict[str, Any]] = []
    current_date: datetime | None = None

    for node in soup.select(".wf-label.mod-large, a.match-item"):
        classes = node.get("class") or []
        if "wf-label" in classes:
            current_date = _parse_vlr_date_label(node.get_text(" ", strip=True))
            continue

        status_el = node.select_one(".ml-status")
        status = status_el.get_text(strip=True) if status_el else "Upcoming"
        status_u = status.upper()
        if status_u in ("COMPLETED", "COMPLETE", "FINISHED"):
            continue

        href = node.get("href") or ""
        mid_m = re.match(r"^/(\d+)/", href)
        mid = mid_m.group(1) if mid_m else ""

        team_blocks = node.select(".match-item-vs-team")
        if len(team_blocks) < 2:
            continue
        teams: list[dict[str, Any]] = []
        for block in team_blocks[:2]:
            name_el = block.select_one(".text-of")
            score_el = block.select_one(".match-item-vs-team-score")
            name = clean_team_display_name(name_el.get_text(" ", strip=True) if name_el else "")
            score_txt = score_el.get_text(strip=True) if score_el else ""
            score = score_txt if score_txt.isdigit() else None
            teams.append(
                {
                    "name": name,
                    "score": score,
                    "won": "mod-winner" in (block.get("class") or []),
                }
            )
        if len(teams) != 2:
            continue

        tournament, series = _extract_tournament(node.select_one(".match-item-event"))
        if not _is_vct_2026(tournament or ""):
            continue

        time_el = node.select_one(".match-item-time")
        clock = _parse_vlr_clock(time_el.get_text(strip=True) if time_el else "")
        utc_local = None
        if current_date and clock:
            utc_local = (
                f"{current_date.year:04d}-{current_date.month:02d}-{current_date.day:02d}"
                f"T{clock[0]:02d}:{clock[1]:02d}:00"
            )

        rows.append(
            {
                "id": mid,
                "teams": teams,
                "status": status,
                "tournament": tournament,
                "event": series,
                "utc_local": utc_local,
                "source": "vlrgg",
            }
        )
    return rows


def fetch_upcoming_matches() -> dict[str, Any]:
    """Live + upcoming VCT 2026 matches (no date='today' filter, no results)."""
    cache_key = "upcoming_vct_2026"
    hit = _CACHE.get(cache_key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]

    session = _session()
    raw = _fetch_api_list(session, "matches")
    if not raw:
        raw = _fetch_api_list(session, "matches", {"status": "upcoming"})
    source = "api"

    by_id: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        if "source" not in item:
            item = {**item, "source": source}
        row = _normalize(item)
        if not row:
            continue
        key = row["id"] or f"{row['team1']['name']}::{row['team2']['name']}::{row.get('utc')}"
        by_id[key] = row

    # orlandomm often 503s or returns non-VCT noise; scrape vlr.gg when empty.
    if not by_id:
        raw = _fetch_vlrgg_upcoming(session)
        source = "vlrgg"
        for item in raw:
            if not isinstance(item, dict):
                continue
            row = _normalize(item)
            if not row:
                continue
            key = row["id"] or f"{row['team1']['name']}::{row['team2']['name']}::{row.get('utc')}"
            by_id[key] = row

    matches = list(by_id.values())

    def sort_key(m: dict) -> tuple:
        order = 0 if m["bucket"] == "live" else 1
        return (order, m.get("utc") or "9999", m.get("tournament") or "")

    matches.sort(key=sort_key)

    payload = {
        "year": _TARGET_YEAR,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(matches),
        "matches": matches,
        "source": source,
    }
    _CACHE[cache_key] = (time.time(), payload)
    return payload


# Back-compat alias for older imports / routes
def fetch_today_matches(**_kwargs) -> dict[str, Any]:
    return fetch_upcoming_matches()
