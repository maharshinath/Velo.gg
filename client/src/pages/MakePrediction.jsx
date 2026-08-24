import '../css/Home.css'
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getTeams } from '../services/api'
import Matchup from '../components/Matchup'
import TodayMatches from '../components/TodayMatches'
import '../css/Dropdowns.css'

function MakePrediction() {
    const [teams, setTeams] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [team1, setTeam1] = useState('')
    const [team2, setTeam2] = useState('')
    const navigate = useNavigate()

    useEffect(() => {
        const loadTeams = async () => {
            try {
                const allteams = await getTeams()
                if (!Array.isArray(allteams) || allteams.length === 0) {
                    throw new Error('No teams returned from API')
                }
                setTeams(allteams)
                setError(null)
            } catch (err) {
                console.error(err)
                setError(
                    'Could not load teams. The API may be waking up (Render free) or out of memory. Wait a minute and refresh.'
                )
            } finally {
                setLoading(false)
            }
        }
        loadTeams()
    }, [])

    const clearMatch = () => {
        setTeam1('')
        setTeam2('')
    }

    const handlePredict = () => {
        const t1 = teams[team1]?.Team
        const t2 = teams[team2]?.Team
        if (!t1 || !t2) return
        navigate(`/predict/${encodeURIComponent(t1)}/${encodeURIComponent(t2)}`)
    }

    const handleTeam1Change = (e) => {
        const selectedIndex = e.target.value
        if (selectedIndex === team2) setTeam2('')
        setTeam1(selectedIndex)
    }

    const handleTeam2Change = (e) => {
        const selectedIndex = e.target.value
        if (selectedIndex === team1) setTeam1('')
        setTeam2(selectedIndex)
    }

    return (
        <div className="home make-prediction">
            <header className="text-content">
                <p className="section-eyebrow">Valorant Champions Tour</p>
                <h1>Velo.gg</h1>
                <p className="hero-tagline">Call the match. Elo-backed VCT winner and map breakdowns.</p>
            </header>

            {team1 !== '' && team2 !== '' && (
                <Matchup team1={teams[team1]} team2={teams[team2]} />
            )}

            {error && <p className="error-message" role="alert">{error}</p>}

            <div className="selection-panel">
                <span className="selection-panel__label">Match setup</span>

                {loading ? (
                    <p className="loading-teams">Loading teams…</p>
                ) : (
                    <div className="dropdowns">
                        <div className="dropdown-field">
                            <label htmlFor="team1">Team 1</label>
                            <select id="team1" value={team1} onChange={handleTeam1Change}>
                                <option value="">Choose team</option>
                                {teams.map((team, index) => {
                                    if (index.toString() === team2) return null
                                    return (
                                        <option key={team.id} value={index}>
                                            {team.Team}
                                        </option>
                                    )
                                })}
                            </select>
                        </div>
                        <div className="dropdown-field">
                            <label htmlFor="team2">Team 2</label>
                            <select id="team2" value={team2} onChange={handleTeam2Change}>
                                <option value="">Choose team</option>
                                {teams.map((team, index) => {
                                    if (index.toString() === team1) return null
                                    return (
                                        <option key={team.id} value={index}>
                                            {team.Team}
                                        </option>
                                    )
                                })}
                            </select>
                        </div>
                    </div>
                )}

                <div className="buttons">
                    <button type="button" className="btn-ghost" onClick={clearMatch}>
                        Clear
                    </button>
                    <button
                        type="button"
                        className="btn-primary predict-btn"
                        disabled={team1 === '' || team2 === '' || loading}
                        onClick={handlePredict}
                    >
                        Predict match
                    </button>
                </div>
            </div>

            <TodayMatches />
        </div>
    )
}

export default MakePrediction
