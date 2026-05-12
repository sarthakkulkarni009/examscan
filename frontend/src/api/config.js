/**
 * Dynamically resolve API base URL from the browser's hostname.
 *
 * When accessed via localhost   → http://localhost:8000
 * When accessed via 192.168.x.x → http://192.168.x.x:8000
 *
 * The VITE_API_BASE_URL env variable acts as an override if explicitly set.
 */
const API_PORT = 8000

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  `${window.location.protocol}//${window.location.hostname}:${API_PORT}`
