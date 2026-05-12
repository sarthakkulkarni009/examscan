import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { getBundles } from '../../api/bundles'
import { assignBundleModeration } from '../../api/moderation'
import axiosInstance from '../../api/axiosInstance'
import LoadingSpinner from '../../components/LoadingSpinner'
import DownloadMarkedPDFsButton from '../../components/DownloadMarkedPDFsButton'

function ExamDashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()

  const [bundles, setBundles] = useState([])
  const [stats, setStats] = useState(null)
  const [teachers, setTeachers] = useState([])
  const [loading, setLoading] = useState(true)

  // Assignment modal state
  const [showAssignModal, setShowAssignModal] = useState(false)
  const [assignBundleId, setAssignBundleId] = useState(null)
  const [selectedAssessor, setSelectedAssessor] = useState('')
  const [selectedModerator, setSelectedModerator] = useState('')
  const [assigning, setAssigning] = useState(false)
  const [assignError, setAssignError] = useState('')

  useEffect(() => {
    fetchData()
  }, [])

  const fetchData = async () => {
    setLoading(true)
    try {
      const [bundlesRes, teachersRes] = await Promise.all([
        getBundles(),
        axiosInstance.get('/api/users/?role=teacher'),
      ])
      const fetchedBundles = bundlesRes.data.results || bundlesRes.data
      setBundles(fetchedBundles)
      const completedBundles = fetchedBundles.filter(b => {
        const total = b.sheets_count || b.total_sheets || 0
        return total > 0 && (b.graded_count || 0) >= total
      })
      setStats({
        total_bundles: fetchedBundles.length,
        unassigned_bundles: fetchedBundles.filter(b => {
          const total = b.sheets_count || b.total_sheets || 0
          const graded = b.graded_count || 0
          return b.assigned_count === 0 && b.status === 'submitted' && (total === 0 || graded < total)
        }).length,
        assigned_bundles: fetchedBundles.filter(b => b.assigned_count > 0).length,
        completed_bundles: completedBundles.length,
        total_sheets: fetchedBundles.reduce((sum, b) => sum + (b.sheets_count || b.total_sheets || 0), 0)
      })
      setTeachers(teachersRes.data.results || teachersRes.data || [])
    } catch (err) {
      console.error("Failed to fetch dashboard data", err)
    } finally {
      setLoading(false)
    }
  }

  const openAssignModal = (bundleId) => {
    setAssignBundleId(bundleId)
    setSelectedAssessor('')
    setSelectedModerator('')
    setAssignError('')
    setShowAssignModal(true)
  }

  const handleAssignBundle = async () => {
    if (!selectedAssessor || !selectedModerator) {
      setAssignError('Please select both an assessor and a moderator.')
      return
    }
    if (selectedAssessor === selectedModerator) {
      setAssignError('Assessor and moderator must be different teachers.')
      return
    }
    setAssigning(true)
    setAssignError('')
    try {
      await assignBundleModeration(assignBundleId, {
        assessor_id: selectedAssessor,
        moderator_id: selectedModerator,
      })
      setShowAssignModal(false)
      fetchData()
    } catch (err) {
      setAssignError(err.response?.data?.error || 'Assignment failed.')
    } finally {
      setAssigning(false)
    }
  }

  const getModerationBadge = (bundle) => {
    const ma = bundle.moderation_assignment
    if (!ma) return null
    if (ma.moderation_passed) {
      return <span className="mod-badge mod-badge-passed">✓ Moderation Passed</span>
    }
    if (ma.moderation_completed && !ma.moderation_passed) {
      return <span className="mod-badge mod-badge-failed">⚠ Correction Needed</span>
    }
    return <span className="mod-badge mod-badge-pending">⏳ Moderation Pending</span>
  }

  return (
    <div className="page-container fade-in">
      <div className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p>Overview of all bundles spanning the examination ecosystem.</p>
        </div>
      </div>

        {/* Stats */}
        {stats && (
          <div className="grid-4" style={{ marginBottom: '2rem' }}>
            <div className="card stat-card">
              <div className="stat-icon" style={{ backgroundColor: 'rgba(99,102,241,0.1)', color: '#4F46E5' }}>📦</div>
              <div className="stat-content">
                <div className="stat-value">{stats.total_bundles || 0}</div>
                <div className="stat-label">Total Bundles</div>
              </div>
            </div>
            <div className="card stat-card">
              <div className="stat-icon" style={{ backgroundColor: 'rgba(245,158,11,0.1)', color: '#F59E0B' }}>⏳</div>
              <div className="stat-content">
                <div className="stat-value">{stats.unassigned_bundles || 0}</div>
                <div className="stat-label">Unassigned Bundles</div>
              </div>
            </div>
            <div className="card stat-card">
              <div className="stat-icon" style={{ backgroundColor: 'rgba(16,185,129,0.1)', color: '#10B981' }}>🧑‍🏫</div>
              <div className="stat-content">
                <div className="stat-value">{stats.assigned_bundles || 0}</div>
                <div className="stat-label">Assigned Bundles</div>
              </div>
            </div>
            <div className="card stat-card">
              <div className="stat-icon" style={{ backgroundColor: 'rgba(99,102,241,0.1)', color: '#4F46E5' }}>📄</div>
              <div className="stat-content">
                <div className="stat-value">{stats.total_sheets || 0}</div>
                <div className="stat-label">Total Answer Sheets</div>
              </div>
            </div>
          </div>
        )}

        {/* Bundles */}
        <div className="card" style={{ padding: 0 }}>
          <div className="card-header flex-between" style={{ padding: '1.5rem', borderBottom: '1px solid var(--border-color)', marginBottom: 0 }}>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 600 }}>Assignment Tracker</h2>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>{bundles.length} tracked</div>
          </div>

          {loading ? (
            <LoadingSpinner message="Loading ecosystem..." />
          ) : (
            <div className="table-container" style={{ border: 'none', borderRadius: 0 }}>
              {bundles.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '4rem 2rem', color: 'var(--text-muted)' }}>
                  <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>📦</div>
                  <h3 style={{ color: 'var(--text-primary)', marginBottom: '0.5rem' }}>No bundles tracked yet</h3>
                  <p>Bundles appear here once scanning staff fully finalize their capture sessions.</p>
                </div>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Bundle #</th>
                      <th>Subject</th>
                      <th>Status</th>
                      <th>Created</th>
                      <th style={{ width: '300px' }}>Assignment</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bundles.map((bundle) => (
                      <tr key={bundle.id}>
                        <td style={{ fontWeight: 500 }}>#{bundle.bundle_number}</td>
                        <td>
                          <div style={{ fontWeight: 500 }}>{bundle.subject_name || 'Subject'}</div>
                          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{bundle.subject_code || 'CODE'}</div>
                        </td>
                        <td>
                          {(() => {
                            const total = bundle.sheets_count || bundle.total_sheets || 0
                            const graded = bundle.graded_count || 0
                            const isFullyGraded = total > 0 && graded >= total
                            if (isFullyGraded) {
                              return <span className="badge badge-completed">Completed</span>
                            }
                            return <span className={`badge badge-${bundle.status}`}>{bundle.status}</span>
                          })()}
                        </td>
                        <td>{new Date(bundle.created_at || Date.now()).toLocaleDateString()}</td>
                        <td>
                          {(() => {
                            const total = bundle.sheets_count || bundle.total_sheets || 0
                            const graded = bundle.graded_count || 0
                            const isFullyGraded = total > 0 && graded >= total

                            if (isFullyGraded && !bundle.moderation_assignment) {
                              // Already fully graded (legacy) — show completed
                              return (
                                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                  <span style={{ color: 'var(--color-success)', fontWeight: 600, fontSize: '0.9rem' }}>✓ Completed</span>
                                  <DownloadMarkedPDFsButton bundleId={bundle.id} completedCount={graded} />
                                </div>
                              )
                            }

                            if (bundle.moderation_assignment) {
                              return (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                                    {getModerationBadge(bundle)}
                                    <DownloadMarkedPDFsButton bundleId={bundle.id} completedCount={graded} />
                                  </div>
                                  <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                                    <span>📝 {bundle.moderation_assignment.assessor_name}</span>
                                    <span style={{ margin: '0 0.4rem' }}>·</span>
                                    <span>🔍 {bundle.moderation_assignment.moderator_name}</span>
                                  </div>
                                </div>
                              )
                            }

                            if (bundle.status === 'submitted' && bundle.assigned_count > 0) {
                              // Legacy assigned but not fully graded
                              return (
                                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                  <span style={{ color: 'var(--color-secondary)', fontWeight: 600, fontSize: '0.9rem' }}>✓ Assigned (legacy)</span>
                                  <DownloadMarkedPDFsButton bundleId={bundle.id} completedCount={graded} />
                                </div>
                              )
                            }

                            if (bundle.status === 'submitted' && bundle.assigned_count === 0) {
                              return (
                                <button className="btn btn-secondary btn-sm" onClick={() => openAssignModal(bundle.id)}>
                                  + Assign Bundle
                                </button>
                              )
                            }

                            return <span style={{ color: 'var(--text-muted)', fontSize: '0.9rem', textTransform: 'capitalize' }}>{bundle.status}</span>
                          })()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>

      {/* Assignment Modal */}
      {showAssignModal && (
        <div className="modal-backdrop" onClick={() => setShowAssignModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '480px' }}>
            <div className="modal-header">
              <h2>Assign Bundle</h2>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowAssignModal(false)}>✕</button>
            </div>
            <div style={{ padding: '1.5rem' }}>
              <div className="form-group">
                <label className="form-label">Assessor</label>
                <select
                  className="form-select"
                  value={selectedAssessor}
                  onChange={(e) => setSelectedAssessor(e.target.value)}
                >
                  <option value="">-- Select Assessor --</option>
                  {teachers.map(t => (
                    <option key={t.id} value={t.id} disabled={t.id === selectedModerator}>
                      {t.full_name} ({t.username})
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Moderator</label>
                <select
                  className="form-select"
                  value={selectedModerator}
                  onChange={(e) => setSelectedModerator(e.target.value)}
                >
                  <option value="">-- Select Moderator --</option>
                  {teachers.map(t => (
                    <option key={t.id} value={t.id} disabled={t.id === selectedAssessor}>
                      {t.full_name} ({t.username})
                    </option>
                  ))}
                </select>
              </div>
              <div style={{
                padding: '0.75rem 1rem', background: 'rgba(99,102,241,0.06)',
                border: '1px solid rgba(99,102,241,0.15)', borderRadius: '8px',
                fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem',
              }}>
                ℹ️ 20% of papers will be automatically selected as moderation samples.
              </div>
              {assignError && (
                <div className="toast toast-error" style={{ marginBottom: '1rem' }}>{assignError}</div>
              )}
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={() => setShowAssignModal(false)}>Cancel</button>
              <button
                className="btn btn-primary"
                onClick={handleAssignBundle}
                disabled={assigning || !selectedAssessor || !selectedModerator}
              >
                {assigning ? <LoadingSpinner size={16} /> : 'Assign'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default ExamDashboard
