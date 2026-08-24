"""Shared match-winner model training utilities."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import RandomizedSearchCV, train_test_split

from feature_engineering import PLAYER_STAT_KEYS
from vct_config import H2H_MIN_TRUST_MATCHES

ELO_BASE_COLS = [
    "Team A Elo",
    "Team B Elo",
    "Team A Winrate",
    "Team B Winrate",
]

# Source columns required to build sparse residual features at inference time.
SPARSE_RESIDUAL_SOURCE_COLS = [
    "Team A International Elo",
    "Team B International Elo",
    "Map pool strength delta",
    "Team A Map Pool Strength",
    "Team B Map Pool Strength",
    "Team A Winrate vs B",
    "Team A H2H Count",
]

MATCH_MODEL_SOURCE_COLS = ELO_BASE_COLS + SPARSE_RESIDUAL_SOURCE_COLS

BLEND_WEIGHT_GRID = [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5]

# Team-A H2H only (Team B H2H is 100 - A; counts are shared).
H2H_FEATURE_COLS = [
    "Team A Winrate vs B",
    "Team A Recent H2H vs B",
    "Team A H2H Count",
    "Team A Recent H2H Count",
]

H2H_MIRROR_COLS = [
    "Team B Winrate vs A",
    "Team B Recent H2H vs A",
    "Team B H2H Count",
    "Team B Recent H2H Count",
]

_ABS_PAIR_STATS = [
    "Winrate",
    "Elo",
    "International Elo",
    "LAN Winrate",
    "Map Pool Strength",
    "Map Pool Differential",
    "Roster Stability",
    *PLAYER_STAT_KEYS,
]

TEAM_A_ABS_COLS = [f"Team A {stat}" for stat in _ABS_PAIR_STATS]
TEAM_B_ABS_COLS = [f"Team B {stat}" for stat in _ABS_PAIR_STATS]

SWAP_BASE_COLS = H2H_FEATURE_COLS + H2H_MIRROR_COLS + TEAM_A_ABS_COLS + TEAM_B_ABS_COLS

CONTEXT_FEATURE_COLS = ["Is LAN", "Same Region"]

DELTA_FEATURE_SPECS = [
    ("H2H delta", "Team A Winrate vs B", "Team B Winrate vs A"),
    ("Recent H2H delta", "Team A Recent H2H vs B", "Team B Recent H2H vs A"),
    ("Winrate delta", "Team A Winrate", "Team B Winrate"),
    ("Elo delta", "Team A Elo", "Team B Elo"),
    ("International Elo delta", "Team A International Elo", "Team B International Elo"),
    ("LAN Winrate delta", "Team A LAN Winrate", "Team B LAN Winrate"),
    ("Map pool strength delta", "Team A Map Pool Strength", "Team B Map Pool Strength"),
    (
        "Map pool differential delta",
        "Team A Map Pool Differential",
        "Team B Map Pool Differential",
    ),
    ("Roster stability delta", "Team A Roster Stability", "Team B Roster Stability"),
    ("K/D delta", "Team A K/D Ratio", "Team B K/D Ratio"),
    ("Damage delta", "Team A Average Damage", "Team B Average Damage"),
    ("ACS delta", "Team A Average Combat Score", "Team B Average Combat Score"),
    ("First kills delta", "Team A Average First Kills", "Team B Average First Kills"),
    (
        "First deaths delta",
        "Team A Average First Deaths Per Round",
        "Team B Average First Deaths Per Round",
    ),
    ("Rating delta", "Team A Rating", "Team B Rating"),
    ("KAST delta", "Team A KAST", "Team B KAST"),
    ("Clutch delta", "Team A Clutch Success", "Team B Clutch Success"),
]

ENGINEERED_FEATURE_COLS = [name for name, _, _ in DELTA_FEATURE_SPECS]
FEATURE_COLS = (
    H2H_FEATURE_COLS
    + H2H_MIRROR_COLS
    + TEAM_A_ABS_COLS
    + TEAM_B_ABS_COLS
    + CONTEXT_FEATURE_COLS
    + ENGINEERED_FEATURE_COLS
)

BASE_FEATURE_COLS = H2H_FEATURE_COLS + H2H_MIRROR_COLS + TEAM_A_ABS_COLS + TEAM_B_ABS_COLS

RF_PARAM_DISTRIBUTION = {
    "n_estimators": [200, 300, 400, 500],
    "max_depth": [10, 14, 18, 22, None],
    "min_samples_leaf": [1, 2, 4, 6],
    "min_samples_split": [2, 4, 8],
    "max_features": ["sqrt", "log2", 0.6],
    "class_weight": ["balanced", "balanced_subsample", None],
}

LGBM_PARAM_DISTRIBUTION = {
    "num_leaves": [15, 23, 31],
    "learning_rate": [0.02, 0.03, 0.05, 0.08],
    "n_estimators": [200, 300, 400],
    "min_child_samples": [20, 30, 40, 50],
    "subsample": [0.7, 0.85],
    "subsample_freq": [1],
    "colsample_bytree": [0.6, 0.8],
    "reg_alpha": [0.1, 0.5, 1.0],
    "reg_lambda": [0.5, 1.0, 2.0],
    "max_depth": [4, 6, 8],
}

DEFAULT_LGBM_PARAMS = {
    "n_estimators": 400,
    "learning_rate": 0.03,
    "num_leaves": 23,
    "max_depth": 6,
    "min_child_samples": 30,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.7,
    "reg_alpha": 0.5,
    "reg_lambda": 1.0,
    "class_weight": "balanced",
}


def add_engineered_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for name, col_a, col_b in DELTA_FEATURE_SPECS:
        if col_a not in out.columns or col_b not in out.columns:
            out[name] = 0.0
            continue
        out[name] = pd.to_numeric(out[col_a], errors="coerce") - pd.to_numeric(
            out[col_b], errors="coerce"
        )
    return out


def _swap_team_columns(df: pd.DataFrame) -> pd.DataFrame:
    swapped = df.copy()
    for a_col, b_col in zip(TEAM_A_ABS_COLS, TEAM_B_ABS_COLS):
        if a_col in df.columns and b_col in df.columns:
            swapped[a_col] = df[b_col]
            swapped[b_col] = df[a_col]
    if "Team A Winrate vs B" in df.columns and "Team B Winrate vs A" in df.columns:
        swapped["Team A Winrate vs B"] = df["Team B Winrate vs A"]
        swapped["Team B Winrate vs A"] = df["Team A Winrate vs B"]
    if "Team A Recent H2H vs B" in df.columns and "Team B Recent H2H vs A" in df.columns:
        swapped["Team A Recent H2H vs B"] = df["Team B Recent H2H vs A"]
        swapped["Team B Recent H2H vs A"] = df["Team A Recent H2H vs B"]
    return swapped


def create_order_invariant_data(df: pd.DataFrame) -> pd.DataFrame:
    base = df.copy()
    for col in SWAP_BASE_COLS + CONTEXT_FEATURE_COLS:
        if col not in base.columns:
            if "Count" in col:
                base[col] = 0
            elif col in CONTEXT_FEATURE_COLS:
                base[col] = 0
            elif "Elo" in col:
                base[col] = 1500.0
            else:
                base[col] = 50.0
    if "Team A Win" not in base.columns:
        raise KeyError("Team A Win")
    cols = SWAP_BASE_COLS + CONTEXT_FEATURE_COLS + ["Team A Win"]
    base = base[cols]
    original = add_engineered_features(base)
    swapped_base = _swap_team_columns(base)
    swapped_base["Team A Win"] = 1 - base["Team A Win"].astype(int)
    swapped = add_engineered_features(swapped_base)
    out = pd.concat([original, swapped], ignore_index=True)
    for col in FEATURE_COLS:
        if col not in out.columns:
            out[col] = 0.0
    return out


def load_model_bundle(path) -> tuple[Any, list[str]]:
    import joblib

    loaded = joblib.load(path)
    if isinstance(loaded, dict) and "model" in loaded:
        return loaded["model"], list(loaded.get("feature_cols", FEATURE_COLS))
    return loaded, FEATURE_COLS


def save_model_bundle(
    path,
    model: Any,
    feature_cols: list[str] | None = None,
    *,
    algorithm: str = "lgbm_calibrated",
    metrics: dict | None = None,
) -> None:
    import joblib

    joblib.dump(
        {
            "model": model,
            "feature_cols": feature_cols or FEATURE_COLS,
            "algorithm": algorithm,
            "version": 9,
            "metrics": metrics or {},
        },
        path,
    )


def _split_time_ordered(matches: pd.DataFrame, test_size: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    split = max(1, int(len(matches) * (1 - test_size)))
    return matches.iloc[:split], matches.iloc[split:]


def _prepare_xy(matches: pd.DataFrame, time_ordered: bool, test_size: float, random_state: int):
    if time_ordered:
        train_base, test_base = _split_time_ordered(matches, test_size)
        train_aug = create_order_invariant_data(train_base)
        test_aug = create_order_invariant_data(test_base)
        return (
            train_aug[FEATURE_COLS],
            train_aug["Team A Win"].astype(int),
            test_aug[FEATURE_COLS],
            test_aug["Team A Win"].astype(int),
        )

    augmented = create_order_invariant_data(matches)
    x = augmented[FEATURE_COLS]
    y = augmented["Team A Win"].astype(int)
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=test_size, random_state=random_state, stratify=y
    )
    return x_train, y_train, x_test, y_test


def _new_lgbm(params: dict, *, random_state: int):
    from lightgbm import LGBMClassifier

    allowed = {
        "num_leaves",
        "learning_rate",
        "n_estimators",
        "min_child_samples",
        "subsample",
        "subsample_freq",
        "colsample_bytree",
        "reg_alpha",
        "reg_lambda",
        "max_depth",
        "class_weight",
    }
    model_params = {k: v for k, v in params.items() if k in allowed}
    class_weight = model_params.pop("class_weight", "balanced")
    model_params.setdefault("subsample_freq", 1)
    return LGBMClassifier(
        random_state=random_state,
        n_jobs=-1,
        verbose=-1,
        class_weight=class_weight,
        **model_params,
    )


def _fit_lgbm(
    x_train: pd.DataFrame,
    y_train: pd.Series,
    *,
    tune: bool,
    random_state: int,
    x_val: pd.DataFrame | None = None,
    y_val: pd.Series | None = None,
) -> tuple[Any, dict]:
    try:
        from lightgbm import LGBMClassifier  # noqa: F401
    except ImportError:
        return _fit_rf(x_train, y_train, tune=tune, random_state=random_state)

    if tune:
        search = RandomizedSearchCV(
            _new_lgbm({"class_weight": "balanced", "subsample_freq": 1}, random_state=random_state),
            param_distributions=LGBM_PARAM_DISTRIBUTION,
            n_iter=40,
            cv=5,
            scoring="neg_log_loss",
            random_state=random_state,
            n_jobs=-1,
            verbose=1,
        )
        search.fit(x_train, y_train)
        best_params = dict(search.best_params_)
        best_params.setdefault("subsample_freq", 1)
    else:
        best_params = dict(DEFAULT_LGBM_PARAMS)
        n_estimators = _early_stopped_estimators(
            x_train,
            y_train,
            params=best_params,
            random_state=random_state,
            x_val=x_val,
            y_val=y_val,
        )
        best_params["n_estimators"] = n_estimators

    base = _new_lgbm(best_params, random_state=random_state)
    base.fit(x_train, y_train)

    calibrated = CalibratedClassifierCV(base, method="isotonic", cv=5)
    calibrated.fit(x_train, y_train)
    return calibrated, best_params


def _chronological_fit_val_split(
    x_train: pd.DataFrame,
    y_train: pd.Series,
    *,
    val_frac: float = 0.15,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series] | None:
    """Late-slice validation: last val_frac rows of training window (pre-holdout)."""
    n = len(x_train)
    if n < 40:
        return None
    split = max(1, int(n * (1 - val_frac)))
    if split >= n - 5:
        return None
    return (
        x_train.iloc[:split],
        y_train.iloc[:split],
        x_train.iloc[split:],
        y_train.iloc[split:],
    )


def _early_stopped_estimators(
    x_train: pd.DataFrame,
    y_train: pd.Series,
    *,
    params: dict,
    random_state: int,
    x_val: pd.DataFrame | None = None,
    y_val: pd.Series | None = None,
) -> int:
    """Choose tree count via early stopping on late chrono slice or stratified holdout."""
    from lightgbm import early_stopping, log_evaluation

    if x_val is not None and y_val is not None and len(x_val) >= 20:
        x_fit, y_fit, x_es, y_es = x_train, y_train, x_val, y_val
    else:
        # Stratified random on augmented rows (chronological late-slice is misleading
        # after order-invariant doubling concatenates originals then swaps).
        try:
            x_fit, x_es, y_fit, y_es = train_test_split(
                x_train,
                y_train,
                test_size=0.15,
                random_state=random_state,
                stratify=y_train,
            )
        except ValueError:
            return int(params.get("n_estimators", DEFAULT_LGBM_PARAMS["n_estimators"]))

    probe_params = dict(params)
    probe_params["n_estimators"] = int(params.get("n_estimators", 400))
    probe = _new_lgbm(probe_params, random_state=random_state)
    probe.fit(
        x_fit,
        y_fit,
        eval_set=[(x_es, y_es)],
        eval_metric="binary_logloss",
        callbacks=[
            early_stopping(stopping_rounds=40, verbose=False),
            log_evaluation(period=0),
        ],
    )
    best = getattr(probe, "best_iteration_", None)
    if best is None or int(best) <= 0:
        return int(probe_params["n_estimators"])
    return max(50, int(best))


def _fit_rf(
    x_train: pd.DataFrame,
    y_train: pd.Series,
    *,
    tune: bool,
    random_state: int,
) -> tuple[Any, dict]:
    if tune:
        search = RandomizedSearchCV(
            RandomForestClassifier(random_state=random_state, n_jobs=-1),
            param_distributions=RF_PARAM_DISTRIBUTION,
            n_iter=24,
            cv=3,
            scoring="neg_log_loss",
            random_state=random_state,
            n_jobs=-1,
            verbose=1,
        )
        search.fit(x_train, y_train)
        model = search.best_estimator_
        return model, search.best_params_

    model = RandomForestClassifier(
        n_estimators=400,
        max_depth=16,
        min_samples_leaf=2,
        max_features="sqrt",
        class_weight="balanced_subsample",
        random_state=random_state,
        n_jobs=-1,
    )
    model.fit(x_train, y_train)
    return model, model.get_params()


class EloAnchoredClassifier:
    """Calibrated Elo + recent-form blend.

    Complex LGBM on 50+ noisy features underperforms plain Elo on this dataset
    (~55% vs ~61% holdout). This estimator keeps the strongest signal.
    """

    def __init__(self, elo_weight: float = 0.85, wr_weight: float = 0.15):
        self.elo_weight = float(elo_weight)
        self.wr_weight = float(wr_weight)
        self.classes_ = np.array([0, 1])
        self._iso = None

    def _frame(self, X: Any) -> pd.DataFrame:
        if isinstance(X, pd.DataFrame):
            return X
        return pd.DataFrame(X, columns=ELO_BASE_COLS)

    def raw_probability(self, X: Any) -> np.ndarray:
        df = self._frame(X)
        ea = pd.to_numeric(df["Team A Elo"], errors="coerce").fillna(1500.0).to_numpy(dtype=float)
        eb = pd.to_numeric(df["Team B Elo"], errors="coerce").fillna(1500.0).to_numpy(dtype=float)
        elo_p = 1.0 / (1.0 + np.power(10.0, (eb - ea) / 400.0))

        wa = pd.to_numeric(df["Team A Winrate"], errors="coerce").fillna(50.0).to_numpy(dtype=float) / 100.0
        wb = pd.to_numeric(df["Team B Winrate"], errors="coerce").fillna(50.0).to_numpy(dtype=float) / 100.0
        denom = np.clip(wa + wb, 1e-6, None)
        wr_p = wa / denom

        w = self.elo_weight + self.wr_weight
        elo_w = self.elo_weight / w
        wr_w = self.wr_weight / w
        return elo_w * elo_p + wr_w * wr_p

    def fit(self, X: Any, y: Any):
        # Elo expected scores are already well-scaled; isotonic recalibration
        # was observed to *hurt* holdout accuracy on this dataset (~61% -> ~57%).
        y_arr = np.asarray(y).astype(int)
        self.classes_ = np.unique(y_arr)
        if self.classes_.size < 2:
            self.classes_ = np.array([0, 1])
        self._iso = None
        self._fitted_ = True
        return self

    def predict_proba(self, X: Any) -> np.ndarray:
        raw = self.raw_probability(X)
        p = np.clip(np.asarray(raw, dtype=float), 0.02, 0.98)
        return np.column_stack([1.0 - p, p])

    def predict(self, X: Any) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)

    def score(self, X: Any, y: Any) -> float:
        y_arr = np.asarray(y).astype(int)
        return float((self.predict(X) == y_arr).mean())


def build_sparse_residual_features(df: pd.DataFrame) -> pd.DataFrame:
    """Trusted deltas only: intl Elo Δ, map-pool Δ, shrunk H2H when count is enough."""
    intl_a = pd.to_numeric(df.get("Team A International Elo"), errors="coerce").fillna(1500.0)
    intl_b = pd.to_numeric(df.get("Team B International Elo"), errors="coerce").fillna(1500.0)
    intl_delta = (intl_a - intl_b) / 400.0

    if "Map pool strength delta" in df.columns:
        map_delta = pd.to_numeric(df["Map pool strength delta"], errors="coerce").fillna(0.0)
    else:
        ma = pd.to_numeric(df.get("Team A Map Pool Strength"), errors="coerce").fillna(0.0)
        mb = pd.to_numeric(df.get("Team B Map Pool Strength"), errors="coerce").fillna(0.0)
        map_delta = ma - mb
    map_delta = map_delta / 100.0

    h2h_wr = pd.to_numeric(df.get("Team A Winrate vs B"), errors="coerce").fillna(50.0)
    h2h_n = pd.to_numeric(df.get("Team A H2H Count"), errors="coerce").fillna(0.0)
    trusted_h2h = np.where(
        h2h_n.to_numpy(dtype=float) >= float(H2H_MIN_TRUST_MATCHES),
        (h2h_wr.to_numpy(dtype=float) - 50.0) / 50.0,
        0.0,
    )

    return pd.DataFrame(
        {
            "intl_elo_delta": intl_delta.to_numpy(dtype=float),
            "map_pool_delta": map_delta.to_numpy(dtype=float),
            "trusted_h2h": trusted_h2h,
        },
        index=df.index,
    )


class EloSparseResidualClassifier:
    """Blend pure Elo probability with a tiny logistic residual."""

    def __init__(
        self,
        elo_model: EloAnchoredClassifier,
        residual_model: Any,
        blend_weight: float,
        feature_cols: list[str],
    ):
        self.elo_model = elo_model
        self.residual_model = residual_model
        self.blend_weight = float(blend_weight)
        self.feature_cols = list(feature_cols)
        self.classes_ = np.array([0, 1])

    def _frame(self, X: Any) -> pd.DataFrame:
        if isinstance(X, pd.DataFrame):
            return X
        return pd.DataFrame(X, columns=self.feature_cols)

    def predict_proba(self, X: Any) -> np.ndarray:
        df = self._frame(X)
        p_elo = self.elo_model.raw_probability(df)
        x_res = build_sparse_residual_features(df)
        p_res = self.residual_model.predict_proba(x_res)[:, 1]
        w = self.blend_weight
        p = (1.0 - w) * p_elo + w * p_res
        p = np.clip(np.asarray(p, dtype=float), 0.02, 0.98)
        return np.column_stack([1.0 - p, p])

    def predict(self, X: Any) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)

    def score(self, X: Any, y: Any) -> float:
        y_arr = np.asarray(y).astype(int)
        return float((self.predict(X) == y_arr).mean())


def _match_feature_cols(matches: pd.DataFrame) -> list[str]:
    return [c for c in MATCH_MODEL_SOURCE_COLS if c in matches.columns]


def _fit_elo_anchored(
    x_train: pd.DataFrame,
    y_train: pd.Series,
    *,
    x_val: pd.DataFrame | None = None,
    y_val: pd.Series | None = None,
) -> tuple[EloAnchoredClassifier, dict]:
    """Pure Elo expected score (form blend historically underperformed on holdout)."""
    del x_val, y_val  # kept for call-site compatibility
    model = EloAnchoredClassifier(elo_weight=1.0, wr_weight=0.0)
    model.fit(x_train, y_train)
    return model, {"elo_weight": 1.0, "wr_weight": 0.0}


def _fit_sparse_residual(
    x_train: pd.DataFrame,
    y_train: pd.Series,
    *,
    x_val: pd.DataFrame,
    y_val: pd.Series,
    elo_model: EloAnchoredClassifier,
    feature_cols: list[str],
) -> tuple[EloSparseResidualClassifier | None, dict]:
    """Fit residual logistic; return model only when blend beats pure Elo on val."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    x_res_train = build_sparse_residual_features(x_train)
    x_res_val = build_sparse_residual_features(x_val)
    residual = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "lr",
                LogisticRegression(
                    C=0.5,
                    max_iter=1000,
                    random_state=42,
                    class_weight="balanced",
                ),
            ),
        ]
    )
    residual.fit(x_res_train, y_train)

    y_val_arr = np.asarray(y_val).astype(int)
    p_elo = elo_model.raw_probability(x_val)
    p_res = residual.predict_proba(x_res_val)[:, 1]
    elo_acc = float(((p_elo >= 0.5).astype(int) == y_val_arr).mean())

    best_w = 0.0
    best_acc = elo_acc
    for w in BLEND_WEIGHT_GRID:
        p = (1.0 - w) * p_elo + w * p_res
        acc = float(((p >= 0.5).astype(int) == y_val_arr).mean())
        if acc > best_acc:
            best_acc = acc
            best_w = w

    params = {
        "blend_weight": best_w,
        "elo_val_accuracy": round(elo_acc * 100, 1),
        "residual_val_accuracy": round(best_acc * 100, 1),
        "residual_features": list(x_res_train.columns),
    }
    # Strict beat-Elo gate: residual must improve validation accuracy.
    if best_w <= 0.0 or best_acc <= elo_acc:
        return None, params

    model = EloSparseResidualClassifier(
        elo_model=elo_model,
        residual_model=residual,
        blend_weight=best_w,
        feature_cols=feature_cols,
    )
    return model, params


def train_match_model(
    matches: pd.DataFrame,
    *,
    tune: bool = True,
    test_size: float = 0.2,
    random_state: int = 42,
    time_ordered: bool = True,
    refit_full: bool = True,
) -> tuple[Any, dict]:
    """Train Elo (+ sparse residual only if it strictly beats pure Elo)."""
    del tune, random_state  # unused; kept for call-site compatibility
    if time_ordered:
        train_base, test_base = _split_time_ordered(matches, test_size)
    else:
        train_base, test_base = train_test_split(
            matches, test_size=test_size, random_state=42, stratify=matches["Team A Win"]
        )

    needed = _match_feature_cols(matches)
    if not all(c in needed for c in ELO_BASE_COLS):
        needed = [c for c in ELO_BASE_COLS if c in matches.columns]

    # Nested validation inside the train window for blend / Elo-weight selection.
    if time_ordered and len(train_base) >= 80:
        fit_base, val_base = _split_time_ordered(train_base, 0.2)
    else:
        fit_base, val_base = train_base, test_base

    x_fit = fit_base[needed]
    y_fit = fit_base["Team A Win"].astype(int)
    x_val = val_base[needed]
    y_val = val_base["Team A Win"].astype(int)
    x_test = test_base[needed]
    y_test = test_base["Team A Win"].astype(int)

    elo_model, elo_params = _fit_elo_anchored(
        x_fit, y_fit, x_val=x_val, y_val=y_val
    )
    residual_model, residual_params = _fit_sparse_residual(
        x_fit,
        y_fit,
        x_val=x_val,
        y_val=y_val,
        elo_model=elo_model,
        feature_cols=needed,
    )

    elo_test_acc = float(elo_model.score(x_test, y_test))
    if residual_model is not None:
        residual_test_acc = float(residual_model.score(x_test, y_test))
    else:
        residual_test_acc = -1.0

    # Strict gate: residual must beat pure Elo on the untouched holdout.
    if residual_model is not None and residual_test_acc > elo_test_acc:
        holdout_model = residual_model
        algorithm = "elo_sparse_residual"
        best_params = {**elo_params, **residual_params}
        test_acc = residual_test_acc
        train_acc = float(residual_model.score(x_fit, y_fit))
        feature_cols = needed
    else:
        holdout_model = elo_model
        algorithm = "elo_anchored"
        best_params = {
            **elo_params,
            **residual_params,
            "residual_rejected": True,
            "residual_holdout_accuracy": (
                None if residual_test_acc < 0 else round(residual_test_acc * 100, 1)
            ),
        }
        test_acc = elo_test_acc
        train_acc = float(elo_model.score(x_fit, y_fit))
        feature_cols = [c for c in ELO_BASE_COLS if c in needed]

    if refit_full:
        if algorithm == "elo_sparse_residual":
            full_elo, _ = _fit_elo_anchored(
                matches[needed],
                matches["Team A Win"].astype(int),
                x_val=x_val,
                y_val=y_val,
            )
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import Pipeline
            from sklearn.preprocessing import StandardScaler

            residual = Pipeline(
                [
                    ("scaler", StandardScaler()),
                    (
                        "lr",
                        LogisticRegression(
                            C=0.5,
                            max_iter=1000,
                            random_state=42,
                            class_weight="balanced",
                        ),
                    ),
                ]
            )
            residual.fit(
                build_sparse_residual_features(matches[needed]),
                matches["Team A Win"].astype(int),
            )
            model = EloSparseResidualClassifier(
                elo_model=full_elo,
                residual_model=residual,
                blend_weight=float(best_params.get("blend_weight", 0.1)),
                feature_cols=needed,
            )
        else:
            model, _ = _fit_elo_anchored(
                matches[feature_cols],
                matches["Team A Win"].astype(int),
                x_val=x_val[feature_cols] if all(c in x_val.columns for c in feature_cols) else x_test[feature_cols],
                y_val=y_val if all(c in x_val.columns for c in feature_cols) else y_test,
            )
    else:
        model = holdout_model

    report = {
        "train_accuracy": round(train_acc * 100, 1),
        "test_accuracy": round(test_acc * 100, 1),
        "elo_test_accuracy": round(elo_test_acc * 100, 1),
        "best_params": best_params,
        "feature_count": len(feature_cols),
        "feature_cols": feature_cols,
        "training_rows": len(matches),
        "augmented_rows": len(matches),
        "time_ordered_split": time_ordered,
        "refit_full": refit_full,
        "algorithm": algorithm,
    }
    return model, report


def evaluate_time_ordered_accuracy(matches: pd.DataFrame, test_frac: float = 0.2) -> float:
    """Pure-Elo holdout accuracy (used for Elo K/margin grid search)."""
    train_base, test_base = _split_time_ordered(matches, test_frac)
    needed = [c for c in ELO_BASE_COLS if c in matches.columns]
    model, _ = _fit_elo_anchored(
        train_base[needed],
        train_base["Team A Win"].astype(int),
        x_val=test_base[needed],
        y_val=test_base["Team A Win"].astype(int),
    )
    return float(model.score(test_base[needed], test_base["Team A Win"].astype(int)))


def walk_forward_accuracy(
    matches: pd.DataFrame,
    *,
    n_folds: int = 4,
    min_train: int = 200,
) -> dict[str, float] | None:
    """Expanding-window walk-forward accuracy for monitoring."""
    if len(matches) < min_train + 50:
        return None
    fold_scores: list[float] = []
    test_span = max(40, (len(matches) - min_train) // n_folds)
    for i in range(n_folds):
        split = min_train + i * test_span
        end = min(split + test_span, len(matches))
        if end <= split or split < min_train:
            continue
        window = matches.iloc[:end].reset_index(drop=True)
        test_frac = len(matches.iloc[split:end]) / len(window)
        if test_frac <= 0 or test_frac >= 1:
            continue
        _, fold_report = train_match_model(
            window,
            tune=False,
            test_size=test_frac,
            time_ordered=True,
            refit_full=False,
        )
        fold_scores.append(float(fold_report["test_accuracy"]) / 100.0)
    if not fold_scores:
        return None
    return {
        "walk_forward_accuracy": float(np.mean(fold_scores)),
        "walk_forward_folds": float(len(fold_scores)),
    }


def probability_scores(model: Any, x_test: pd.DataFrame, y_test: pd.Series) -> dict[str, float]:
    from sklearn.metrics import brier_score_loss, log_loss

    proba = model.predict_proba(x_test)[:, 1]
    preds = (proba >= 0.5).astype(int)
    accuracy = float((preds == y_test.to_numpy()).mean())
    brier = float(brier_score_loss(y_test, proba))
    logloss = float(log_loss(y_test, np.clip(proba, 1e-6, 1 - 1e-6)))
    return {"accuracy": accuracy, "brier_score": brier, "log_loss": logloss}
