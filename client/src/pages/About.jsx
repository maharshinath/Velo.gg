import { useEffect, useState } from 'react'
import { getMeta } from '../services/api'
import '../css/Home.css'

/** Fallback when the API is asleep — keep in sync with server/data/model_metrics.json */
const FALLBACK_METRICS = {
  current_holdout_accuracy: 60.1,
  deployed_at_training_holdout_accuracy: 63.2,
  walk_forward_accuracy: 59.2,
  vct_regional_split_accuracy: 61.3,
  international_split_accuracy: 64.9,
  selective_65_accuracy: 71.4,
  selective_65_coverage: 19.8,
  betting_confidence_gate: 65,
  match_count: 1274,
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

    return (
        <div className="home about-page">
            <header className="text-content">
                <p className="section-eyebrow">About Velo.gg</p>
                <h1>About</h1>
            </header>

            <div className="about">
                <p>
                    Velo.gg predicts VCT match and map winners with a margin-aware Elo model
                    plus a gated residual (international Elo, map pool, trusted H2H) that only
                    ships when it beats pure Elo on holdout. Map predictions use historical map
                    win rates on the current competitive pool (Abyss, Ascent, Haven, Lotus,
                    Split, Summit, Sunset).
                </p>
                <p>
                    Live app:{' '}
                    <a href="https://velo-gg.onrender.com" target="_blank" rel="noopener noreferrer">
                        https://velo-gg.onrender.com
                    </a>
                </p>
                <p>
                    Dataset:{' '}
                    <a
                        href="https://www.kaggle.com/datasets/ryanluong1/valorant-champion-tour-2021-2023-data"
                        target="_blank"
                        rel="noopener noreferrer"
                    >
                        Valorant Champion Tour 2021–2026 (Kaggle)
                    </a>
                    {' '}plus VLR sync for newer Stage 2 matches.
                </p>
                <p>
                    Current training set: <strong>{matchCount.toLocaleString()}</strong> pro series,{' '}
                    <strong>{teamCount}</strong> teams (VCT 2021–2026, including Stage 2 2026).
                    Refresh with <code>python scripts/sync_vlr_data.py</code> from <code>server/</code>.
                </p>
                <p>
                    Model accuracy — current holdout (deployed model, latest 20% of matches):{' '}
                    <strong>{currentHoldout}%</strong>
                    {atTraining != null && atTraining !== currentHoldout && (
                        <> · at deployment: {atTraining}%</>
                    )}
                    {metrics.walk_forward_accuracy != null && (
                        <> · walk-forward: {metrics.walk_forward_accuracy}%</>
                    )}
                    {metrics.selective_65_accuracy != null && (
                        <>
                            {' '}
                            · selective ≥{metrics.betting_confidence_gate ?? 65}%:{' '}
                            {metrics.selective_65_accuracy}% on {metrics.selective_65_coverage}% of
                            games
                        </>
                    )}
                    {metrics.evaluated_at && <> · evaluated {metrics.evaluated_at}</>}.
                    {' '}Holdout uses refreshed features on recent 2026 matches.
                </p>
            </div>
        </div>
    )
}

export default About
