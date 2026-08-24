# Velo.gg

**Velo.gg** is Elo-backed Valorant Champions Tour match forecasting — pick any two pro teams, get a winner call, per-map breakdowns, stat comparisons, roster intel, and a live upcoming VCT schedule.

[![Live](https://img.shields.io/badge/Live-velo--gg.onrender.com-2ea44f)](https://velo-gg.onrender.com)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)](https://react.dev/)
[![Flask](https://img.shields.io/badge/Flask-3-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Model](https://img.shields.io/badge/Model-Elo%20%2B%20margin-F7931E?logo=scikit-learn&logoColor=white)](https://scikit-learn.org/)
[![Accuracy](https://img.shields.io/badge/Holdout~63.2%25-time--ordered-2ea44f)](./README.md#model-accuracy)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

**Live app:** [https://velo-gg.onrender.com](https://velo-gg.onrender.com)

Velo.gg is based on [terrdv/VCT-Match-Predictor](https://github.com/terrdv/VCT-Match-Predictor), extended with a Kaggle data pipeline, VLR live sync, 2021–2026 seasons, point-in-time features, Elo-anchored match modeling, map-level models, and a full UI redesign.

| Snapshot | |
|---|---|
| **Matches** | 1,269 pro series |
| **Teams** | 90 |
| **Model** | Elo + series-margin updates |
| **Honest holdout** | ~63.2% (time-ordered) |

---

## What it does

1. **Select two VCT teams** from **90** pro rosters with logos and region tags.
2. **Get a match winner prediction** with confidence tier (Likely · Slight edge · Toss-up), animated reveal, and a highlighted predicted winner strip.
3. **Browse upcoming VCT 2026 games** on the home page (live + upcoming from VLR), then jump straight into a prediction.
4. **Drill into detail tabs** — map-by-map win chances, head-to-head stats, full breakdown with key factors, and live rosters.

Shareable URLs: `/predict/Sentinels/Fnatic` (team names are URL-encoded automatically).

---

## Dataset (current)

| | |
|---|---|
| **Pro matches** | **1,269** |
| **Teams** | **90** |
| **Season span** | 2021 – **2026** |
| **Latest events** | VCT 2026 Stage 2 (Americas / Pacific / China / EMEA), earlier Stage 1 + Masters |

**Sources:** [Kaggle VCT 2021–2026](https://www.kaggle.com/datasets/ryanluong1/valorant-champion-tour-2021-2023-data) (base) + **[VLR](https://vlr.orlandomm.net/)** ingestion for newer pro matches (`sync_vlr_data.py`).

Match results and player stats refresh via VLR sync; map stats come from rebuilt map CSVs.

---

## Screens & features

### Home
- Dual team dropdowns with search-friendly labels
- Matchup preview cards once both teams are selected
- **Upcoming VCT Games** — live and upcoming VCT 2026 matches from VLR, with Predict links
- One-click navigation to the prediction view

### Prediction page

| Area | What you get |
|------|----------------|
| **Winner strip** | Side-by-side team cards, gold “Predicted” badge, shimmer border, and glow on the favored team |
| **Confidence badge** | Likely / Slight edge / Toss-up based on model margin |
| **Map Predictions** | Competitive-pool maps, Valorant splash art, per-map win %, favored team logo |
| **Stats** | H2H win rates, Recharts comparison chart, metrics table with leader logos on each delta |
| **Breakdown** | Full winner analysis, win probabilities, and “why this team is favored” key factors |
| **Roaster** | Player rosters lazy-loaded from the VLR API when you open the tab |

### About
- Dataset attribution and live model accuracy from `model_metrics.json`

---

## Model accuracy

Refresh metrics anytime:

```bash
cd server
python scripts/evaluate_model.py
```

| Metric | Value | Meaning |
|--------|------:|---------|
| Time-ordered split | **63.2%** | Train on earlier matches, test on later ones (honest baseline) |
| Deployed holdout | **63.2%** | Saved model evaluated on the same time-ordered holdout |
| International events | **64.9%** | Time-ordered holdout on internationals only |
| Regional VCT | **61.3%** | Time-ordered holdout on regional VCT events |
| Walk-forward | **59.2%** | Rolling retrain accuracy across the timeline |
| Random split | **60.7%** | Stratified shuffle (less realistic than time-ordered) |

> **Honest reading:** Prefer the **time-ordered** figure (**~63%**) over random-split numbers. Complex tree models on noisy features underperformed Elo on this dataset. The deployed match model stays Elo-anchored (a sparse residual is trained but only shipped when it beats pure Elo on holdout).

| | |
|---|---|
| **Match model** | Elo-anchored classifier (team Elo with series-margin K scaling) |
| **Features (match)** | Elo plus a gated sparse residual (**11** columns when residual ships) |
| **Training data** | Point-in-time rolling features (no full-career leakage on H2H / form) |
| **Map model** | Separate map win % from `map_team_stats.csv` / `map_h2h_stats.csv` |
| **Extras** | Confidence labels, key factors, series simulation helpers |

Raw Kaggle files (~79 MB) are not committed. Download into `server/data/kaggle/` with `update_dataset.py --download`.

---

## Quick start

### Prerequisites

- Python **3.10+**
- Node.js **18+**
- [Kaggle API credentials](https://www.kaggle.com/docs/api) (only for `--download`)

### Install

```bash
git clone https://github.com/maharshinath/Velo.gg.git
cd Velo.gg

cd server && pip install -r requirements.txt
cd ../client && npm install
```

### Build dataset & model (first run)

```bash
cd server
python scripts/update_dataset.py --download
```

Generates `csv/*.csv`, map stats, and `models/rf.pkl` (bundle still named `rf.pkl` for compatibility).

### Run locally

**Windows (easy):** double-click `start.bat`, or use `start-backend.bat` / `start-frontend.bat`.

**API** (port **5001** — avoids Windows conflicts on 5000):

```bash
cd server
python -c "from app import app; app.run(debug=True, port=5001, use_reloader=False)"
```

**Frontend:**

```bash
cd client
npm run dev
```

| Service | URL |
|---------|-----|
| **Live app** | https://velo-gg.onrender.com |
| App (local) | http://localhost:5173 |
| API (local) | http://127.0.0.1:5001/api |

Restart Flask after retraining so it loads the new `rf.pkl`.

### Deploy (Render)

See [docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md) — Blueprint in `render.yaml` (API + static site).

**Production:** [https://velo-gg.onrender.com](https://velo-gg.onrender.com)

### Tests

```bash
cd server
python -m pytest tests/ -q
```

---

## API

Base URL: `http://127.0.0.1:5001/api`

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/teams` | All teams (stats + logo paths) |
| `GET` | `/info/<team>` | Single team row |
| `GET` | `/predict/<team1>/<team2>` | Winner %, maps, key factors, confidence |
| `GET` | `/matchup_data/<team1>/<team2>` | Feature row for stat comparison |
| `GET` | `/roster/<team>` | Players and coaches (VLR, cached) |
| `GET` | `/matches/upcoming` | Live + upcoming VCT 2026 matches from VLR |
| `GET` | `/meta` | Comp pool, `model_metrics` |
| `GET` | `/health` | Liveness + whether the model is loaded |

---

## Project structure

```
Velo.gg/
├── client/
│   ├── src/
│   │   ├── pages/              # MakePrediction, PredictionPage, About, Compare
│   │   ├── components/         # Prediction, MapPredictions, TodayMatches, …
│   │   ├── data/mapImages.js
│   │   └── services/api.js
│   └── package.json
├── server/
│   ├── app.py                  # Flask REST API
│   ├── model_training.py       # Elo-anchored training + bundle I/O
│   ├── feature_engineering.py  # Point-in-time match features
│   ├── vlr_ingest.py           # Fetch pro matches + stats from VLR
│   ├── today_matches.py        # Upcoming VCT schedule helper
│   ├── map_predictions.py      # Per-map win probabilities
│   ├── prediction_extras.py    # Confidence, key factors, helpers
│   ├── models/rf.pkl           # Trained match-model bundle
│   ├── scripts/
│   │   ├── update_dataset.py   # Rebuild from Kaggle + retrain
│   │   ├── sync_vlr_data.py    # Pull newer matches from VLR + retrain
│   │   ├── retrain_model.py    # Retrain from existing CSVs
│   │   └── evaluate_model.py   # Refresh model_metrics.json
│   ├── data/
│   │   ├── model_metrics.json
│   │   ├── vlr_player_stats.csv
│   │   └── kaggle/             # Gitignored raw data
│   └── tests/
├── start.bat                   # Windows: API + frontend
└── .github/workflows/
```

---

## Updating data

From `server/`:

```bash
python scripts/update_dataset.py --download   # fetch latest Kaggle zip
python scripts/update_dataset.py              # rebuild CSVs + retrain
python scripts/sync_vlr_data.py               # pull newer pro matches from VLR + retrain
python scripts/retrain_model.py --no-tune     # retrain only (faster)
python scripts/evaluate_model.py              # refresh About-page metrics
```

| Command / flag | Effect |
|----------------|--------|
| `sync_vlr_data.py` | Adds completed VCT/Masters matches from VLR not yet in `scores.csv` |
| `sync_vlr_data.py --no-tune` | Faster retrain |
| `retrain_model.py --no-tune` | Rebuild features + Elo model from local CSVs |
| `update_dataset.py --download` | Fetch Kaggle zip before processing |
| `update_dataset.py --min-year 2024` | Seasons from 2024 onward only |
| `update_dataset.py --all-years` | All seasons including Challengers |

Default: **`--min-year 2021`** with pro-tournament filtering (Champions, Masters, `VCT YYYY:` events).

---

## Tech stack

| Layer | Technologies |
|-------|--------------|
| Frontend | React 19, React Router 7, Vite 7, Recharts |
| Backend | Flask 3, Flask-RESTful, flask-cors |
| ML / data | pandas, scikit-learn, joblib, BeautifulSoup |
| Match data | [VLR API](https://vlr.orlandomm.net/) + vlr.gg |
| Rosters / schedule | [VLR API](https://vlr.orlandomm.net/) |
| Map art | [valorant-api.com](https://valorant-api.com) CDN |

---

## Roadmap

- Fresher map-level stats from VLR for map predictions
- Stronger roster / lineup change signals
- Deeper walk-forward evaluation dashboards
- Optional second-stage models that only run when they beat Elo on holdout

---

## License & credits

- **Product:** Velo.gg
- **License:** [MIT](./LICENSE)
- **Dataset:** MIT (Kaggle)
- **Author:** [maharshinath](https://github.com/maharshinath)
- **Original project:** [terrdv/VCT-Match-Predictor](https://github.com/terrdv/VCT-Match-Predictor)
