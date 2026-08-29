import { useEffect, useState } from 'react'
import MapPredictions from './MapPredictions'
import TeamRoster from './TeamRoster'
import TeamStatsDashboard from './TeamDashboard'
import { logoUrl, DEFAULT_LOGO } from '../config'
import '../css/Prediction.css'

const TABS = [
  { id: 'maps', label: 'Map Predictions' },
  { id: 'stats', label: 'Stats' },
  { id: 'winner', label: 'Breakdown' },
  { id: 'betting', label: 'Betting' },
  { id: 'roster', label: 'Roaster' },
]

function plainRecTitle(rec, tipTeam) {
  if (rec === 'bet' && tipTeam) return `Worth a look on ${tipTeam}`
  if (rec === 'lean' && tipTeam) return `Slight lean: ${tipTeam}`
  return 'Skip this one'
}

function plainRecReason(betting, hasOdds) {
  const tip = betting.tip_team || betting.favored_team
  if (!hasOdds) {
    return 'We need book prices to check if our win chance is better than the site’s.'
  }
  if (betting.recommendation === 'bet' && tip) {
    const ours = betting.tip_model_pct
    const books = betting.tip_book_pct
    if (ours != null && books != null) {
      return `We give ${tip} about ${ours}% — books price them closer to ${books}%. That gap is the value.`
    }
    return `Our win chance for ${tip} is higher than what the book prices imply.`
  }
  if (tip && betting.tip_model_pct != null && betting.tip_book_pct != null) {
    return `No clear value — for ${tip} we have ~${betting.tip_model_pct}% vs books ~${betting.tip_book_pct}%.`
  }
  return 'Book prices already look in line with (or better than) our estimates.'
}

function BettingInsightsPanel({ team1, team2, betting, oddsLoading }) {
  const riskDisclaimer = (
    <p className="prediction-disclaimer betting-disclaimer">
      This betting tab is for experimentation and for fun — learning statistics and
      mathematics, not for making money. It is not financial advice. Betting is risky;
      you can lose money. I am not responsible for any losses.
    </p>
  )

  if (oddsLoading && !betting?.odds_available) {
    return (
      <div className="betting-insights">
        <p className="tab-panel-message">Looking up book prices on VLR…</p>
        {riskDisclaimer}
      </div>
    )
  }
  if (!betting) {
    return (
      <div className="betting-insights">
        <p className="tab-panel-message">
          Betting info isn't available for this matchup.
        </p>
        {riskDisclaimer}
      </div>
    )
  }

  const rec = betting.recommendation || 'pass'
  const hasOdds = Boolean(betting.odds_available)
  const bookies = Array.isArray(betting.bookies) ? betting.bookies : []
  const tipTeam = betting.tip_team || betting.favored_team
  const team1Pct = ((betting.model_prob_team1 ?? 0) * 100).toFixed(0)
  const team2Pct = ((betting.model_prob_team2 ?? 0) * 100).toFixed(0)
  const book1Pct =
    betting.implied_prob_team1 != null
      ? Number(betting.implied_prob_team1).toFixed(0)
      : null
  const book2Pct =
    betting.implied_prob_team2 != null
      ? Number(betting.implied_prob_team2).toFixed(0)
      : null

  return (
    <div className="betting-insights">
      <div className={`betting-rec betting-rec--${rec}`}>
        <strong className="betting-rec-label">
          {plainRecTitle(rec, tipTeam)}
        </strong>
        <p className="betting-rec-reason">{plainRecReason(betting, hasOdds)}</p>
      </div>

      <div className="betting-simple-row">
        <div className="betting-simple-block">
          <span className="betting-simple-label">
            {hasOdds ? 'Book win chance' : 'Book prices'}
          </span>
          {hasOdds && book1Pct != null && book2Pct != null ? (
            <>
              <p>
                {team1.Team} <strong>{book1Pct}%</strong>
                <span className="betting-sub"> (price {Number(betting.team1_odds).toFixed(2)})</span>
              </p>
              <p>
                {team2.Team} <strong>{book2Pct}%</strong>
                <span className="betting-sub"> (price {Number(betting.team2_odds).toFixed(2)})</span>
              </p>
              <p className="betting-sub">
                Compare our % to the book %. Higher on our side = possible value
                {betting.bookie_count > 1 ? ` · avg of ${betting.bookie_count} sites` : ''}
              </p>
            </>
          ) : (
            <p className="betting-sub">No prices found on VLR for this match right now.</p>
          )}
        </div>

        <div className="betting-simple-block">
          <span className="betting-simple-label">Our win chance</span>
          <p>
            {team1.Team} <strong>{team1Pct}%</strong>
          </p>
          <p>
            {team2.Team} <strong>{team2Pct}%</strong>
          </p>
        </div>
      </div>

      {bookies.length > 0 && (
        <div className="betting-books">
          <h4>Prices by site</h4>
          <ul className="betting-books-list">
            {bookies.map((b) => (
              <li key={`${b.bookie}-${b.team1_odds}-${b.team2_odds}`}>
                <span className="betting-book-name">{b.bookie}</span>
                <span>
                  {team1.Team} {Number(b.team1_odds).toFixed(2)} · {team2.Team}{' '}
                  {Number(b.team2_odds).toFixed(2)}
                </span>
              </li>
            ))}
          </ul>
          {betting.source_url && (
            <a
              className="betting-source"
              href={betting.source_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Check on VLR.gg
            </a>
          )}
        </div>
      )}

      {riskDisclaimer}
    </div>
  )
}

function Prediction({
  team1,
  team2,
  result,
  matchupData,
  team1Roster,
  team2Roster,
  rosterLoading,
  rosterError,
  oddsLoading,
  onRosterTabOpen,
}) {
  const [phase, setPhase] = useState('idle') // idle | lock | reveal
  const [activeTab, setActiveTab] = useState('winner')

  useEffect(() => {
    setPhase('idle')
    let lock
    let reveal
    // Double-rAF so the browser paints idle before lock/reveal classes apply
    const raf = requestAnimationFrame(() => {
      lock = window.setTimeout(() => setPhase('lock'), 80)
      reveal = window.setTimeout(() => setPhase('reveal'), 1100)
    })
    return () => {
      cancelAnimationFrame(raf)
      window.clearTimeout(lock)
      window.clearTimeout(reveal)
    }
  }, [result, team1?.Team, team2?.Team])

  useEffect(() => {
    setActiveTab('winner')
  }, [result, team1?.Team, team2?.Team])

  const selectTab = (tabId) => {
    setActiveTab(tabId)
    if (tabId === 'roster') onRosterTabOpen?.()
  }

  if (!team1 || !team2 || !result) return null

  const team1Wins =
    result.team1_win_prediction ??
    (Number(result.team1_win_probability) >= Number(result.team2_win_probability))
  const winner = team1Wins ? team1 : team2
  const confidence = result.confidence
  const winnerProb = team1Wins ? result.team1_win_probability : result.team2_win_probability
  const revealed = phase === 'reveal'

  const winnerFx = (
    <>
      <div className="matchup-winner-glow" aria-hidden="true" />
      <div className="matchup-winner-shimmer" aria-hidden="true" />
      <div className="matchup-shockwave" aria-hidden="true" />
      <div className="matchup-sparks" aria-hidden="true">
        {Array.from({ length: 14 }, (_, i) => (
          <span key={i} className="matchup-spark" style={{ '--i': i }} />
        ))}
      </div>
      <span className="matchup-pick-label">Predicted</span>
    </>
  )

  return (
    <div
      key={`${team1.Team}-${team2.Team}-${winner.Team}-${winnerProb}`}
      className={`prediction-container is-phase-${phase}`}
    >
      <div className="winner-callout" aria-live="polite">
        {phase === 'lock' && <span className="winner-callout__lock">Calling it…</span>}
        {phase === 'reveal' && (
          <span className="winner-callout__reveal">
            <strong>{winner.Team}</strong>
            <em>predicted winner</em>
          </span>
        )}
      </div>
      {revealed && (
        <>
          <div className="winner-celebration-burst" aria-hidden="true" />
          <div className="winner-flash" aria-hidden="true" />
        </>
      )}
      <div className="prediction-header">
        <h3>Match winner prediction</h3>
        {confidence && (
          <span className={`confidence-badge confidence-${confidence.level}`}>
            {confidence.label}
          </span>
        )}
      </div>

      <div className={`prediction-teams-strip is-phase-${phase}`}>
        <div className="matchup-stage">
          <article
            className={`matchup-slot${team1Wins ? ' matchup-slot--winner' : ' matchup-slot--loser'}`}
          >
            {team1Wins && winnerFx}
            <div className="matchup-slot-content">
              <div className="matchup-logo-wrap">
                <img
                  src={logoUrl(team1['Image Path'])}
                  alt={team1.Team}
                  className="matchup-logo"
                  onError={(e) => { e.currentTarget.src = DEFAULT_LOGO }}
                />
              </div>
              <div className="matchup-meta">
                <span className="matchup-name">{team1.Team}</span>
                {team1.Region && <span className="matchup-region">{team1.Region}</span>}
              </div>
            </div>
          </article>

          <div className="matchup-center">
            <span className="matchup-vs">VS</span>
            <span
              className={`matchup-pointer${team1Wins ? ' matchup-pointer--left' : ' matchup-pointer--right'}`}
              aria-hidden="true"
            />
          </div>

          <article
            className={`matchup-slot${!team1Wins ? ' matchup-slot--winner' : ' matchup-slot--loser'}`}
          >
            {!team1Wins && winnerFx}
            <div className="matchup-slot-content">
              <div className="matchup-logo-wrap">
                <img
                  src={logoUrl(team2['Image Path'])}
                  alt={team2.Team}
                  className="matchup-logo"
                  onError={(e) => { e.currentTarget.src = DEFAULT_LOGO }}
                />
              </div>
              <div className="matchup-meta">
                <span className="matchup-name">{team2.Team}</span>
                {team2.Region && <span className="matchup-region">{team2.Region}</span>}
              </div>
            </div>
          </article>
        </div>
      </div>

      <div className="prediction-tabs-footer">
        <div className="prediction-tabs" role="tablist" aria-label="Prediction details">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`tab-${tab.id}`}
              aria-selected={activeTab === tab.id}
              aria-controls={`panel-${tab.id}`}
              className={`prediction-tab${activeTab === tab.id ? ' is-active' : ''}`}
              onClick={() => selectTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab && (
          <div
            className="prediction-tab-panel"
            role="tabpanel"
            id={`panel-${activeTab}`}
            aria-labelledby={`tab-${activeTab}`}
          >
            {activeTab === 'winner' && (
              <div className="prediction-content prediction-tab-winner">
                <div className="prediction-result glass">
                  <div className={`winner-announcement${revealed ? ' is-live' : ''}`}>
                    <span className="predicted-text">Predicted winner</span>
                    <div className="winner-announcement-logo-wrap">
                      <img
                        className="winner-announcement-logo"
                        src={logoUrl(winner['Image Path'])}
                        alt=""
                        onError={(e) => { e.currentTarget.src = DEFAULT_LOGO }}
                      />
                    </div>
                    <span className="winner-name">{winner.Team}</span>
                    {winnerProb != null && (
                      <span className="winner-chance-badge">{winnerProb}% win chance</span>
                    )}
                    {result.team1_win_probability != null && (
                      <span className="match-win-chance">
                        {team1.Team} {result.team1_win_probability}% · {team2.Team}{' '}
                        {result.team2_win_probability}%
                      </span>
                    )}
                  </div>

                  {result.key_factors?.length > 0 && (
                    <div className="key-factors">
                      <h4>Why {winner.Team} is favored</h4>
                      <ul>
                        {result.key_factors.map((f) => (
                          <li key={f.label}>
                            <strong>{f.label}:</strong> {f.detail}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <p className="prediction-disclaimer">
                    Estimates from historical VCT data. Not betting odds; does not account for
                    live roster changes or map veto order.
                  </p>
                </div>
              </div>
            )}

            {activeTab === 'roster' && (
              <>
                {rosterLoading && <p className="tab-panel-message">Loading rosters…</p>}
                {rosterError && <p className="tab-panel-error">{rosterError}</p>}
                {!rosterLoading && !rosterError && (
                  <div className="rosters-panel">
                    <TeamRoster teamName={team1.Team} roster={team1Roster} playersOnly />
                    <TeamRoster teamName={team2.Team} roster={team2Roster} playersOnly />
                  </div>
                )}
              </>
            )}

            {activeTab === 'maps' && (
              <MapPredictions
                team1={team1}
                team2={team2}
                mapPredictions={result.map_predictions}
                embedded
              />
            )}

            {activeTab === 'betting' && (
              <BettingInsightsPanel
                team1={team1}
                team2={team2}
                betting={result.betting}
                oddsLoading={oddsLoading}
              />
            )}

            {activeTab === 'stats' && matchupData && (
              <TeamStatsDashboard
                team1={team1}
                team2={team2}
                matchupData={matchupData}
                embedded
              />
            )}

            {activeTab === 'stats' && !matchupData && (
              <p className="tab-panel-message">Stats unavailable for this matchup.</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default Prediction
