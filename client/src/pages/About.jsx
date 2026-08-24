import { useEffect, useState } from 'react'
import { getMeta } from '../services/api'
import '../css/Home.css'

function About() {
    const [meta, setMeta] = useState(null)

    useEffect(() => {
        getMeta().then(setMeta).catch(() => {})
    }, [])

    const metrics = meta?.model_metrics

    return (
        <div className="home about-page">
            <header className="text-content">
                <p className="section-eyebrow">About Velo.gg</p>
                <h1>About</h1>
            </header>

            <div className="about">
                <p>
                    Velo.gg predicts VCT match and map winners using a margin-aware Elo model plus a
                    small residual (international Elo, map pool, trusted H2H) trained on
                    pro match outcomes — rolling Elo, recent win rates, and map history.
                    Map predictions cover the current competitive pool plus standard maps (including Summit).
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
                </p>
                <p>
                    Current training set: <strong>1,269</strong> pro series, <strong>90</strong> teams
                    (VCT 2021–2026, including Stage 2 2026). Refresh with{' '}
                    <code>python scripts/sync_vlr_data.py</code> from <code>server/</code>.
                </p>
                {metrics && (
                    <p>
                        Model accuracy — time-ordered holdout:{' '}
                        {metrics.time_ordered_split_accuracy ?? metrics.deployed_model_holdout_accuracy}%
                        {metrics.walk_forward_accuracy != null && (
                            <> · walk-forward: {metrics.walk_forward_accuracy}%</>
                        )}
                        {metrics.vct_regional_split_accuracy != null && (
                            <> · regional: {metrics.vct_regional_split_accuracy}%</>
                        )}
                        {metrics.international_split_accuracy != null && (
                            <> · international: {metrics.international_split_accuracy}%</>
                        )}
                        {metrics.selective_65_accuracy != null && (
                            <>
                                {' '}
                                · selective ≥{metrics.betting_confidence_gate ?? 65}%:{' '}
                                {metrics.selective_65_accuracy}% on {metrics.selective_65_coverage}% of
                                games
                            </>
                        )}
                        . Time-ordered holdout is the honest all-match baseline.
                    </p>
                )}
            </div>
        </div>
    )
}

export default About
