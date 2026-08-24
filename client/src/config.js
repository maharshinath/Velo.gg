/** Local Flask in Vite dev; Render API in production unless VITE_API_ORIGIN is set. */
const DEFAULT_ORIGIN = import.meta.env.DEV
  ? 'http://127.0.0.1:5001'
  : 'https://velo-gg-api.onrender.com'

export const API_ORIGIN = (import.meta.env.VITE_API_ORIGIN || DEFAULT_ORIGIN).replace(/\/$/, '')

export const API_BASE = `${API_ORIGIN}/api`

export const DEFAULT_LOGO = `${API_ORIGIN}/static/logos/default-logo.svg`

export function logoUrl(path) {
  if (!path) return DEFAULT_LOGO
  if (/^https?:\/\//i.test(path)) return path
  return path.startsWith('/') ? `${API_ORIGIN}${path}` : `${API_ORIGIN}/${path}`
}
