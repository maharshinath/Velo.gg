# Client (React + Vite)

Frontend for **Velo.gg**. Full pipeline, model, and API docs live in the root [README](../README.md).

| Snapshot (Aug 2026) | |
|---|---|
| Dataset | **1,269** pro series · **90** teams · 2021–2026 |
| Match model | Elo + series-margin K, gated sparse residual (**11** features when it ships) |
| Honest holdout | **63.2%** time-ordered · **71.4%** when confidence ≥ 65% (~20% of games) |
| App | http://localhost:5173 |
| API | http://127.0.0.1:5001/api |

The About page loads accuracy live from `GET /api/meta` (`server/data/model_metrics.json`). Restart Flask after a retrain so `rf.pkl` and metrics stay in sync.

## Run

```bash
npm install
npm run dev
```

Needs the Flask API on port **5001** (see root README or `start.bat` / `start-frontend.bat`).

## Screens

- **Home** — team pickers, upcoming VCT 2026 matches from VLR, Predict links
- **Prediction** — winner %, maps, H2H, key factors, optional betting edge vs VLR odds
- **About** — live model metrics
- **Compare** — side-by-side team stats

Shareable URLs: `/predict/Sentinels/FNATIC` (names are URL-encoded).
