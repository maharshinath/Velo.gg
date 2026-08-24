import { API_BASE } from '../config'

const BASE_URL = API_BASE


export const getPrediction = async (team1, team2) => {
    const result = await fetch(
        `${BASE_URL}/predict/${encodeURIComponent(team1)}/${encodeURIComponent(team2)}`
    )
    if (!result.ok) throw new Error('Prediction failed')
    return await result.json()
}


export const getMatchupData = async (team1, team2) => {
    const result = await fetch(
        `${BASE_URL}/matchup_data/${encodeURIComponent(team1)}/${encodeURIComponent(team2)}`
    )
    if (!result.ok) throw new Error('Failed to load matchup data')
    const data = await result.json()
    return Array.isArray(data) ? data[0] : data
}


const parseTeamsPayload = (data) => {
    if (Array.isArray(data)) return data
    if (typeof data === 'string') return JSON.parse(data)
    throw new Error('Unexpected teams response format')
}

export const getTeams = async () => {
    let lastError = null
    for (let attempt = 0; attempt < 4; attempt++) {
        const controller = new AbortController()
        const timer = setTimeout(() => controller.abort(), 45000)
        try {
            const response = await fetch(`${BASE_URL}/teams`, { signal: controller.signal })
            if (!response.ok) throw new Error(`Failed to load teams (${response.status})`)
            return parseTeamsPayload(await response.json())
        } catch (err) {
            lastError = err
            await new Promise((resolve) => setTimeout(resolve, 2500 * (attempt + 1)))
        } finally {
            clearTimeout(timer)
        }
    }
    throw lastError
}


export const getTeamData = async (team) => {
    const response = await fetch(`${BASE_URL}/info/${encodeURIComponent(team)}`)
    if (!response.ok) throw new Error(`Failed to load team (${response.status})`)
    return parseTeamsPayload(await response.json())
}


export const getRoster = async (team) => {
    const response = await fetch(`${BASE_URL}/roster/${encodeURIComponent(team)}`)
    if (!response.ok) throw new Error(`Failed to load roster (${response.status})`)
    return await response.json()
}


export const getMeta = async () => {
    const response = await fetch(`${BASE_URL}/meta`)
    if (!response.ok) throw new Error('Failed to load meta')
    return await response.json()
}


export const getTodayMatches = async () => getUpcomingMatches()

export const getUpcomingMatches = async () => {
    const response = await fetch(`${BASE_URL}/matches/upcoming`)
    if (!response.ok) throw new Error('Failed to load upcoming matches')
    return await response.json()
}
