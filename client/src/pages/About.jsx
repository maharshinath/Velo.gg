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
                <p className="section-eyebrow">About this project</p>
                <h1>About</h1>
            </header>

            <div className="about">
                <p>
                    This app predicts VCT match and map winners using a margin-aware Elo model plus a
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
                {metrics && (
                    <p>
                        Model accuracy — random split: {metrics.random_split_accuracy}%
                        {metrics.time_ordered_split_accuracy != null && (
                            <> · time-ordered (all matches): {metrics.time_ordered_split_accuracy}%</>
                        )}
                        {metrics.international_split_accuracy != null && (
                            <> · international: {metrics.international_split_accuracy}%</>
                        )}
                        . The time-ordered figure is the honest all-match baseline for forecasting.
                    </p>
                )}
            </div>
        </div>
    )
}

export default About
