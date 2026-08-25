import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getTeamData, getPrediction, getRoster, getMatchupData, getMatchOdds } from '../services/api'
import Prediction from '../components/Prediction'
import '../css/PredictionPage.css'


function PredictionPage() {
    const { team1, team2 } = useParams()
    const navigate = useNavigate()
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [team1Data, setTeam1Data] = useState(null)
    const [team2Data, setTeam2Data] = useState(null)
    const [predictionResult, setPredictionResult] = useState(null)
    const [team1Roster, setTeam1Roster] = useState(null)
    const [team2Roster, setTeam2Roster] = useState(null)
    const [matchupData, setMatchupData] = useState(null)
    const [rosterLoading, setRosterLoading] = useState(false)
    const [rosterError, setRosterError] = useState(null)
    const [oddsLoading, setOddsLoading] = useState(false)

    useEffect(() => {
        let cancelled = false

        const fetchData = async () => {
            setLoading(true)
            setError(null)
            setPredictionResult(null)
            setTeam1Data(null)
            setTeam2Data(null)
            setTeam1Roster(null)
            setTeam2Roster(null)
            setMatchupData(null)
            setRosterLoading(false)
            setRosterError(null)
            setOddsLoading(false)

            const t1 = decodeURIComponent(team1 || '')
            const t2 = decodeURIComponent(team2 || '')

            if (!t1 || !t2 || t1 === t2) {
                setError('Please select two different teams.')
                setLoading(false)
                return
            }

            try {
                const prediction = await getPrediction(t1, t2)
                if (cancelled) return
                setPredictionResult(prediction)
                setOddsLoading(true)
                getMatchOdds(t1, t2)
                    .then((oddsPayload) => {
                        if (cancelled || !oddsPayload?.betting) return
                        setPredictionResult((prev) =>
                            prev ? { ...prev, betting: oddsPayload.betting, odds: oddsPayload.odds } : prev
                        )
                    })
                    .catch((err) => console.error(err))
                    .finally(() => {
                        if (!cancelled) setOddsLoading(false)
                    })

                const [t1Rows, t2Rows] = await Promise.all([
                    getTeamData(t1),
                    getTeamData(t2),
                ])
                if (cancelled) return
                setTeam1Data(t1Rows[0] ?? null)
                setTeam2Data(t2Rows[0] ?? null)

                const matchupResult = await getMatchupData(t1, t2)
                if (cancelled) return
                setMatchupData(matchupResult)
            } catch (err) {
                if (!cancelled) {
                    console.error(err)
                    setError(
                        'Could not load this matchup. Make sure the API is running.'
                    )
                }
            } finally {
                if (!cancelled) setLoading(false)
            }
        }

        fetchData()
        return () => { cancelled = true }
    }, [team1, team2])

    const loadRosters = useCallback(async () => {
        if (team1Roster && team2Roster) return

        const t1 = decodeURIComponent(team1 || '')
        const t2 = decodeURIComponent(team2 || '')
        setRosterLoading(true)
        setRosterError(null)

        try {
            const [r1, r2] = await Promise.allSettled([
                getRoster(t1),
                getRoster(t2),
            ])
            if (r1.status === 'fulfilled') setTeam1Roster(r1.value)
            if (r2.status === 'fulfilled') setTeam2Roster(r2.value)
            if (r1.status === 'rejected' && r2.status === 'rejected') {
                setRosterError('Could not load rosters.')
            }
        } catch (err) {
            console.error(err)
            setRosterError('Could not load rosters.')
        } finally {
            setRosterLoading(false)
        }
    }, [team1, team2, team1Roster, team2Roster])

    if (loading) {
        return (
            <div className="prediction-page predicting">
                <div className="predicting-loader surface">
                    <div className="predicting-spinner" />
                    <p className="predicting-title">Running prediction</p>
                    <p className="predicting-matchup">
                        {decodeURIComponent(team1 || '')} vs {decodeURIComponent(team2 || '')}
                    </p>
                </div>
            </div>
        )
    }

    if (error || !predictionResult || !team1Data || !team2Data) {
        return (
            <div className="prediction-page prediction-error">
                <div className="surface prediction-error-card">
                    <p className="error-message">{error || 'Prediction data is unavailable for these teams.'}</p>
                    <button type="button" className="btn-primary" onClick={() => navigate('/')}>
                        Back to team selection
                    </button>
                </div>
            </div>
        )
    }

    return (
        <div className="prediction-page results-ready">
            <section className="page-section" aria-label="Prediction">
                <Prediction
                    result={predictionResult}
                    team1={team1Data}
                    team2={team2Data}
                    matchupData={matchupData}
                    team1Roster={team1Roster}
                    team2Roster={team2Roster}
                    rosterLoading={rosterLoading}
                    rosterError={rosterError}
                    oddsLoading={oddsLoading}
                    onRosterTabOpen={loadRosters}
                />
            </section>

            <footer className="prediction-actions">
                <button type="button" className="btn-ghost" onClick={() => navigate('/')}>
                    ← New prediction
                </button>
            </footer>
        </div>
    )
}

export default PredictionPage
