import { useEffect, useState } from 'react'
import { getMeta } from '../services/api'
import '../css/Home.css'

/** Fallback when the API is asleep — keep in sync with server/data/model_metrics.json */
const FALLBACK_METRICS = {
  current_holdout_accuracy: 60.1,
  deployed_at_training_holdout_accuracy: 63.2,
  walk_forward_accuracy: 58.7,
  selective_65_accuracy: 69.1,
  selective_65_coverage: 22.2,
  betting_confidence_gate: 65,
  match_count: 1274,
  evaluated_at: '2026-08-28',
}

function fmtPct(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `${Number(value).toFixed(1)}%`
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
  const matchCount = meta?.match_count ?? metrics.match_count ?? 1274
  const teamCount = meta?.team_count ?? 90
  const confidenceGate = metrics.betting_confidence_gate ?? 65

  const statCards = [
    {
      label: 'Current holdout',
      value: fmtPct(currentHoldout),
      hint: 'Deployed model on the latest 20% of pro series',
      primary: true,
    },
    {
      label: `High-confidence picks (≥${confidenceGate}%)`,
      value: fmtPct(metrics.selective_65_accuracy),
      hint: metrics.selective_65_coverage != null
        ? `${metrics.selective_65_coverage}% of recent holdout games`
        : 'Favorites the model is most sure about',
    },
    {
      label: 'At model deployment',
      value: fmtPct(atTraining),
      hint: 'Benchmark when the live model was saved',
    },
    {
      label: 'Walk-forward',
      value: fmtPct(metrics.walk_forward_accuracy),
      hint: 'Rolling out-of-sample check across seasons',
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
          <h2 className="about-section__title">How it works</h2>
          <p>
            Match predictions start with a margin-aware Elo rating built from pro series
            results. A small residual layer (international Elo gap, map-pool strength,
            trusted head-to-head) is only used when it beats pure Elo on holdout — the
            live model includes that blend.
          </p>
          <p>
            Map tabs use historical win rates on the current competitive pool: Abyss,
            Ascent, Haven, Lotus, Split, Summit, and Sunset.
          </p>
        </section>

        <section className="about-section">
          <h2 className="about-section__title">Dataset</h2>
          <p>
            <strong>{matchCount.toLocaleString()}</strong> pro series across{' '}
            <strong>{teamCount}</strong> teams — VCT 2021 through Stage 2 2026, synced
            from{' '}
            <a
              href="https://www.kaggle.com/datasets/ryanluong1/valorant-champion-tour-2021-2023-data"
              target="_blank"
              rel="noopener noreferrer"
            >
              Kaggle
            </a>{' '}
            and refreshed with newer results from VLR.
          </p>
        </section>

        <section className="about-section">
          <h2 className="about-section__title">Model accuracy</h2>
          <p className="about-section__intro">
            Holdout accuracy is measured on the most recent 20% of matches with
            point-in-time features — the same way we gate new model releases.
            {metrics.evaluated_at && (
              <> Last evaluated {metrics.evaluated_at}.</>
            )}
          </p>
          <div className="about-stats" role="list">
            {statCards.map((card) => (
              <article
                key={card.label}
                className={`about-stat${card.primary ? ' about-stat--primary' : ''}`}
                role="listitem"
              >
                <span className="about-stat__label">{card.label}</span>
                <span className="about-stat__value">{card.value}</span>
                <span className="about-stat__hint">{card.hint}</span>
              </article>
            ))}
          </div>
          {atTraining != null && currentHoldout != null && atTraining !== currentHoldout && (
            <p className="about-section__footnote">
              The live model was saved at {fmtPct(atTraining)} holdout; current holdout
              is {fmtPct(currentHoldout)} because recent 2026 matches dominate the test
              window and features are rebuilt as new results arrive.
            </p>
          )}
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
