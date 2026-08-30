import { useEffect, useState } from 'react'
import { getMeta } from '../services/api'
import '../css/Home.css'

/** Fallback when the API is asleep — keep in sync with server/data/model_metrics.json */
const FALLBACK_METRICS = {
  current_holdout_accuracy: 62.7,
  deployed_at_training_holdout_accuracy: 61.4,
  time_ordered_split_accuracy: 62.7,
  walk_forward_accuracy: 58.8,
  vct_regional_split_accuracy: 62.5,
  international_split_accuracy: 62.2,
  selective_65_accuracy: 69.4,
  selective_65_coverage: 28.9,
  selective_65_n: 72,
  betting_confidence_gate: 65,
  brier_score: 0.2328,
  log_loss: 0.6584,
  feature_count: 4,
  match_count: 1282,
  evaluated_at: '2026-08-30',
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

function AboutTable({ columns, rows }) {
  return (
    <div className="about-table-wrap">
      <table className="about-table">
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

  const metrics = meta?.model_metrics ?? FALLBACK_METRICS
  const currentHoldout =
    metrics.current_holdout_accuracy ?? metrics.time_ordered_split_accuracy
  const atTraining =
    metrics.deployed_at_training_holdout_accuracy ??
    metrics.deployed_model_holdout_accuracy
  const matchCount = meta?.match_count ?? metrics.match_count ?? 1282
  const teamCount = meta?.team_count ?? 90
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
    { metric: 'Seasons covered', value: 'VCT 2021 – Stage 2 2026' },
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
      metric: 'International',
      value: fmtPct(metrics.international_split_accuracy),
      detail: 'Time-ordered holdout on international events',
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
      value: 'K=32 · sweep×1.25 · close×0.85',
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
            ; newer Stage 2 results synced from VLR.
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
