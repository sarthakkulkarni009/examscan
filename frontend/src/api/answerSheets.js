import axiosInstance from './axiosInstance'
import { API_BASE_URL } from './config'

export const getAnswerSheets = (params) =>
  axiosInstance.get('/api/answer-sheets/', { params })

export const uploadImage = (formData) =>
  axiosInstance.post('/api/answer-sheets/upload-image/', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })

export const deleteImage = (id) =>
  axiosInstance.delete(`/api/answer-sheets/upload-image/${id}/`)

export const finalizeSheet = (data) =>
  axiosInstance.post('/api/answer-sheets/finalize/', data)

export const assignSheet = (id, data) =>
  axiosInstance.patch(`/api/answer-sheets/${id}/assign/`, data)

export const bulkAssignSheets = (data) =>
  axiosInstance.patch('/api/answer-sheets/bulk-assign/', data)

export const flagSheet = (id, data) =>
  axiosInstance.patch(`/api/answer-sheets/${id}/flag/`, data)

export const getSheetPdfUrl = (id) =>
  `${API_BASE_URL}/api/answer-sheets/${id}/pdf/`
