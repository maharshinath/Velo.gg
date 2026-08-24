"""Evaluate model with random, time-ordered, and segment-specific splits."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd
from sklearn.metrics import accuracy_score

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

from model_training import (  # noqa: E402
    ELO_BASE_COLS,
    MATCH_MODEL_SOURCE_COLS,
    load_model_bundle,
    probability_scores,
    train_match_model,
    walk_forward_accuracy,
)
from tournament_utils import is_international_tournament  # noqa: E402
from vct_config import BETTING_CONFIDENCE_GATE  # noqa: E402

METRICS_PATH = SERVER_DIR / "data" / "model_metrics.json"


def _feature_cols_for(df: pd.DataFrame) -> list[str]:
    cols = [c for c in MATCH_MODEL_SOURCE_COLS if c in df.columns]
    if all(c in cols for c in ELO_BASE_COLS):
        return cols
    return [c for c in ELO_BASE_COLS if c in df.columns]


def is_regional_vct(tournament: str) -> bool:
    return bool(re.match(r"^VCT \d{4}:", str(tournament)))


def _evaluate_random_split(df: pd.DataFrame, test_frac: float = 0.2) -> dict[str, float] | None:
    if len(df) < 20:
        return None
    model, report = train_match_model(
        df, tune=False, test_size=test_frac, time_ordered=False, refit_full=False
    )
    # Approximate probability metrics on a fresh stratified holdout; accuracy from report.
    from sklearn.model_selection import train_test_split

    cols = list(report.get("feature_cols") or _feature_cols_for(df))
    use_cols = [c for c in cols if c in df.columns]
    x = df[use_cols]
    y = df["Team A Win"].astype(int)
    _, x_test, _, y_test = train_test_split(
        x, y, test_size=test_frac, random_state=42, stratify=y
    )
    try:
        scores = probability_scores(model, x_test, y_test)
    except Exception:
        scores = {"accuracy": 0.0, "brier_score": float("nan"), "log_loss": float("nan")}
    scores["accuracy"] = float(report["test_accuracy"]) / 100.0
    return scores


def _evaluate_segment(df: pd.DataFrame, test_frac: float = 0.2) -> dict[str, float] | None:
    if len(df) < 20:
        return None
    model, report = train_match_model(
        df, tune=False, test_size=test_frac, time_ordered=True, refit_full=False
    )
    split = max(1, int(len(df) * (1 - test_frac)))
    test_base = df.iloc[split:]
    if test_base.empty:
        return None
    cols = list(report.get("feature_cols") or getattr(model, "feature_cols", None) or _feature_cols_for(df))
    use_cols = [c for c in cols if c in test_base.columns]
    if not use_cols:
        use_cols = _feature_cols_for(test_base)
    scores = probability_scores(
        model, test_base[use_cols], test_base["Team A Win"].astype(int)
    )
    scores["accuracy"] = float(report["test_accuracy"]) / 100.0
    probs = model.predict_proba(test_base[use_cols])[:, 1]
    y = test_base["Team A Win"].astype(int).to_numpy()
    scores["selective"] = _selective_accuracy(probs, y, BETTING_CONFIDENCE_GATE)
    return scores


def _selective_accuracy(
    probs,
    y_true,
    gate: float,
) -> dict[str, float] | None:
    """Accuracy when only betting the favorite at/above the confidence gate."""
    import numpy as np

    probs = np.asarray(probs, dtype=float)
    y_true = np.asarray(y_true, dtype=int)
    favored = np.maximum(probs, 1.0 - probs)
    mask = favored >= gate
    coverage = float(mask.mean()) if len(mask) else 0.0
    if not mask.any():
        return {"accuracy": None, "coverage": round(coverage * 100, 1), "n": 0}
    preds = (probs[mask] >= 0.5).astype(int)
    return {
        "accuracy": float(accuracy_score(y_true[mask], preds)),
        "coverage": round(coverage * 100, 1),
        "n": int(mask.sum()),
    }


def main() -> None:
    matches_path = SERVER_DIR / "csv" / "filtered_matches.csv"
    df = pd.read_csv(matches_path)
    deployed, feature_cols = load_model_bundle(SERVER_DIR / "models" / "rf.pkl")
    import joblib

    bundle = joblib.load(SERVER_DIR / "models" / "rf.pkl")
    bundle_metrics = bundle.get("metrics", {}) if isinstance(bundle, dict) else {}

    random_scores = _evaluate_random_split(df)
    all_scores = _evaluate_segment(df)
    intl_df = df[df["Tournament"].astype(str).map(is_international_tournament)]
    vct_df = df[df["Tournament"].astype(str).map(is_regional_vct)]
    intl_scores = _evaluate_segment(intl_df)
    vct_scores = _evaluate_segment(vct_df)

    # Prefer the true time-ordered holdout from training when the deployed model
    # was refit on all rows (circular holdout would read ~100%).
    if bundle_metrics.get("refit_full") and bundle_metrics.get("holdout_test_accuracy") is not None:
        deployed_acc = float(bundle_metrics["holdout_test_accuracy"]) / 100.0
    else:
        split = int(len(df) * 0.8)
        holdout = df.iloc[split:]
        cols = [c for c in feature_cols if c in holdout.columns]
        deployed_probs = deployed.predict_proba(holdout[cols])[:, 1]
        deployed_preds = (deployed_probs >= 0.5).astype(int)
        deployed_acc = accuracy_score(holdout["Team A Win"].astype(int), deployed_preds)

    wf = walk_forward_accuracy(df)
    selective = (all_scores or {}).get("selective") if all_scores else None

    metrics = {
        "random_split_accuracy": round(random_scores["accuracy"] * 100, 1) if random_scores else None,
        "time_ordered_split_accuracy": round(all_scores["accuracy"] * 100, 1) if all_scores else None,
        "vct_regional_split_accuracy": round(vct_scores["accuracy"] * 100, 1) if vct_scores else None,
        "international_split_accuracy": round(intl_scores["accuracy"] * 100, 1) if intl_scores else None,
        "brier_score": round(all_scores["brier_score"], 4) if all_scores else None,
        "log_loss": round(all_scores["log_loss"], 4) if all_scores else None,
        "deployed_model_holdout_accuracy": round(deployed_acc * 100, 1),
        "walk_forward_accuracy": (
            round(wf["walk_forward_accuracy"] * 100, 1) if wf else None
        ),
        "selective_65_accuracy": (
            round(selective["accuracy"] * 100, 1)
            if selective and selective.get("accuracy") is not None
            else None
        ),
        "selective_65_coverage": selective.get("coverage") if selective else None,
        "selective_65_n": selective.get("n") if selective else None,
        "betting_confidence_gate": round(BETTING_CONFIDENCE_GATE * 100, 1),
        "feature_count": len(feature_cols),
        "note": (
            "Segment splits use time-ordered holdout. "
            "selective_65_* = accuracy/coverage when only picking favorites "
            f"at confidence ≥ {BETTING_CONFIDENCE_GATE*100:.0f}%. "
            "Lower Brier score = better calibrated probabilities."
        ),
    }
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
