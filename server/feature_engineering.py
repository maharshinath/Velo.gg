"""Point-in-time and live feature builders for match winner prediction."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from context_features import enrich_context_features, roster_stability_from_ratings
from map_features import enrich_map_features
from tournament_utils import is_international_tournament, shrink_rate
import vct_config
from vct_config import (
    ELO_INITIAL,
    H2H_MIN_TRUST_MATCHES,
    RECENT_H2H_MATCHES,
    RECENT_LAN_MATCHES,
    RECENT_PLAYER_STAT_MATCHES,
    RECENT_WINRATE_MATCHES,
)

PLAYER_STAT_KEYS = (
    "K/D Ratio",
    "Average Damage",
    "Average Combat Score",
    "Average First Kills",
    "Average First Deaths Per Round",
    "Rating",
    "KAST",
    "Clutch Success",
)

PLAYER_STAT_SOURCE_COLUMNS = {
    "K/D Ratio": "Kills:Deaths",
    "Average Damage": "Average Damage Per Round",
    "Average Combat Score": "Average Combat Score",
    "Average First Kills": "First Kills",
    "Average First Deaths Per Round": "First Deaths Per Round",
    "Rating": "Rating",
    "KAST": "Kill, Assist, Trade, Survive %",
    "Clutch Success": "Clutch Success %",
}

PLAYER_STAT_COLUMN_FALLBACKS: dict[str, tuple[str, ...]] = {
    "Average First Kills": ("First Kills", "First Kills Per Round"),
}

PLAYER_STAT_LOAD_COLUMNS = [
    "Tournament",
    "Stage",
    "Match Type",
    "Teams",
    *PLAYER_STAT_SOURCE_COLUMNS.values(),
    "First Kills Per Round",
]

DEFAULT_PLAYER_STATS = {
    "K/D Ratio": 1.0,
    "Average Damage": 130.0,
    "Average Combat Score": 200.0,
    "Average First Kills": 5.0,
    "Average First Deaths Per Round": 0.25,
    "Rating": 1.0,
    "KAST": 70.0,
    "Clutch Success": 15.0,
}


def _parse_stat_values(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace("%", "", regex=False).str.strip()
    return pd.to_numeric(cleaned, errors="coerce")


def aggregate_player_rows(rows: pd.DataFrame) -> dict[str, float] | None:
    if rows.empty:
        return None
    out: dict[str, float] = {}
    for key, col in PLAYER_STAT_SOURCE_COLUMNS.items():
        candidates = PLAYER_STAT_COLUMN_FALLBACKS.get(key, (col,))
        for candidate in candidates:
            if candidate not in rows.columns:
                continue
            values = _parse_stat_values(rows[candidate]).dropna()
            if values.empty:
                continue
            out[key] = float(values.mean())
            break
    return out or None


def _mean_snapshots(snapshots: list[dict[str, float]] | deque[dict[str, float]]) -> dict[str, float]:
    if not snapshots:
        return dict(DEFAULT_PLAYER_STATS)
    history = list(snapshots)[-RECENT_PLAYER_STAT_MATCHES:]
    out: dict[str, float] = {}
    for key in PLAYER_STAT_KEYS:
        values = [snap[key] for snap in history if key in snap]
        out[key] = sum(values) / len(values) if values else DEFAULT_PLAYER_STATS[key]
    return out


def _canonical_pair(team_a: str, team_b: str) -> tuple[str, str]:
    return tuple(sorted((team_a, team_b)))


def _match_map_key(tournament: str, stage: str, match_type: str, team_a: str, team_b: str) -> tuple:
    return (str(tournament), str(stage), str(match_type), frozenset((str(team_a), str(team_b))))


def series_margin_factor(score_a: float | int | None, score_b: float | int | None) -> float:
    """Soft margin scaling so sweeps matter without overpowering Elo."""
    try:
        a = int(score_a) if score_a is not None else 0
        b = int(score_b) if score_b is not None else 0
    except (TypeError, ValueError):
        return 1.0
    margin = abs(a - b)
    if margin <= 0:
        return 1.0
    if margin >= 2:
        return float(vct_config.ELO_MARGIN_SWEEP)
    return float(vct_config.ELO_MARGIN_CLOSE)

@dataclass
class MatchFeatureTracker:
    """Rolling, point-in-time state updated after each match in chronological order."""

    winrate_window: int = RECENT_WINRATE_MATCHES
    h2h_window: int = RECENT_H2H_MATCHES
    player_window: int = RECENT_PLAYER_STAT_MATCHES
    lan_window: int = RECENT_LAN_MATCHES
    regions: dict[str, str] | None = None

    def __post_init__(self) -> None:
        # (result 0/1, weight) for margin-aware form.
        self._win_history: dict[str, deque[tuple[int, float]]] = defaultdict(
            lambda: deque(maxlen=self.winrate_window)
        )
        self._lan_win_history: dict[str, deque[tuple[int, float]]] = defaultdict(
            lambda: deque(maxlen=self.lan_window)
        )
        self._h2h_history: dict[tuple[str, str], list[int]] = {}
        self._player_history: dict[str, list[dict[str, float]]] = defaultdict(list)
        self._elo: dict[str, float] = defaultdict(lambda: ELO_INITIAL)
        self._international_elo: dict[str, float] = defaultdict(lambda: ELO_INITIAL)
        self._player_stats_index: dict[tuple, dict[str, float] | pd.DataFrame] = {}
        self._player_bucket_consumed: set[tuple] = set()
        self._map_stats: dict[tuple[str, str], dict[str, int]] = defaultdict(
            lambda: {"wins": 0, "played": 0}
        )
        self._map_scores_index: dict[tuple, pd.DataFrame] = {}

    def index_player_stats(self, player_stats: pd.DataFrame) -> None:
        if player_stats is None or player_stats.empty:
            self._player_stats_index = {}
            return
        stats = player_stats
        if "Teams" in stats.columns:
            stats["Teams"] = stats["Teams"].astype(str).str.strip()
        numeric_keys: list[str] = []
        work = stats[["Tournament", "Stage", "Match Type", "Teams"]].copy()
        for key, col in PLAYER_STAT_SOURCE_COLUMNS.items():
            candidates = PLAYER_STAT_COLUMN_FALLBACKS.get(key, (col,))
            chosen = next((c for c in candidates if c in stats.columns), None)
            if chosen is None:
                continue
            work[key] = _parse_stat_values(stats[chosen])
            numeric_keys.append(key)
        if not numeric_keys:
            self._player_stats_index = {}
            return
        means = work.groupby(["Tournament", "Stage", "Match Type", "Teams"], sort=False)[
            numeric_keys
        ].mean()
        grouped: dict[tuple, dict[str, float]] = {}
        for idx, row in means.iterrows():
            snap = {k: float(v) for k, v in row.items() if pd.notna(v)}
            if snap:
                grouped[idx if isinstance(idx, tuple) else (idx,)] = snap
        self._player_stats_index = grouped

    def release_replay_indexes(self) -> None:
        """Drop per-match lookup tables after history replay (live API only needs rolling state)."""
        self._player_stats_index = {}
        self._map_scores_index = {}
        self._player_bucket_consumed = set()

    def index_map_scores(self, map_scores: pd.DataFrame | None) -> None:
        self._map_scores_index = {}
        if map_scores is None or map_scores.empty:
            return
        maps = map_scores.copy()
        for col in ("Team A", "Team B", "Tournament", "Stage", "Match Type"):
            if col not in maps.columns:
                return
            maps[col] = maps[col].astype(str).str.strip()
        maps["_pair"] = [
            frozenset((a, b)) for a, b in zip(maps["Team A"], maps["Team B"])
        ]
        grouped: dict[tuple, pd.DataFrame] = {}
        for keys, group in maps.groupby(
            ["Tournament", "Stage", "Match Type", "_pair"], sort=False
        ):
            grouped[keys] = group.drop(columns=["_pair"])
        self._map_scores_index = grouped

    def seed_map_stats(self, lookup: dict[tuple[str, str], dict] | None) -> None:
        """Seed cumulative map WRs (RAM-safe live path; skips full map-score replay)."""
        if not lookup:
            return
        for (team, map_name), entry in lookup.items():
            played = int(entry.get("played", 0) or 0)
            wins = int(entry.get("wins", 0) or 0)
            if played <= 0:
                continue
            self._map_stats[(str(team), str(map_name))] = {
                "wins": wins,
                "played": played,
            }

    def _map_lookup(self) -> dict[tuple[str, str], dict]:
        return {
            key: {
                "wins": int(stats["wins"]),
                "played": int(stats["played"]),
                "winrate": (
                    stats["wins"] / stats["played"] * 100 if stats["played"] else 50.0
                ),
            }
            for key, stats in self._map_stats.items()
        }

    def _weighted_rate(self, history: deque[tuple[int, float]]) -> float:
        if not history:
            return 50.0
        weight = sum(w for _, w in history)
        if weight <= 0:
            return 50.0
        return sum(result * w for result, w in history) / weight * 100

    def _winrate(self, team: str) -> float:
        return self._weighted_rate(self._win_history[team])

    def _lan_winrate(self, team: str) -> float:
        return self._weighted_rate(self._lan_win_history[team])

    def _h2h_history_for(self, team_a: str, team_b: str) -> tuple[list[int], bool]:
        left, right = _canonical_pair(team_a, team_b)
        history = self._h2h_history.get((left, right), [])
        return history, team_a == left

    def h2h_record(self, team_a: str, team_b: str) -> tuple[int, int, int]:
        """Unshrunk series record: (wins_a, wins_b, meetings)."""
        history, team_a_is_left = self._h2h_history_for(team_a, team_b)
        n = len(history)
        wins_left = int(sum(history))
        wins_right = n - wins_left
        if team_a_is_left:
            return wins_left, wins_right, n
        return wins_right, wins_left, n

    def _h2h_rate(self, team_a: str, team_b: str) -> tuple[float, float, int]:
        history, team_a_is_left = self._h2h_history_for(team_a, team_b)
        if not history:
            return 50.0, 50.0, 0
        wins_left = sum(history)
        n = len(history)
        rate_left = shrink_rate(wins_left / n * 100, n, H2H_MIN_TRUST_MATCHES)
        rate_right = 100.0 - rate_left
        if team_a_is_left:
            return rate_left, rate_right, n
        return rate_right, rate_left, n

    def _recent_h2h_rate(self, team_a: str, team_b: str) -> tuple[float, float, int]:
        history, team_a_is_left = self._h2h_history_for(team_a, team_b)
        if not history:
            return 50.0, 50.0, 0
        recent = history[-self.h2h_window :]
        wins_left = sum(recent)
        n = len(recent)
        rate_left = shrink_rate(wins_left / n * 100, n, H2H_MIN_TRUST_MATCHES)
        rate_right = 100.0 - rate_left
        if team_a_is_left:
            return rate_left, rate_right, n
        return rate_right, rate_left, n

    def _player_stats(self, team: str) -> dict[str, float]:
        return _mean_snapshots(self._player_history[team])

    def _match_player_snapshot(
        self,
        tournament: str,
        stage: str,
        match_type: str,
        team: str,
    ) -> dict[str, float] | None:
        key = (tournament, stage, match_type, team)
        snap = self._player_stats_index.get(key)
        if snap is None:
            return None
        if isinstance(snap, pd.DataFrame):
            return aggregate_player_rows(snap)
        return snap

    def _roster_stability(self, team: str) -> float:
        ratings = [
            snap.get("Rating", 1.0)
            for snap in self._player_history[team][-RECENT_PLAYER_STAT_MATCHES:]
        ]
        return roster_stability_from_ratings(ratings)

    def features_for(
        self,
        team_a: str,
        team_b: str,
        *,
        tournament: str | None = None,
    ) -> dict[str, float | int]:
        h2h_a, h2h_b, h2h_n = self._h2h_rate(team_a, team_b)
        recent_h2h_a, recent_h2h_b, recent_h2h_n = self._recent_h2h_rate(team_a, team_b)
        stats_a = self._player_stats(team_a)
        stats_b = self._player_stats(team_b)
        row: dict[str, float | int] = {
            "Team A Winrate vs B": h2h_a,
            "Team A Recent H2H vs B": recent_h2h_a,
            "Team A H2H Count": h2h_n,
            "Team A Recent H2H Count": recent_h2h_n,
            "Team A Winrate": self._winrate(team_a),
            "Team A Elo": self._elo[team_a],
            "Team A International Elo": self._international_elo[team_a],
            "Team A LAN Winrate": self._lan_winrate(team_a),
            "Team B Winrate vs A": h2h_b,
            "Team B Recent H2H vs A": recent_h2h_b,
            "Team B H2H Count": h2h_n,
            "Team B Recent H2H Count": recent_h2h_n,
            "Team B Winrate": self._winrate(team_b),
            "Team B Elo": self._elo[team_b],
            "Team B International Elo": self._international_elo[team_b],
            "Team B LAN Winrate": self._lan_winrate(team_b),
        }
        for key in PLAYER_STAT_KEYS:
            row[f"Team A {key}"] = stats_a[key]
            row[f"Team B {key}"] = stats_b[key]

        regions = self.regions or {}
        enrich_context_features(
            row,
            team_a=team_a,
            team_b=team_b,
            tournament=tournament,
            regions=regions,
            stability_a=self._roster_stability(team_a),
            stability_b=self._roster_stability(team_b),
        )
        enrich_map_features(row, team_a, team_b, self._map_lookup())
        return row

    def _update_elo(
        self,
        elo: dict[str, float],
        team_a: str,
        team_b: str,
        team_a_won: bool,
        *,
        margin_factor: float = 1.0,
    ) -> None:
        score_a = 1.0 if team_a_won else 0.0
        elo_a = elo[team_a]
        elo_b = elo[team_b]
        expected_a = 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))
        k = float(vct_config.ELO_K_FACTOR) * margin_factor
        elo[team_a] = elo_a + k * (score_a - expected_a)
        elo[team_b] = elo_b + k * ((1.0 - score_a) - (1.0 - expected_a))

    def _record_maps(
        self,
        *,
        tournament: str,
        stage: str,
        match_type: str,
        team_a: str,
        team_b: str,
    ) -> None:
        key = _match_map_key(tournament, stage, match_type, team_a, team_b)
        rows = self._map_scores_index.get(key)
        if rows is None or rows.empty:
            return
        for _, map_row in rows.iterrows():
            map_name = str(map_row.get("Map", "")).strip()
            if not map_name:
                continue
            map_team_a = str(map_row["Team A"]).strip()
            map_team_b = str(map_row["Team B"]).strip()
            try:
                score_a = float(map_row["Team A Score"])
                score_b = float(map_row["Team B Score"])
            except (TypeError, ValueError):
                continue
            if score_a == score_b:
                continue
            winner = map_team_a if score_a > score_b else map_team_b
            for team in (map_team_a, map_team_b):
                stats = self._map_stats[(team, map_name)]
                stats["played"] += 1
                if team == winner:
                    stats["wins"] += 1

    def prepare_match_block(self, tournament: str, stage: str, match_type: str) -> None:
        """Hook for chronological block handling (no-op with immediate player consume)."""
        return

    def flush_pending_player_stats(self) -> None:
        return

    def record(
        self,
        *,
        tournament: str,
        stage: str,
        match_type: str,
        team_a: str,
        team_b: str,
        team_a_won: bool,
        score_a: float | int | None = None,
        score_b: float | int | None = None,
    ) -> None:
        margin = series_margin_factor(score_a, score_b)
        self._update_elo(self._elo, team_a, team_b, team_a_won, margin_factor=margin)

        international = is_international_tournament(tournament)
        if international:
            self._update_elo(
                self._international_elo, team_a, team_b, team_a_won, margin_factor=margin
            )
            self._lan_win_history[team_a].append((1 if team_a_won else 0, margin))
            self._lan_win_history[team_b].append((0 if team_a_won else 1, margin))

        self._win_history[team_a].append((1 if team_a_won else 0, 1.0))
        self._win_history[team_b].append((0 if team_a_won else 1, 1.0))

        left, right = _canonical_pair(team_a, team_b)
        if (left, right) not in self._h2h_history:
            self._h2h_history[(left, right)] = []
        left_won = team_a_won if team_a == left else (not team_a_won)
        self._h2h_history[(left, right)].append(1 if left_won else 0)

        self._record_maps(
            tournament=tournament,
            stage=stage,
            match_type=match_type,
            team_a=team_a,
            team_b=team_b,
        )

        # Consume each week bucket once (avoids double-append; same-week later games
        # still see prior same-week bucket — better than starving form entirely).
        for team in (team_a, team_b):
            key = (str(tournament), str(stage), str(match_type), str(team))
            if key in self._player_bucket_consumed:
                continue
            snapshot = self._match_player_snapshot(tournament, stage, match_type, team)
            if snapshot:
                self._player_history[team].append(snapshot)
            self._player_bucket_consumed.add(key)


def load_team_regions_map() -> dict[str, str]:
    path = Path(__file__).resolve().parent / "csv" / "team_data.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    if "Region" not in df.columns:
        return {}
    return {
        str(team): str(region)
        for team, region in zip(df["Team"], df["Region"])
        if pd.notna(region) and str(region).strip()
    }


def _load_map_scores_optional() -> pd.DataFrame | None:
    try:
        from map_predictions import load_merged_map_scores

        return load_merged_map_scores()
    except Exception:
        return None


def _score_pair(row: pd.Series) -> tuple[float | None, float | None]:
    score_a = row["Team A Score"] if "Team A Score" in row.index else None
    score_b = row["Team B Score"] if "Team B Score" in row.index else None
    return score_a, score_b


def build_live_feature_tracker(
    scores: pd.DataFrame,
    player_stats: pd.DataFrame,
    *,
    regions: dict[str, str] | None = None,
    map_lookup: dict | None = None,
    map_scores: pd.DataFrame | None = None,
) -> MatchFeatureTracker:
    tracker = MatchFeatureTracker(regions=regions)
    tracker.index_player_stats(player_stats)
    # Prefer an explicit CSV lookup for live/API (cheap). Otherwise replay map scores
    # when provided/available. Empty DataFrame means "skip heavy map replay".
    if map_lookup:
        tracker.seed_map_stats(map_lookup)
    elif map_scores is None:
        tracker.index_map_scores(_load_map_scores_optional())
    elif not map_scores.empty:
        tracker.index_map_scores(map_scores)
    team_a_vals = scores["Team A"].to_numpy()
    team_b_vals = scores["Team B"].to_numpy()
    result_vals = scores["Match Result"].astype(str).to_numpy()
    tournament_vals = scores["Tournament"].to_numpy()
    stage_vals = scores["Stage"].to_numpy()
    match_type_vals = scores["Match Type"].to_numpy()
    score_a_vals = (
        scores["Team A Score"].to_numpy() if "Team A Score" in scores.columns else [None] * len(scores)
    )
    score_b_vals = (
        scores["Team B Score"].to_numpy() if "Team B Score" in scores.columns else [None] * len(scores)
    )
    for i in range(len(scores)):
        team_a = team_a_vals[i]
        team_b = team_b_vals[i]
        team_a_won = result_vals[i] == f"{team_a} won"
        tracker.prepare_match_block(tournament_vals[i], stage_vals[i], match_type_vals[i])
        tracker.record(
            tournament=tournament_vals[i],
            stage=stage_vals[i],
            match_type=match_type_vals[i],
            team_a=team_a,
            team_b=team_b,
            team_a_won=team_a_won,
            score_a=score_a_vals[i],
            score_b=score_b_vals[i],
        )
    tracker.flush_pending_player_stats()
    tracker.release_replay_indexes()
    return tracker


def build_match_feature_rows(
    scores: pd.DataFrame,
    player_stats: pd.DataFrame,
    *,
    map_scores: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build training rows with point-in-time features (state before each match)."""
    regions = load_team_regions_map()
    tracker = MatchFeatureTracker(regions=regions)
    tracker.index_player_stats(player_stats)
    maps = map_scores if map_scores is not None else _load_map_scores_optional()
    tracker.index_map_scores(maps)
    records: list[dict] = []
    teams_with_stats: set[str] = set(player_stats["Teams"].astype(str).str.strip())

    for _, row in scores.iterrows():
        team_a = row["Team A"]
        team_b = row["Team B"]
        if team_a not in teams_with_stats or team_b not in teams_with_stats:
            continue

        tracker.prepare_match_block(row["Tournament"], row["Stage"], row["Match Type"])
        feat = tracker.features_for(team_a, team_b, tournament=str(row["Tournament"]))
        records.append(
            {
                "Tournament": row["Tournament"],
                "Stage": row["Stage"],
                "Match Type": row["Match Type"],
                "Team A": team_a,
                "Team B": team_b,
                **feat,
                "Team A Win": int(str(row["Match Result"]) == f"{team_a} won"),
            }
        )
        score_a, score_b = _score_pair(row)
        tracker.record(
            tournament=row["Tournament"],
            stage=row["Stage"],
            match_type=row["Match Type"],
            team_a=team_a,
            team_b=team_b,
            team_a_won=str(row["Match Result"]) == f"{team_a} won",
            score_a=score_a,
            score_b=score_b,
        )
    tracker.flush_pending_player_stats()
    return pd.DataFrame(records)


def live_features_for_pair(
    team_a: str,
    team_b: str,
    scores: pd.DataFrame,
    player_stats: pd.DataFrame,
) -> dict[str, float | int]:
    tracker = build_live_feature_tracker(scores, player_stats)
    return tracker.features_for(team_a, team_b)


def team_profile_from_tracker(
    tracker: MatchFeatureTracker,
    team: str,
) -> dict[str, float]:
    stats = tracker._player_stats(team)
    return {
        "Winrate": tracker._winrate(team),
        "Elo": tracker._elo[team],
        "International Elo": tracker._international_elo[team],
        "LAN Winrate": tracker._lan_winrate(team),
        **stats,
    }
