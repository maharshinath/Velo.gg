"""Confidence labels, key factors, series simulation, recent form."""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import pandas as pd

from vct_config import (
    H2H_MIN_TRUST_MATCHES,
    RECENT_FORM_MATCHES,
    RECENT_H2H_MATCHES,
    RECENT_LAN_MATCHES,
    RECENT_WINRATE_MATCHES,
)

SERVER_DIR = Path(__file__).resolve().parent
KAGGLE_DIR = SERVER_DIR / "data" / "kaggle"


def confidence_label(team1_prob: float) -> dict:
    """Human-readable confidence from favorite's win %."""
    favorite = max(team1_prob, 100.0 - team1_prob)
    edge = abs(team1_prob - 50.0)
    if favorite >= 65 and edge >= 15:
        level, text = "likely", "Likely"
    elif edge >= 8:
        level, text = "slight", "Slight edge"
    else:
        level, text = "tossup", "Toss-up"
    return {"level": level, "label": text, "favorite_probability": round(favorite, 1)}


def implied_prob_from_decimal(odds: float) -> float:
    if odds <= 1.0:
        return 1.0
    return 1.0 / odds


def decimal_ev(prob: float, decimal_odds: float) -> float:
    """Expected value of staking 1 unit at decimal odds with true win prob."""
    return prob * decimal_odds - 1.0


def build_betting_insight(
    team1: str,
    team2: str,
    model_p_team1: float,
    *,
    odds: dict | None = None,
) -> dict:
    """Betting decision from model probability vs book implied probability.

    Tip the side where our estimated win chance exceeds the (fair) book chance.
    No fixed confidence gate (e.g. 65%) — value is edge only.
    """
    p1 = float(model_p_team1)
    p2 = 1.0 - p1
    model_favored = team1 if p1 >= p2 else team2

    out: dict = {
        "model_prob_team1": round(p1, 4),
        "model_prob_team2": round(p2, 4),
        "favored_team": model_favored,
        "confidence_pct": round(max(p1, p2) * 100, 1),
        "odds_available": False,
        "recommendation": "pass",
        "recommendation_label": "Need book prices to compare",
        "tip_team": None,
        "edge_pp": None,
        "disclaimer": (
            "Informational only. Not financial advice. Tips compare our win chance "
            "to the book sites' implied chance (prices from VLR)."
        ),
    }

    if not odds:
        return out

    o1 = odds.get("team1_odds")
    o2 = odds.get("team2_odds")
    try:
        o1_f = float(o1) if o1 is not None else None
        o2_f = float(o2) if o2 is not None else None
    except (TypeError, ValueError):
        return out

    have_both = o1_f is not None and o2_f is not None and o1_f > 1.0 and o2_f > 1.0
    if not have_both:
        if o1_f is not None and o1_f > 1.0:
            out["team1_odds"] = round(o1_f, 3)
            out["implied_prob_team1"] = round(implied_prob_from_decimal(o1_f) * 100, 1)
        if o2_f is not None and o2_f > 1.0:
            out["team2_odds"] = round(o2_f, 3)
            out["implied_prob_team2"] = round(implied_prob_from_decimal(o2_f) * 100, 1)
        if out.get("team1_odds") or out.get("team2_odds"):
            out["odds_method"] = odds.get("method")
            out["source_url"] = odds.get("source_url")
            out["match_id"] = odds.get("match_id")
            out["recommendation_label"] = (
                "Only one pre-match price is still listed on VLR (usual after the match)."
            )
        return out

    i1 = implied_prob_from_decimal(o1_f)
    i2 = implied_prob_from_decimal(o2_f)
    overround = i1 + i2
    fair1 = i1 / overround if overround > 0 else i1
    fair2 = i2 / overround if overround > 0 else i2

    # Compare model to raw implied (1/odds). Same rule as +EV after juice.
    edge1 = p1 - i1
    edge2 = p2 - i2
    if edge1 >= edge2:
        tip_team, tip_p, tip_book, tip_odds, tip_edge = team1, p1, i1, o1_f, edge1
    else:
        tip_team, tip_p, tip_book, tip_odds, tip_edge = team2, p2, i2, o2_f, edge2

    tip_ev = decimal_ev(tip_p, tip_odds)
    has_value = tip_edge > 0

    out.update(
        {
            "odds_available": True,
            "team1_odds": round(o1_f, 3),
            "team2_odds": round(o2_f, 3),
            "implied_prob_team1": round(i1 * 100, 1),
            "implied_prob_team2": round(i2 * 100, 1),
            "fair_implied_prob_team1": round(fair1 * 100, 1),
            "fair_implied_prob_team2": round(fair2 * 100, 1),
            "edge_team1_pp": round(edge1 * 100, 1),
            "edge_team2_pp": round(edge2 * 100, 1),
            "edge_favored_pp": round(tip_edge * 100, 1),
            "edge_pp": round(tip_edge * 100, 1),
            "ev_unit": round(tip_ev, 3),
            "tip_team": tip_team,
            "tip_model_pct": round(tip_p * 100, 1),
            "tip_book_pct": round(tip_book * 100, 1),
            "tip_odds": round(tip_odds, 3),
            "odds_method": odds.get("method"),
            "bookie_count": odds.get("bookie_count") or len(odds.get("bookies") or []),
            "bookies": odds.get("bookies") or [],
            "source_url": odds.get("source_url"),
            "match_id": odds.get("match_id"),
        }
    )

    if has_value:
        out["recommendation"] = "bet"
        out["recommendation_label"] = f"Value on {tip_team} @ {tip_odds:.2f}"
        out["favored_team"] = tip_team
    else:
        out["recommendation"] = "pass"
        out["recommendation_label"] = "No value vs book prices"

    return out


def build_key_factors(
    team1: str,
    team2: str,
    favored_team: str,
    feature_row: pd.Series,
    recent_form: dict[str, float],
    agent_diversity: dict[str, float],
) -> list[dict]:
    factor_defs = [
        ("Head-to-head record", "Team A Winrate vs B", "Team B Winrate vs A", True, True, "Team A H2H Count"),
        (
            f"Recent head-to-head (last {RECENT_H2H_MATCHES})",
            "Team A Recent H2H vs B",
            "Team B Recent H2H vs A",
            True,
            True,
            "Team A Recent H2H Count",
        ),
        (f"Recent win rate (last {RECENT_WINRATE_MATCHES} matches)", "Team A Winrate", "Team B Winrate", True, True, None),
        ("Elo rating", "Team A Elo", "Team B Elo", True, True, None),
        ("International Elo", "Team A International Elo", "Team B International Elo", True, True, None),
        (f"LAN win rate (last {RECENT_LAN_MATCHES} intl. matches)", "Team A LAN Winrate", "Team B LAN Winrate", True, True, None),
        ("Player rating", "Team A Rating", "Team B Rating", True, True, None),
        ("KAST", "Team A KAST", "Team B KAST", True, True, None),
        ("Clutch success", "Team A Clutch Success", "Team B Clutch Success", True, True, None),
        ("Recent form (last matches)", None, None, True, False, None),
        ("Agent pool diversity", None, None, True, False, None),
        ("K/D ratio", "Team A K/D Ratio", "Team B K/D Ratio", True, True, None),
        ("Average damage", "Team A Average Damage", "Team B Average Damage", True, True, None),
        ("Average combat score", "Team A Average Combat Score", "Team B Average Combat Score", True, True, None),
        ("Average first kills", "Team A Average First Kills", "Team B Average First Kills", True, True, None),
        (
            "Average first deaths per round",
            "Team A Average First Deaths Per Round",
            "Team B Average First Deaths Per Round",
            False,
            True,
            None,
        ),
    ]

    def fmt_pct(a: float, b: float) -> str:
        return f"{a:.1f}% vs {b:.1f}%"

    def fmt_num(a: float, b: float, decimals: int = 1) -> str:
        return f"{a:.{decimals}f} vs {b:.{decimals}f}"

    candidates: list[tuple[float, str, str]] = []

    for label, col_a, col_b, higher_better, from_row, count_col in factor_defs:
        if count_col and float(feature_row.get(count_col, 0)) < H2H_MIN_TRUST_MATCHES:
            continue
        if from_row and col_a and col_b:
            v1, v2 = float(feature_row[col_a]), float(feature_row[col_b])
            if "win rate" in label.lower() or "head-to-head" in label.lower():
                detail = fmt_pct(v1, v2)
            elif "Deaths" in label:
                detail = fmt_num(v1, v2, 2) + " per round"
            else:
                detail = fmt_num(v1, v2, 2 if "K/D" in label else 1)
        elif label.startswith("Recent form"):
            v1, v2 = recent_form.get(team1, 50.0), recent_form.get(team2, 50.0)
            detail = fmt_pct(v1, v2)
        else:
            v1, v2 = agent_diversity.get(team1, 0.0), agent_diversity.get(team2, 0.0)
            detail = f"{v1:.0f} agents vs {v2:.0f} agents used"

        if higher_better:
            margin = abs(v1 - v2)
            team1_better = v1 > v2
        else:
            margin = abs(v2 - v1)
            team1_better = v1 < v2

        if margin <= 0:
            continue
        favored_is_team1 = favored_team == team1
        if (favored_is_team1 and team1_better) or (not favored_is_team1 and not team1_better):
            candidates.append((margin, label, detail))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [{"label": label, "detail": detail} for _, label, detail in candidates[:6]]


def compute_recent_winrates(
    scores: pd.DataFrame,
    n: int = RECENT_WINRATE_MATCHES,
) -> dict[str, float]:
    """Per-team win % over each team's last n completed matches."""
    team_results: dict[str, list[int]] = defaultdict(list)
    for _, row in scores.iterrows():
        team_a, team_b = row["Team A"], row["Team B"]
        winner = str(row["Match Result"]).replace(" won", "")
        team_results[team_a].append(1 if winner == team_a else 0)
        team_results[team_b].append(1 if winner == team_b else 0)

    out: dict[str, float] = {}
    for team, results in team_results.items():
        recent = results[-n:]
        out[team] = sum(recent) / len(recent) * 100 if recent else 50.0
    return out


def compute_recent_form(scores: pd.DataFrame, n: int = RECENT_FORM_MATCHES) -> dict[str, float]:
    return compute_recent_winrates(scores, n=n)


def compute_agent_diversity() -> dict[str, float]:
    """Unique agents picked per team across latest Kaggle season data."""
    year_dirs = sorted(KAGGLE_DIR.glob("vct_*"), reverse=True)
    for year_dir in year_dirs:
        path = year_dir / "agents" / "teams_picked_agents.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path)
        if "Team" not in df.columns or "Agent" not in df.columns:
            continue
        return df.groupby("Team")["Agent"].nunique().to_dict()
    return {}


def sort_map_predictions(map_predictions: list[dict]) -> list[dict]:
    return sorted(map_predictions, key=lambda m: m["map"].lower())


def _map_pick_pool(comp_maps: list[dict], used: frozenset[str]) -> list[dict]:
    """Maps still available; once all are used, the full pool is available again."""
    remaining = [m for m in comp_maps if m["map"] not in used]
    return remaining if remaining else comp_maps


def _exact_series_win_prob(
    comp_maps: tuple[dict, ...],
    t1: int,
    t2: int,
    used: frozenset[str],
    wins_needed: int,
) -> float:
    """Exact team1 series win probability (uniform random map pick from pool)."""
    if t1 >= wins_needed:
        return 1.0
    if t2 >= wins_needed:
        return 0.0

    pool = _map_pick_pool(list(comp_maps), used)
    n = len(pool)
    prob = 0.0
    for pick in pool:
        p1 = pick["team1_win_probability"] / 100.0
        used_next = used | {pick["map"]}
        prob += (1.0 / n) * (
            p1 * _exact_series_win_prob(comp_maps, t1 + 1, t2, used_next, wins_needed)
            + (1.0 - p1) * _exact_series_win_prob(comp_maps, t1, t2 + 1, used_next, wins_needed)
        )
    return prob


@lru_cache(maxsize=128)
def _cached_series_prob(
    map_probs: tuple[tuple[str, float], ...],
    best_of: int,
) -> float:
    comp_maps = tuple({"map": name, "team1_win_probability": p1} for name, p1 in map_probs)
    wins_needed = best_of // 2 + 1
    return _exact_series_win_prob(comp_maps, 0, 0, frozenset(), wins_needed)


def simulate_series(
    map_predictions: list[dict],
    best_of: int = 3,
    trials: int = 6000,
) -> dict:
    """Deterministic BoN series probability from per-map win rates (comp pool only)."""
    del trials  # kept for API compatibility; exact calc replaces Monte Carlo
    comp_maps = [m for m in map_predictions if m.get("in_comp_pool")]
    if not comp_maps:
        comp_maps = list(map_predictions)
    if not comp_maps:
        return {
            "format": f"Bo{best_of}",
            "team1_series_win_probability": 50.0,
            "team2_series_win_probability": 50.0,
            "maps_considered": [],
            "method": "exact",
        }

    map_probs = tuple(
        sorted((m["map"], float(m["team1_win_probability"])) for m in comp_maps)
    )
    p1 = round(_cached_series_prob(map_probs, best_of) * 100, 1)
    return {
        "format": f"Bo{best_of}",
        "team1_series_win_probability": p1,
        "team2_series_win_probability": round(100.0 - p1, 1),
        "maps_considered": [m["map"] for m in comp_maps],
        "method": "exact",
    }
