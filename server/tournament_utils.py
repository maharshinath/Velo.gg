"""Tournament classification, chronological sorting, and H2H shrinkage."""

from __future__ import annotations

import re
from datetime import datetime

import pandas as pd

PRO_TOURNAMENT_PATTERN = re.compile(
    r"Valorant Champions|Valorant Masters|Esports World Cup|VCT \d{4}:",
    re.I,
)

PRO_EVENT_START_PATTERN = re.compile(
    r"^(Valorant Champions|Valorant Masters|Esports World Cup|VCT \d{4}: (Americas|EMEA|Pacific|China))",
    re.I,
)

INTERNATIONAL_PATTERN = re.compile(
    r"Valorant Champions|Valorant Masters|Esports World Cup",
    re.I,
)

STANDARD_MAPS = frozenset(
    {
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
    }
)

H2H_MIN_TRUST_MATCHES = 3

SCORES_COLUMNS = [
    "Tournament",
    "Stage",
    "Match Type",
    "Match Name",
    "Team A",
    "Team B",
    "Team A Score",
    "Team B Score",
    "Match Result",
    "Match Date",
]

MAPS_SCORES_COLUMNS = [
    "Tournament",
    "Stage",
    "Match Type",
    "Map",
    "Team A",
    "Team B",
    "Team A Score",
    "Team B Score",
]


def normalize_map_name(name: str) -> str | None:
    cleaned = " ".join(str(name).split())
    if not cleaned:
        return None
    title = cleaned.title()
    if title in STANDARD_MAPS:
        return title
    lower = cleaned.lower()
    for standard in STANDARD_MAPS:
        if standard.lower() == lower:
            return standard
    # VLR headers often include "PICK" and duration: "Ascent PICK 1:22:04"
    for standard in STANDARD_MAPS:
        token = standard.lower()
        if lower == token or lower.startswith(token + " ") or f" {token} " in f" {lower} ":
            return standard
    return None


def is_pro_tournament(name: str) -> bool:
    return bool(PRO_TOURNAMENT_PATTERN.search(str(name)))


def is_pro_event_name(name: str) -> bool:
    normalized = normalize_tournament_name(name)
    if "ascension" in normalized.lower():
        return False
    return bool(PRO_EVENT_START_PATTERN.match(normalized))


def is_international_tournament(name: str) -> bool:
    return bool(INTERNATIONAL_PATTERN.search(str(name)))


def normalize_tournament_name(name: str) -> str:
    """Normalize VLR/Kaggle tournament labels to canonical names."""
    name = " ".join(str(name).split())

    ewc = re.search(
        r"(?:Valorant at\s+)?(?:Esports World Cup|EWC)\s*['']?(\d{2,4})",
        name,
        re.I,
    )
    if ewc:
        year = ewc.group(1)
        if len(year) == 2:
            year = f"20{year}"
        return f"Esports World Cup {year}"

    m = re.search(
        r"VCT\s*(\d{2,4}):\s*(\w+)\s+(Kickoff|Stage\s*\d+)",
        name,
        re.I,
    )
    if m:
        year = m.group(1)
        if len(year) == 2:
            year = f"20{year}"
        region_map = {
            "AMER": "Americas",
            "AMERICAS": "Americas",
            "EMEA": "EMEA",
            "PAC": "Pacific",
            "PACIFIC": "Pacific",
            "CN": "China",
            "CHINA": "China",
        }
        region = region_map.get(m.group(2).upper(), m.group(2).title())
        tail = m.group(3)
        if re.search(r"kickoff", tail, re.I):
            return f"VCT {year}: {region} Kickoff"
        stage_num = re.search(r"(\d+)", tail)
        if stage_num:
            return f"VCT {year}: {region} Stage {stage_num.group(1)}"

    masters = re.search(r"^(?:Valorant\s+)?Masters\s+(.+)$", name, re.I)
    if masters:
        return f"Valorant Masters {masters.group(1)}"

    # World Championship only — not "Valorant Champions Tour ...".
    if not re.search(r"Champions\s+Tour", name, re.I):
        year_first = re.search(
            r"^(?:Valorant\s+)?Champions\s+(\d{4})(?:\s*[:\-]?\s*[A-Za-z]+)?$",
            name,
            re.I,
        )
        if year_first:
            return f"Valorant Champions {year_first.group(1)}"
        city_year = re.search(
            r"^(?:Valorant\s+)?Champions\s+([A-Za-z]+)\s+(\d{4})$",
            name,
            re.I,
        )
        if city_year and city_year.group(1).lower() not in {"tour", "stage", "kickoff"}:
            return f"Valorant Champions {city_year.group(2)}"
        # VLR cards sometimes omit the year ("Champions Shanghai").
        if re.search(r"^(?:Valorant\s+)?Champions\s+Shanghai$", name, re.I):
            return "Valorant Champions 2026"

    return name


def infer_tournament_year(tournament: str) -> int:
    m = re.search(r"(20\d{2})", str(tournament))
    if m:
        return int(m.group(1))
    return 2021


def tournament_tier(tournament: str) -> int:
    name = str(tournament)
    if "Champions" in name:
        return 50
    if "World Cup" in name or re.search(r"\bEWC\b", name, re.I):
        return 40
    if "Masters" in name:
        return 35
    if "Stage 2" in name:
        return 25
    if "Stage 1" in name:
        return 20
    if "Kickoff" in name:
        return 15
    if "VCT" in name:
        return 10
    return 5


def stage_sort_key(stage: str) -> int:
    text = str(stage).lower()
    if "group" in text:
        return 10
    if "swiss" in text:
        return 20
    if "playoff" in text:
        return 30
    if "final" in text:
        return 40
    return 15


def parse_match_date(
    value: str | None,
    *,
    tournament: str | None = None,
    tournament_year: int | None = None,
) -> datetime | None:
    """Parse a match date, injecting tournament year for yearless VLR strings."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    # Strip common VLR timezone tokens (IST etc.) before parsing.
    text = re.sub(
        r"(?i)[\s\u00a0\u202f]*(?:IST|PST|PDT|EST|EDT|CST|CDT|MST|MDT|UTC|GMT|"
        r"CET|CEST|JST|KST|SGT|AEDT|AEST|BST|WIB|WITA)\s*$",
        "",
        text,
    ).strip()
    text = re.sub(r"\s*[-–—]?\s*Patch\b.*$", "", text, flags=re.I).strip()
    text = re.sub(r"\s+", " ", text).strip()

    year = tournament_year
    if year is None and tournament is not None:
        year = infer_tournament_year(tournament)

    parsed: datetime | None = None
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
        "%A, %B %d %I:%M %p",
        "%A, %B %d %H:%M",
        "%A, %b %d %I:%M %p",
        "%A, %B %d, %Y %I:%M %p",
        "%A, %B %d, %Y",
    ):
        try:
            parsed = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        fallback = pd.to_datetime(text, errors="coerce")
        if pd.isna(fallback):
            return None
        parsed = fallback.to_pydatetime()
        if getattr(parsed, "tzinfo", None) is not None:
            parsed = parsed.replace(tzinfo=None)

    # Yearless formats (e.g. "Thursday, July 9 1:30 PM") default to 1900.
    if parsed.year < 2020:
        if year is None or year < 2020:
            return None
        parsed = parsed.replace(year=int(year))
    return parsed


def shrink_rate(rate_pct: float, sample_size: int, min_full: int = H2H_MIN_TRUST_MATCHES) -> float:
    """Shrink a percentage rate toward 50% when sample size is small."""
    if sample_size <= 0:
        return 50.0
    weight = min(1.0, sample_size / min_full)
    return rate_pct * weight + 50.0 * (1.0 - weight)


def shrink_probability(prob: float, sample_size: int, min_full: int = H2H_MIN_TRUST_MATCHES) -> float:
    weight = min(1.0, sample_size / min_full)
    return prob * weight + 0.5 * (1.0 - weight)


def ensure_scores_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in SCORES_COLUMNS:
        if col not in out.columns:
            out[col] = None
    return out[SCORES_COLUMNS]


def sort_scores_chronologically(df: pd.DataFrame) -> pd.DataFrame:
    """Sort matches oldest-first using match dates when present, else tournament heuristics."""
    out = ensure_scores_columns(df)
    out["_orig_idx"] = range(len(out))
    out["_tier"] = out["Tournament"].map(tournament_tier)

    sort_dates: list[datetime] = []
    for _, row in out.iterrows():
        year = infer_tournament_year(row["Tournament"])
        parsed = parse_match_date(
            row.get("Match Date"),
            tournament=str(row["Tournament"]),
            tournament_year=year,
        )
        if parsed is None:
            tier = tournament_tier(row["Tournament"])
            stage = stage_sort_key(row.get("Stage", ""))
            pseudo = datetime(year, min(12, max(1, tier // 4 + 1)), min(28, stage + 1))
            sort_dates.append(pseudo)
        else:
            sort_dates.append(parsed)
    out["_sort_date"] = sort_dates
    out = out.sort_values(["_sort_date", "_tier", "_orig_idx"], ascending=True)
    return out.drop(columns=["_orig_idx", "_sort_date", "_tier"]).reset_index(drop=True)
