import { RestClient } from './rest'

/** Shared REST client; '' base URL uses the Vite dev proxy (no CORS). */
export const rest = new RestClient()
