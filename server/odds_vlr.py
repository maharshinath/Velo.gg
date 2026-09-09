"""Fetch bookmaker decimal odds from VLR.gg match Betting modules."""

from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from vlr_ingest import (
    REQUEST_DELAY,
    TEAM_ALIASES,
    VLR_API,
    VLR_MATCH_URL,
    _get_with_retry,
    clean_team_display_name,
    normalize_team,
)

_ODDS_CACHE: dict[str, tuple[float, dict | None]] = {}
_CACHE_TTL_SEC = 180.0
# Keep odds fetch snappy so /api/predict stays usable when VLR is slow.
_ODDS_TIMEOUT = 12
_ODDS_RETRIES = 1
_ODDS_API_TIMEOUT = 4
_VLR_TEAM_IDS_PATH = Path(__file__).resolve().parent / "data" / "vlr_team_ids.json"
_VLR_TEAM_IDS: dict[str, int] | None = None
_MISS = object()

_BOOKIE_LABELS = {
    "ggbet": "GG.BET",
    "thunderpick": "Thunderpick",
    "rainbet": "Rainbet",
    "shuffle": "Shuffle",
    "winz": "Winz.io",
    "betway": "Betway",
    "rivalry": "Rivalry",
}

_ODDS_RE = re.compile(
    r"\$100\s+on\s+(.+?)\s+returned\s+\$(\d+(?:\.\d+)?)\s+at\s+pre-match\s+odds|"
    r"(\d+\.\d+)\s+([A-Za-z0-9 .'\-]+?)\s+odds\s+pre-match",
    re.I,
)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.vlr.gg/",
        }
    )
    return s


def _cache_get(key: str) -> dict | None | object:
    hit = _ODDS_CACHE.get(key)
    if not hit:
        return _MISS
    ts, payload = hit
    if time.time() - ts > _CACHE_TTL_SEC:
        return _MISS
    return payload


def _cache_set(key: str, payload: dict | None) -> None:
    _ODDS_CACHE[key] = (time.time(), payload)


def _fold(text: str) -> str:
    """Lowercase + strip accents for fuzzy team matching (LEVIATÁN ↔ Leviatan)."""
    nfkd = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).lower().strip()


def _team_key(name: str) -> str:
    return _fold(clean_team_display_name(normalize_team(str(name))))


def _vlr_team_id(name: str) -> int | None:
    global _VLR_TEAM_IDS
    if _VLR_TEAM_IDS is None:
        try:
            raw = json.loads(_VLR_TEAM_IDS_PATH.read_text(encoding="utf-8"))
            _VLR_TEAM_IDS = {str(k): int(v) for k, v in raw.items()}
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            _VLR_TEAM_IDS = {}
    canonical = TEAM_ALIASES.get(str(name).strip(), str(name).strip())
    tid = _VLR_TEAM_IDS.get(str(name).strip()) or _VLR_TEAM_IDS.get(canonical)
    return int(tid) if tid else None


def _names_match(a: str, b: str) -> bool:
    ka, kb = _team_key(a), _team_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    if ka in kb or kb in ka:
        return True
    aa = TEAM_ALIASES.get(a, a)
    bb = TEAM_ALIASES.get(b, b)
    return _team_key(aa) == _team_key(bb)


def _bookie_label(img) -> str:
    if img is None:
        return "Book"
    for cls in img.get("class") or []:
        if str(cls).startswith("mod-"):
            key = str(cls)[4:].lower()
            return _BOOKIE_LABELS.get(key, key.replace("-", " ").title())
    src = str(img.get("src") or "")
    m = re.search(r"/([^/]+)\.(?:png|svg|webp|jpg)$", src, re.I)
    if m:
        key = m.group(1).lower().replace("_logo", "").replace("-logo", "")
        return _BOOKIE_LABELS.get(key, key.replace("-", " ").title())
    return "Book"


def _parse_decimal(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d+\.\d{1,3})", text.replace(",", "."))
    if not m:
        return None
    odds = float(m.group(1))
    if odds < 1.01 or odds > 50:
        return None
    return odds


def parse_betting_books(html: str) -> list[dict[str, Any]]:
    """
    Parse the VLR match Betting module (multi-bookie cards).

    Each card looks like:
      a.match-bet-item
        .match-bet-item-half.mod-1  → left team + odds
        .match-bet-item-half.mod-2  → right team + odds + Live/Pre-match note
    """
    soup = BeautifulSoup(html, "html.parser")
    books: list[dict[str, Any]] = []

    # Prefer items under the Betting label; fall back to all match-bet-item cards.
    items = []
    for label in soup.select("div.wf-label"):
        if _fold(label.get_text()) == "betting":
            parent = label.parent
            if parent:
                items = parent.select("a.match-bet-item, .match-bet-item")
            break
    if not items:
        items = soup.select("a.match-bet-item, .wf-card.match-bet-item")

    for item in items:
        left = item.select_one(".match-bet-item-half.mod-1")
        right = item.select_one(".match-bet-item-half.mod-2")
        if not left or not right:
            continue
        name1_el = left.select_one(".match-bet-item-team-name")
        name2_el = right.select_one(".match-bet-item-team-name")
        odds1 = _parse_decimal(
            (left.select_one(".match-bet-item-odds") or left).get_text(" ", strip=True)
        )
        odds2 = _parse_decimal(
            (right.select_one(".match-bet-item-odds") or right).get_text(" ", strip=True)
        )
        if odds1 is None or odds2 is None or not name1_el or not name2_el:
            continue
        note_el = item.select_one(".match-bet-item-note")
        note = note_el.get_text(" ", strip=True) if note_el else ""
        books.append(
            {
                "bookie": _bookie_label(item.select_one("img")),
                "team1_name": name1_el.get_text(" ", strip=True),
                "team2_name": name2_el.get_text(" ", strip=True),
                "team1_odds": odds1,
                "team2_odds": odds2,
                "status": note or None,
            }
        )
    return books


def parse_post_match_odds(html: str) -> list[tuple[str, float]]:
    """Completed matches only list the winning side's pre-match price."""
    soup = BeautifulSoup(html, "html.parser")
    found: list[tuple[str, float]] = []
    for item in soup.select("a.match-bet-item.mod-post-odds, .match-bet-item.mod-post-odds"):
        names = [
            n.get_text(" ", strip=True)
            for n in item.select(".match-bet-item-teamzzz, .match-bet-item-team-name")
        ]
        full = next((n for n in names if n and len(n) > 3), names[0] if names else "")
        text = item.get_text(" ", strip=True)
        m = re.search(r"(\d+\.\d{2})\s+\S+\s+odds\s+pre-match", text, re.I)
        if full and m:
            found.append((full, float(m.group(1))))
    return _dedupe_odds(found)


def parse_odds_from_html(html: str) -> list[tuple[str, float]]:
    """Backward-compatible: return averaged (team, odds) pairs from Betting module."""
    books = parse_betting_books(html)
    if books:
        return _average_team_odds(books)
    post = parse_post_match_odds(html)
    if post:
        return post

    soup = BeautifulSoup(html, "html.parser")
    found: list[tuple[str, float]] = []
    text = soup.get_text("\n", strip=True)
    for m in _ODDS_RE.finditer(text):
        if m.group(1) and m.group(2):
            found.append((m.group(1).strip(), round(float(m.group(2)) / 100.0, 3)))
        elif m.group(3) and m.group(4):
            found.append((m.group(4).strip(), float(m.group(3))))
    if not found:
        for m in re.finditer(
            r"(\d+\.\d{2})\s+([A-Za-z0-9 .'\-]{2,40}?)\s+odds\s+pre-match", text, re.I
        ):
            found.append((m.group(2).strip(), float(m.group(1))))
    return _dedupe_odds(found)


def _average_team_odds(books: list[dict[str, Any]]) -> list[tuple[str, float]]:
    sums: dict[str, list[float]] = {}
    display: dict[str, str] = {}
    for book in books:
        for side in ("1", "2"):
            name = book[f"team{side}_name"]
            odds = book[f"team{side}_odds"]
            key = _team_key(name)
            sums.setdefault(key, []).append(float(odds))
            display[key] = name
    return [
        (display[key], round(sum(vals) / len(vals), 3))
        for key, vals in sums.items()
    ]


def _dedupe_odds(rows: list[tuple[str, float]]) -> list[tuple[str, float]]:
    by_team: dict[str, list[float]] = {}
    display: dict[str, str] = {}
    for name, odds in rows:
        key = _team_key(name)
        by_team.setdefault(key, []).append(odds)
        display[key] = name
    return [
        (display[key], round(sum(vals) / len(vals), 3))
        for key, vals in by_team.items()
    ]


def _map_odds_to_teams(
    odds_rows: list[tuple[str, float]],
    team1: str,
    team2: str,
) -> dict[str, float] | None:
    o1 = o2 = None
    for name, odds in odds_rows:
        if _names_match(name, team1):
            o1 = odds
        elif _names_match(name, team2):
            o2 = odds
    if o1 is None and o2 is None:
        return None
    out: dict[str, float] = {}
    if o1 is not None:
        out["team1_odds"] = float(o1)
    if o2 is not None:
        out["team2_odds"] = float(o2)
    return out


def _remap_books_to_caller(
    books: list[dict[str, Any]],
    team1: str,
    team2: str,
) -> list[dict[str, Any]] | None:
    """Normalize each bookie row so team1/team2 match the caller's seating."""
    if not books:
        return None
    sample = books[0]
    left, right = sample["team1_name"], sample["team2_name"]
    if _names_match(left, team1) and _names_match(right, team2):
        flip = False
    elif _names_match(left, team2) and _names_match(right, team1):
        flip = True
    else:
        return None

    out: list[dict[str, Any]] = []
    for b in books:
        if flip:
            out.append(
                {
                    "bookie": b["bookie"],
                    "team1_odds": b["team2_odds"],
                    "team2_odds": b["team1_odds"],
                    "status": b.get("status"),
                }
            )
        else:
            out.append(
                {
                    "bookie": b["bookie"],
                    "team1_odds": b["team1_odds"],
                    "team2_odds": b["team2_odds"],
                    "status": b.get("status"),
                }
            )
    return out


def _match_pairs(match: dict) -> tuple[str, str] | None:
    teams = match.get("teams") or []
    if len(teams) < 2:
        a = match.get("team1") or match.get("team_a")
        b = match.get("team2") or match.get("team_b")
        if isinstance(a, dict):
            a = a.get("name")
        if isinstance(b, dict):
            b = b.get("name")
        if a and b:
            return str(a), str(b)
        return None
    t0 = teams[0].get("name") if isinstance(teams[0], dict) else teams[0]
    t1 = teams[1].get("name") if isinstance(teams[1], dict) else teams[1]
    if not t0 or not t1:
        return None
    return str(t0), str(t1)


def _pair_is_matchup(a: str, b: str, team1: str, team2: str) -> bool:
    return (_names_match(a, team1) and _names_match(b, team2)) or (
        _names_match(a, team2) and _names_match(b, team1)
    )


def _candidate_from_href(
    href: str,
    team_a: str,
    team_b: str,
    status: str | None = None,
) -> dict | None:
    if not href:
        return None
    path = href.split("?", 1)[0]
    m = re.match(r"^/(\d+)/", path)
    if not m:
        return None
    mid = m.group(1)
    match_url = href if href.startswith("http") else f"https://www.vlr.gg{path}"
    return {
        "match_id": mid,
        "url": match_url,
        "vlr_team_a": team_a,
        "vlr_team_b": team_b,
        "status": status,
    }


def _candidate_from_listing_anchor(
    anchor,
    team1: str,
    team2: str,
) -> dict | None:
    team_blocks = anchor.select(".match-item-vs-team .text-of")
    names = [clean_team_display_name(el.get_text(" ", strip=True)) for el in team_blocks]
    if len(names) < 2:
        names = [
            clean_team_display_name(el.get_text(" ", strip=True))
            for el in anchor.select(".m-item-team-name")
        ]
    if len(names) < 2:
        return None
    a, b = names[0], names[1]
    if not _pair_is_matchup(a, b, team1, team2):
        return None
    status_el = anchor.select_one(".ml-status")
    status = status_el.get_text(strip=True) if status_el else None
    return _candidate_from_href(anchor.get("href") or "", a, b, status)


def _find_match_candidate_from_vlrgg(
    session: requests.Session,
    team1: str,
    team2: str,
) -> dict | None:
    """Find a match URL by scraping vlr.gg lists, then team match history."""
    for url in (
        "https://www.vlr.gg/matches",
        "https://www.vlr.gg/matches/?group=upcoming",
        "https://www.vlr.gg/matches/results",
        "https://www.vlr.gg/matches/results/?page=2",
    ):
        try:
            resp = _get_with_retry(
                session,
                url,
                timeout=_ODDS_TIMEOUT,
                retries=_ODDS_RETRIES,
            )
            if resp is None or resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for anchor in soup.select("a.match-item"):
                found = _candidate_from_listing_anchor(anchor, team1, team2)
                if found:
                    return found
        except Exception:
            continue
        time.sleep(REQUEST_DELAY)

    for seed in (team1, team2):
        found = _find_match_on_team_history(session, seed, team1, team2)
        if found:
            return found
    return None


def _find_match_on_team_history(
    session: requests.Session,
    seed_team: str,
    team1: str,
    team2: str,
) -> dict | None:
    """Team results pages keep H2H after it falls off /matches/results page 1."""
    tid = _vlr_team_id(seed_team)
    if not tid:
        return None
    url = f"https://www.vlr.gg/team/matches/{tid}/"
    try:
        resp = _get_with_retry(
            session,
            url,
            timeout=_ODDS_TIMEOUT,
            retries=_ODDS_RETRIES,
        )
        if resp is None or resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        for anchor in soup.select("a.m-item"):
            found = _candidate_from_listing_anchor(anchor, team1, team2)
            if found:
                found["status"] = found.get("status") or "completed"
                return found
    except Exception:
        return None
    return None


def _find_match_candidate(
    session: requests.Session,
    team1: str,
    team2: str,
) -> dict | None:
    """Prefer vlr.gg scrape; the JSON mirror is often down and too slow for odds."""
    scraped = _find_match_candidate_from_vlrgg(session, team1, team2)
    if scraped:
        return scraped

    for path, params in (
        ("matches", {"page": 1, "status": "upcoming"}),
        ("matches", {"page": 1, "status": "live"}),
    ):
        try:
            resp = _get_with_retry(
                session,
                f"{VLR_API}/{path}",
                params=params,
                timeout=_ODDS_API_TIMEOUT,
                retries=1,
            )
            if resp is None or resp.status_code != 200:
                continue
            payload = resp.json()
        except Exception:
            continue
        data = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(data, list):
            continue
        for match in data:
            pair = _match_pairs(match) if isinstance(match, dict) else None
            if not pair:
                continue
            a, b = pair
            if not _pair_is_matchup(a, b, team1, team2):
                continue
            mid = str(match.get("id") or match.get("match_id") or "")
            slug = str(match.get("slug") or "match")
            url = match.get("url") or (
                VLR_MATCH_URL.format(match_id=mid, slug=slug) if mid else None
            )
            if not url and mid:
                url = f"https://www.vlr.gg/{mid}"
            if url:
                return {
                    "match_id": mid,
                    "url": url,
                    "vlr_team_a": a,
                    "vlr_team_b": b,
                    "status": match.get("status"),
                }
    return None

def fetch_match_odds(team1: str, team2: str) -> dict[str, Any] | None:
    """Return averaged decimal odds + per-bookie lines from VLR Betting module."""
    cache_key = f"{_team_key(team1)}::{_team_key(team2)}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached  # type: ignore[return-value]

    try:
        session = _session()
        candidate = _find_match_candidate(session, team1, team2)
        if not candidate:
            _cache_set(cache_key, None)
            return None
        resp = _get_with_retry(
            session,
            candidate["url"],
            timeout=_ODDS_TIMEOUT,
            retries=_ODDS_RETRIES,
        )
        if resp is None or resp.status_code != 200:
            _cache_set(cache_key, None)
            return None

        books_raw = parse_betting_books(resp.text)
        books = _remap_books_to_caller(books_raw, team1, team2)
        if not books:
            # Try seating against VLR's listed order
            books = _remap_books_to_caller(
                books_raw, candidate["vlr_team_a"], candidate["vlr_team_b"]
            )
            if books and not (
                _names_match(candidate["vlr_team_a"], team1)
                and _names_match(candidate["vlr_team_b"], team2)
            ):
                books = [
                    {
                        "bookie": b["bookie"],
                        "team1_odds": b["team2_odds"],
                        "team2_odds": b["team1_odds"],
                        "status": b.get("status"),
                    }
                    for b in books
                ]

        if books:
            avg1 = round(sum(b["team1_odds"] for b in books) / len(books), 3)
            avg2 = round(sum(b["team2_odds"] for b in books) / len(books), 3)
            out = {
                "team1_odds": avg1,
                "team2_odds": avg2,
                "method": "vlr_bookie_avg",
                "bookies": books,
                "bookie_count": len(books),
                "source_url": candidate["url"],
                "match_id": candidate.get("match_id"),
                "status": candidate.get("status"),
            }
            _cache_set(cache_key, out)
            return out

        # Fallback to legacy blurb parsing
        rows = parse_odds_from_html(resp.text)
        mapped = _map_odds_to_teams(rows, team1, team2)
        if mapped is None and rows:
            mapped = _map_odds_to_teams(
                rows, candidate["vlr_team_a"], candidate["vlr_team_b"]
            )
            if mapped and not _names_match(candidate["vlr_team_a"], team1):
                swapped = {
                    "team1_odds": mapped.get("team2_odds"),
                    "team2_odds": mapped.get("team1_odds"),
                }
                mapped = {k: v for k, v in swapped.items() if v is not None} or None
        if not mapped:
            _cache_set(cache_key, None)
            return None
        both = mapped.get("team1_odds") is not None and mapped.get("team2_odds") is not None
        out = {
            **mapped,
            "method": "vlr_blurb" if both else "vlr_post_odds",
            "bookies": [],
            "bookie_count": 0,
            "source_url": candidate["url"],
            "match_id": candidate.get("match_id"),
            "status": candidate.get("status"),
        }
        _cache_set(cache_key, out)
        return out
    except Exception:
        _cache_set(cache_key, None)
        return None
