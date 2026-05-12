import axios from 'axios'
import { API_BASE_URL } from './config'

const axiosInstance = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
})

// Request interceptor — attach access token
axiosInstance.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Response interceptor — handle 401 with silent refresh
let isRefreshing = false
let failedQueue = []

const processQueue = (error, token = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error)
    } else {
      prom.resolve(token)
    }
  })
  failedQueue = []
}

axiosInstance.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`
          return axiosInstance(originalRequest)
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const refresh = sessionStorage.getItem('refresh_token')
        if (!refresh) throw new Error('No refresh token')

        const { data } = await axios.post(
          `${API_BASE_URL}/api/auth/refresh/`,
          { refresh }
        )

        sessionStorage.setItem('access_token', data.access)
        if (data.refresh) {
          sessionStorage.setItem('refresh_token', data.refresh)
        }

        processQueue(null, data.access)
        isRefreshing = false

        originalRequest.headers.Authorization = `Bearer ${data.access}`
        return axiosInstance(originalRequest)
      } catch (refreshError) {
        processQueue(refreshError, null)
        isRefreshing = false

        // Clear auth state and redirect
        sessionStorage.clear()
        const role = sessionStorage.getItem('user_role')
        const loginPaths = {
          scanning_staff: '/login/scanning',
          teacher: '/login/teacher',
          exam_dept: '/login/exam-dept',
        }
        window.location.href = loginPaths[role] || '/login/scanning'
        return Promise.reject(refreshError)
      }
    }

    return Promise.reject(error)
  }
)

export default axiosInstance
