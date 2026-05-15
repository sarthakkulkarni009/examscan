import axiosInstance from './axiosInstance'

export const submitEvaluation = (data) =>
  axiosInstance.post('/api/evaluations/', data)

export const getEvaluation = (answerSheetId, role = 'assessor') =>
  axiosInstance.get(`/api/evaluations/${answerSheetId}/`, { params: { role } })

export const amendMarks = (evaluationId, data) =>
  axiosInstance.patch(`/api/evaluations/${evaluationId}/amend-marks/`, data)

export const saveDraft = (data) =>
  axiosInstance.patch('/api/evaluations/draft/', data)

export const getPdfStatus = (evaluationId) =>
  axiosInstance.get(`/api/evaluations/${evaluationId}/pdf-status/`)
