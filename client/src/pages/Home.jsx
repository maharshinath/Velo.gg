import '../css/Home.css'
import {useState, useEffect, useNavigate} from "react"
import { getPrediction, getMatchupData , getTeamData, getTeams} from '../services/api'
import Matchup from '../components/Matchup'
import TeamButton from '../components/TeamButton'
import Prediction from '../components/Prediction'
import TeamStatsDashboard from '../components/TeamDashboard'


function Home() {
    const [match, setMatch] = useState([null, null])
    const [teams, setTeams] = useState([])
    const [error, setError] = useState(null)
    const [loading, setLoading] = useState(true)
    const [predict, setPredict] = useState(false)
    const [matchResult, setResult] = useState(null)
    const [predictionLoading, setPredictionLoading] = useState(false)
    const [matchupData, setMatchupData] = useState(null)

    useEffect(() => {
        const loadTeams = async() => {
            try{
                const allteams = await getTeams();
                setTeams(allteams)
            } catch (err) {
                console.log(err)
                setError("Failed to load teams...")
            } finally {
                setLoading(false)
            }
        }
        loadTeams()
    }, [])

    const handleTeamSelect = (team) => {
        setMatch(prevMatch => {
            const [team1, team2] = prevMatch;
            
            // If no teams selected, add as team1
            if (!team1) {
                return [team, team2];
            }
            // If team1 selected but not team2, add as team2
            else if (!team2) {
                // Prevent selecting the same team twice
                if (team.id === team1.id) {
                    return prevMatch; // Don't update if same team
                }
                return [team1, team];
            }
            // If both teams selected, replace team1 with new selection
            else {
                return [team1, team2]
            }
        });
    };

    const handlePredict = async () => {
        setPredictionLoading(true)
            try {
                const result = await getPrediction(match[0], match[1])
                const matchup = await getMatchupData(match[0], match[1])  // <- fetch matchup data
                setResult(result)
                setMatchupData(matchup)  // <- store it
                setPredict(true)
            } catch (err) {
                console.error('Prediction failed:', err)
                setError('Failed to get prediction')
            } finally {
                setPredictionLoading(false)
            }
    }

    const handleReset = () => {
        setPredict(false)
        setMatch([null,null])
        setResult(null)
    }

    const clearMatch = () => {
        setMatch([null, null]);
    };



    

    return predict ? (
            <>
                <Prediction team1={match[0]} team2={match[1]} result={matchResult} onReset={handleReset} />
                <TeamStatsDashboard team1={match[0]} team2={match[1]} matchupData={matchupData}/>
            </>
            

            
           
        ) : (
            <div className="home">
                <div className="text-content">
                    <h1>Velo</h1>
                    <p>Call VCT matches with a margin-aware Elo model.</p>
                    <Matchup team1={match[0]} team2={match[1]} />
                    <div className="buttons">
                        <button onClick={clearMatch}>Clear Match</button>
                        <button 
                            disabled={!match[0] || !match[1] || predictionLoading} 
                            onClick={handlePredict}
                        >
                            {predictionLoading ? 'Predicting...' : 'Predict'}
                        </button>
                    </div>
                </div>

                {error && <div className="error-message">{error}</div>}

                {loading ? (
                    <div className="loading">Loading...</div>
                ) : (
                    <div className="button-grid glass">
                        {teams.map(team => (
                            <TeamButton 
                                team={team} 
                                key={team.id} 
                                onTeamSelect={handleTeamSelect}
                                isSelected={match[0]?.id === team.id || match[1]?.id === team.id}
                            />
                        ))}
                    </div>
                )}
            </div> 
        );
}

export default Home