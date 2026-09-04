import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getUpcomingMatches } from '../services/api'
import '../css/TodayMatches.css'

function scoreLine(team) {
  if (team?.score == null || team.score === '') return null
  return team.score
}

function TodayMatches() {
  const [payload, setPayload] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const data = await getUpcomingMatches()
        if (!cancelled) {
          setPayload(data)
          setError(null)
        }
      } catch (err) {
        console.error(err)
        if (!cancelled) setError("Couldn't load upcoming VCT matches.")
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    const timer = window.setInterval(load, 90_000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  const matches = payload?.matches || []
  const live = matches.filter((m) => m.bucket === 'live')
  const upcoming = matches.filter((m) => m.bucket === 'upcoming')

  return (
    <section className="today-matches" aria-label="Upcoming VCT Games">
      <header className="today-matches__header">
        <h2>Upcoming VCT Games</h2>
        <p>Live and upcoming matches from VLR</p>
      </header>

      {loading && <p className="today-matches__msg">Loading matches…</p>}
      {error && <p className="today-matches__msg today-matches__msg--error">{error}</p>}
      {!loading && !error && matches.length === 0 && (
        <p className="today-matches__msg">No upcoming VCT matches found right now.</p>
      )}

      {!loading && live.length > 0 && <MatchGroup title="Live" matches={live} />}
      {!loading && upcoming.length > 0 && (
        <MatchGroup title="Upcoming" matches={upcoming} />
      )}
    </section>
  )
}

function formatWhen(match) {
  if (match.bucket === 'live') return 'LIVE'
  if (!match.utc) return match.status || ''
  try {
    const d = new Date(match.utc)
    return d.toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    })
  } catch {
    return match.status || ''
  }
}

function MatchGroup({ title, matches }) {
  return (
    <div className="today-group">
      <h3>{title}</h3>
      <ul className="today-list">
        {matches.map((m) => {
          const s1 = scoreLine(m.team1)
          const s2 = scoreLine(m.team2)
          const hasScore = s1 != null && s2 != null
          return (
            <li
              key={m.id || `${m.team1.name}-${m.team2.name}-${m.utc}`}
              className="today-card"
            >
              <div className="today-card__meta">
                <span className={`today-pill today-pill--${m.bucket}`}>
                  {formatWhen(m)}
                </span>
                <span className="today-event">
                  {m.tournament}
                  {m.event ? ` · ${m.event}` : ''}
                </span>
              </div>

              <div className="today-card__teams">
                <span className={`today-team${m.team1.won ? ' is-winner' : ''}`}>
                  {m.team1.logo && (
                    <img src={m.team1.logo} alt="" className="today-logo" />
                  )}
                  <span className="today-team-name">{m.team1.name}</span>
                </span>

                <span className="today-score">
                  {hasScore ? (
                    <>
                      <strong>{s1}</strong>
                      <span>:</span>
                      <strong>{s2}</strong>
                    </>
                  ) : (
                    <span className="today-vs">vs</span>
                  )}
                </span>

                <span
                  className={`today-team today-team--right${m.team2.won ? ' is-winner' : ''}`}
                >
                  <span className="today-team-name">{m.team2.name}</span>
                  {m.team2.logo && (
                    <img src={m.team2.logo} alt="" className="today-logo" />
                  )}
                </span>
              </div>

              <div className="today-card__actions">
                {m.predictable ? (
                  <Link
                    className="today-predict"
                    to={`/predict/${encodeURIComponent(m.team1.name)}/${encodeURIComponent(m.team2.name)}`}
                  >
                    Predict
                  </Link>
                ) : (
                  <span className="today-predict is-disabled">Predict unavailable</span>
                )}
                {m.url && (
                  <a
                    className="today-vlr"
                    href={m.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    VLR
                  </a>
                )}
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export default TodayMatches
