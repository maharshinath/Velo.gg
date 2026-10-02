import { useEffect, useState } from 'react'
import { getMeta } from '../services/api'
import '../css/Home.css'

/** Fallback when the API is asleep — keep in sync with server/data/model_metrics.json */
const FALLBACK_METRICS = {
  current_holdout_accuracy: 60.9,
  deployed_at_training_holdout_accuracy: 60.9,
  time_ordered_split_accuracy: 60.9,
  walk_forward_accuracy: 59.7,
  vct_regional_split_accuracy: 60.2,
  international_split_accuracy: 63.4,
  selective_65_accuracy: 68.1,
  selective_65_coverage: 34.3,
  selective_65_n: 94,
  betting_confidence_gate: 65,
  brier_score: 0.2316,
  log_loss: 0.6548,
  feature_count: 4,
  match_count: 1397,
  team_count: 89,
  evaluated_at: '2026-10-02',
  international_deployed_accuracy: 57.5,
  international_deployed_n: 461,
  international_deployed_selective_65_accuracy: 65.7,
  international_deployed_selective_65_n: 70,
  international_categories: [
    { label: 'Champions', n: 177, accuracy: 59.3, selective_65_accuracy: 78.6, selective_65_n: 28 },
    { label: 'Masters', n: 180, accuracy: 53.9, selective_65_accuracy: 57.1, selective_65_n: 28 },
    { label: 'Esports World Cup', n: 104, accuracy: 60.6, selective_65_accuracy: 57.1, selective_65_n: 14 },
  ],
  international_events: [
    { label: 'Champions 2026', n: 16, accuracy: 87.5, selective_65_accuracy: 100.0, selective_65_n: 7 },
    { label: 'Esports World Cup 2026', n: 27, accuracy: 70.4, selective_65_accuracy: 83.3, selective_65_n: 6 },
    { label: 'Masters Toronto 2025', n: 24, accuracy: 66.7, selective_65_accuracy: 62.5, selective_65_n: 8 },
    { label: 'Champions 2022', n: 33, accuracy: 60.6, selective_65_accuracy: 66.7, selective_65_n: 3 },
    { label: 'Champions 2021', n: 27, accuracy: 59.3, selective_65_accuracy: 0.0, selective_65_n: 1 },
    { label: 'Masters Berlin (S3)', n: 27, accuracy: 59.3, selective_65_accuracy: null, selective_65_n: 0 },
    { label: 'Champions 2025', n: 34, accuracy: 58.8, selective_65_accuracy: 70.0, selective_65_n: 10 },
    { label: 'Masters Santiago 2026', n: 24, accuracy: 58.3, selective_65_accuracy: 71.4, selective_65_n: 7 },
    { label: 'Champions 2023', n: 33, accuracy: 57.6, selective_65_accuracy: 75.0, selective_65_n: 4 },
    { label: 'Esports World Cup 2025', n: 77, accuracy: 57.1, selective_65_accuracy: 37.5, selective_65_n: 8 },
    { label: 'Masters Reykjavík (S2)', n: 18, accuracy: 55.6, selective_65_accuracy: null, selective_65_n: 0 },
    { label: 'Masters Reykjavík (S1)', n: 24, accuracy: 54.2, selective_65_accuracy: null, selective_65_n: 0 },
    { label: 'Masters Copenhagen (S2)', n: 24, accuracy: 50.0, selective_65_accuracy: null, selective_65_n: 0 },
    { label: 'Champions 2024', n: 34, accuracy: 47.1, selective_65_accuracy: 100.0, selective_65_n: 3 },
    { label: 'Masters London 2026', n: 23, accuracy: 43.5, selective_65_accuracy: 57.1, selective_65_n: 7 },
    { label: 'Masters Bangkok 2025', n: 16, accuracy: 37.5, selective_65_accuracy: 33.3, selective_65_n: 6 },
  ],
}

const FALLBACK_MAP_POOL = [
  'Abyss',
  'Ascent',
  'Haven',
  'Lotus',
  'Split',
  'Summit',
  'Sunset',
]

function fmtPct(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `${Number(value).toFixed(1)}%`
}

function fmtNum(value, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  if (digits > 0) return Number(value).toFixed(digits)
  return Number(value).toLocaleString()
}

function fmtEloSettings(elo) {
  if (elo?.k == null) return 'K=40 · sweep×1.25 · close×0.85'
  return `K=${Number(elo.k)} · sweep×${Number(elo.margin_sweep)} · close×${Number(elo.margin_close)}`
}

function intlRowDetail(row) {
  const series = `${fmtNum(row.n)} series`
  if (row.selective_65_accuracy == null || !row.selective_65_n) {
    return series
  }
  return `${series} · ≥65% ${fmtPct(row.selective_65_accuracy)} (n=${fmtNum(row.selective_65_n)})`
}

function AboutTable({ columns, rows, wide }) {
  return (
    <div className="about-table-wrap">
      <table className={wide ? 'about-table about-table--wide' : 'about-table'}>
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} scope="col">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.metric}>
              <th scope="row">{row.metric}</th>
              {columns.slice(1).map((col) => (
                <td
                  key={col.key}
                  className={
                    col.numeric
                      ? 'about-table__num'
                      : col.note
                        ? 'about-table__note'
                        : undefined
                  }
                >
                  {row[col.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function About() {
  const [meta, setMeta] = useState(null)

  useEffect(() => {
    getMeta().then(setMeta).catch(() => {})
  }, [])

  const metrics = { ...FALLBACK_METRICS, ...(meta?.model_metrics ?? {}) }
  const currentHoldout =
    metrics.current_holdout_accuracy ?? metrics.time_ordered_split_accuracy
  const atTraining =
    metrics.deployed_at_training_holdout_accuracy ??
    metrics.deployed_model_holdout_accuracy
  const matchCount = meta?.match_count ?? metrics.match_count ?? 1397
  const teamCount = meta?.team_count ?? metrics.team_count ?? 89
  const confidenceGate = metrics.betting_confidence_gate ?? 65
  const mapPool = meta?.comp_pool_maps?.length
    ? meta.comp_pool_maps
    : FALLBACK_MAP_POOL
  const holdoutN =
    metrics.selective_65_n != null && metrics.selective_65_coverage != null
      ? Math.round(
          (Number(metrics.selective_65_n) / Number(metrics.selective_65_coverage)) * 100
        )
      : null

  const datasetRows = [
    { metric: 'Pro series (matches)', value: fmtNum(matchCount) },
    { metric: 'Teams', value: fmtNum(teamCount) },
    { metric: 'Seasons covered', value: 'VCT 2021–2026 · Champions Shanghai · EWC 2025–2026' },
    { metric: 'Data sources', value: 'Kaggle base + VLR sync' },
    { metric: 'Feature count (live model)', value: fmtNum(metrics.feature_count) },
    { metric: 'Last metrics eval', value: metrics.evaluated_at ?? '—' },
  ]

  const accuracyRows = [
    {
      metric: 'Current holdout',
      value: fmtPct(currentHoldout),
      detail: holdoutN
        ? `Latest ~20% of series (~${fmtNum(holdoutN)} matches)`
        : 'Latest ~20% of series, point-in-time features',
    },
    {
      metric: 'At model deployment',
      value: fmtPct(atTraining),
      detail: 'Score when the live pickle was saved',
    },
    {
      metric: 'Walk-forward',
      value: fmtPct(metrics.walk_forward_accuracy),
      detail: 'Rolling out-of-sample across seasons',
    },
    {
      metric: 'Regional VCT',
      value: fmtPct(metrics.vct_regional_split_accuracy),
      detail: 'Time-ordered holdout on regional leagues',
    },
    {
      metric: 'International holdout',
      value: fmtPct(metrics.international_split_accuracy),
      detail: 'Time-ordered holdout on international events only',
    },
    {
      metric: `High-confidence (≥${confidenceGate}%)`,
      value: fmtPct(metrics.selective_65_accuracy),
      detail:
        metrics.selective_65_coverage != null
          ? `${Number(metrics.selective_65_coverage).toFixed(1)}% of holdout · n=${fmtNum(metrics.selective_65_n)}`
          : 'Favorites above the confidence gate',
    },
  ]

  const intlAll = {
    n: metrics.international_deployed_n,
    accuracy: metrics.international_deployed_accuracy,
    selective_65_accuracy: metrics.international_deployed_selective_65_accuracy,
    selective_65_n: metrics.international_deployed_selective_65_n,
  }
  const intlCategoryRows = (metrics.international_categories ?? []).map((row) => ({
    metric: row.label,
    value: fmtPct(row.accuracy),
    detail: intlRowDetail(row),
  }))
  const intlEventRows = (metrics.international_events ?? []).map((row) => ({
    metric: row.label,
    value: fmtPct(row.accuracy),
    detail: intlRowDetail(row),
  }))
  const intlSummaryRows = [
    {
      metric: 'All internationals',
      value: fmtPct(intlAll.accuracy),
      detail: intlRowDetail(intlAll),
    },
    ...intlCategoryRows,
  ]

  const calibrationRows = [
    {
      metric: 'Brier score',
      value: fmtNum(metrics.brier_score, 4),
      detail: 'Lower is better — probability calibration',
    },
    {
      metric: 'Log loss',
      value: fmtNum(metrics.log_loss, 4),
      detail: 'Lower is better — probabilistic scoring',
    },
    {
      metric: 'Confidence gate',
      value: fmtPct(confidenceGate),
      detail: 'Used for selective / high-confidence reporting',
    },
  ]

  const modelRows = [
    { metric: 'Live algorithm', value: 'Margin-aware Elo (pure Elo)' },
    {
      metric: 'Residual blend',
      value: 'Gated — only ships if it beats Elo on holdout',
    },
    {
      metric: 'Elo settings',
      value: fmtEloSettings(meta?.elo),
    },
    {
      metric: 'Core signals',
      value: 'Team Elo, win rates, international Elo, map pool, H2H',
    },
    {
      metric: 'Promotion rule',
      value: 'Must beat deployed model on the same holdout by ≥0.5%',
    },
    {
      metric: 'Map predictions',
      value: 'Historical map win rates on the current pool',
    },
    {
      metric: 'Competitive map pool',
      value: mapPool.join(', '),
    },
    {
      metric: 'Betting tab',
      value: 'Experiment / learning only — not financial advice',
    },
  ]

  return (
    <div className="home about-page">
      <header className="text-content about-page__header">
        <p className="section-eyebrow">About Velo.gg</p>
        <h1>About</h1>
        <p className="about-page__lede">
          Margin-aware Elo predictions for VCT — match winners, map breakdowns, and
          confidence-weighted edges when book lines are available.
        </p>
      </header>

      <div className="about about-page__body">
        <section className="about-section">
          <h2 className="about-section__title">Dataset</h2>
          <AboutTable
            columns={[
              { key: 'metric', label: 'Metric' },
              { key: 'value', label: 'Value' },
            ]}
            rows={datasetRows}
          />
          <p className="about-section__footnote">
            Base data from{' '}
            <a
              href="https://www.kaggle.com/datasets/ryanluong1/valorant-champion-tour-2021-2023-data"
              target="_blank"
              rel="noopener noreferrer"
            >
              Kaggle
            </a>
            ; Champions Shanghai 2026 group stage (16 series so far), Stage 2 playoffs, and EWC results synced from VLR.
          </p>
        </section>

        <section className="about-section">
          <h2 className="about-section__title">Model accuracy</h2>
          <AboutTable
            columns={[
              { key: 'metric', label: 'Metric' },
              { key: 'value', label: 'Accuracy', numeric: true },
              { key: 'detail', label: 'Notes', note: true },
            ]}
            rows={accuracyRows}
          />
          <p className="about-section__footnote">
            Holdout uses the most recent 20% of matches with point-in-time features.
          </p>
        </section>

        <section className="about-section">
          <h2 className="about-section__title">Internationals</h2>
          <AboutTable
            wide
            columns={[
              { key: 'metric', label: 'Slice' },
              { key: 'value', label: 'Accuracy', numeric: true },
              { key: 'detail', label: 'Notes', note: true },
            ]}
            rows={intlSummaryRows}
          />
          <AboutTable
            wide
            columns={[
              { key: 'metric', label: 'Event' },
              { key: 'value', label: 'Accuracy', numeric: true },
              { key: 'detail', label: 'Notes', note: true },
            ]}
            rows={intlEventRows}
          />
          <p className="about-section__footnote">
            Live pickle on every series in that event, including matches used in
            training. The holdout figure above is the stricter time-ordered split.
          </p>
        </section>

        <section className="about-section">
          <h2 className="about-section__title">Calibration</h2>
          <AboutTable
            columns={[
              { key: 'metric', label: 'Metric' },
              { key: 'value', label: 'Value', numeric: true },
              { key: 'detail', label: 'Notes', note: true },
            ]}
            rows={calibrationRows}
          />
        </section>

        <section className="about-section">
          <h2 className="about-section__title">Model & product</h2>
          <AboutTable
            columns={[
              { key: 'metric', label: 'Item' },
              { key: 'value', label: 'Detail' },
            ]}
            rows={modelRows}
          />
        </section>

        <section className="about-section about-section--compact">
          <h2 className="about-section__title">Links</h2>
          <ul className="about-links">
            <li>
              <a href="https://velo-gg.onrender.com" target="_blank" rel="noopener noreferrer">
                velo-gg.onrender.com
              </a>
            </li>
            <li>
              <a href="https://github.com/maharshinath/Velo.gg" target="_blank" rel="noopener noreferrer">
                Source on GitHub
              </a>
            </li>
          </ul>
        </section>
      </div>
    </div>
  )
}

export default About
