## Performance

Latency is measured locally with repeated HTTP requests against the Flask API on `127.0.0.1:5001` (model already loaded). Predict timings use `?odds=0` so VLR odds scraping is not in the path.

### August 24, 2026 (current)

Warm cache, **80** requests per endpoint, Sentinels vs FNATIC. Dataset **1,269** matches; deployed model is Elo + gated residual (`rf.pkl`).

| Endpoint | Avg | p95 | p99 |
|--------|-----|-----|------|
| GET /api/health | 11.1 ms | 24.8 ms | 26.0 ms |
| GET /api/info/\<team\> | 13.4 ms | 27.0 ms | 27.7 ms |
| GET /api/matchup_data | 25.5 ms | 33.4 ms | 34.4 ms |
| GET /api/predict (`odds=0`) | 55.1 ms | 69.4 ms | 83.4 ms |
| GET /api/meta | 11.5 ms | 25.2 ms | 26.9 ms |

`/api/predict` without `odds=0` is slower and noisier (live VLR scrape). Upcoming matches (`/api/matches/upcoming`) depends on VLR and is not a local CPU benchmark.

---

### History

January 19th (100 requests on localhost):

| Endpoint | Avg | p95 | p99 |
|--------|-----|-----|------|
| GET /api/info/\<team\> | 22 ms | 42 ms | 79 ms |
| GET /api/matchup_data | 23 ms | 23 ms | 26 ms |
| GET /api/predict | 44 ms | 52 ms | 71 ms |

Jan 23: Added a global predictor object (load model once) — large drop vs cold per-request loads.

| Endpoint | Avg | p95 | p99 |
|--------|-----|-----|------|
| GET /api/info/\<team\> | 2.9 ms | 5.2 ms | 7.8 ms |
| GET /api/matchup_data | 5.7 ms | 7.6 ms | 8.6 ms |
| GET /api/predict | 8.9 ms | 9.5 ms | 10 ms |

Later Elo/residual work and a larger CSV (now 1,269 series) raised predict/matchup times vs Jan 23, still well under 100 ms p95 with odds scraping off.
