import React, { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { getAnswerSheets } from '../../api/answerSheets'
import { changePassword } from '../../api/auth'
import {
  getAssessmentBundles, getModerationBundles,
  getModerationStatus, requestComparison,
} from '../../api/moderation'
import StatusBadge from '../../components/StatusBadge'
import LoadingSpinner from '../../components/LoadingSpinner'

function TeacherDashboard() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [activeTab, setActiveTab] = useState('assessment')
  const [assessmentBundles, setAssessmentBundles] = useState([])
  const [moderationBundles, setModerationBundles] = useState([])
  const [sheets, setSheets] = useState([])
  const [loading, setLoading] = useState(true)
  const [expandedBundle, setExpandedBundle] = useState(null)

  // Moderation state per bundle
  const [modStatuses, setModStatuses] = useState({})
  const [comparingBundle, setComparingBundle] = useState(null)
  const [comparisonResult, setComparisonResult] = useState(null)
  const [expandedPaper, setExpandedPaper] = useState(null)

  const [showPasswordModal, setShowPasswordModal] = useState(
    location.state?.mustChangePassword || false
  )
  const [oldPwd, setOldPwd] = useState('')
  const [newPwd, setNewPwd] = useState('')
  const [pwdLoading, setPwdLoading] = useState(false)
  const [pwdMessage, setPwdMessage] = useState({ type: '', text: '' })
  const [toastMessage, setToastMessage] = useState({ type: '', text: '' })

  useEffect(() => { fetchData() }, [])

  useEffect(() => {
    if (location.state?.bundleCompleted) {
      setToastMessage({ type: 'success', text: 'Bundle fully evaluated!' })
      window.history.replaceState({}, document.title)
      setTimeout(() => setToastMessage({ type: '', text: '' }), 4000)
    }
  }, [location.state])

  const fetchData = async () => {
    setLoading(true)
    try {
      const [sheetsRes, assessRes, modRes] = await Promise.all([
        getAnswerSheets(),
        getAssessmentBundles(),
        getModerationBundles(),
      ])
      setSheets(sheetsRes.data.results || sheetsRes.data)
      setAssessmentBundles(assessRes.data.results || assessRes.data || [])
      setModerationBundles(modRes.data.results || modRes.data || [])
    } catch { /* silent */ } finally { setLoading(false) }
  }

  const loadModerationStatus = async (bundleId) => {
    try {
      const res = await getModerationStatus(bundleId)
      setModStatuses(prev => ({ ...prev, [bundleId]: res.data }))
    } catch { /* no moderation for this bundle */ }
  }

  const handlePasswordChange = async (e) => {
    e.preventDefault()
    setPwdLoading(true)
    setPwdMessage({ type: '', text: '' })
    try {
      await changePassword({ old_password: oldPwd, new_password: newPwd })
      setPwdMessage({ type: 'success', text: 'Password changed successfully!' })
      setTimeout(() => setShowPasswordModal(false), 1500)
    } catch (err) {
      setPwdMessage({
        type: 'error',
        text: err.response?.data?.old_password?.[0] || err.response?.data?.new_password?.[0] || 'Failed.',
      })
    } finally { setPwdLoading(false) }
  }

  const toggleBundle = (bundleId) => {
    if (expandedBundle === bundleId) {
      setExpandedBundle(null)
    } else {
      setExpandedBundle(bundleId)
      loadModerationStatus(bundleId)
    }
  }

  const handleRequestComparison = async (bundleId) => {
    setComparingBundle(bundleId)
    setComparisonResult(null)
    try {
      const res = await requestComparison(bundleId)
      setComparisonResult(res.data)
      loadModerationStatus(bundleId)
      if (res.data.bundle_status === 'PASSED') {
        setToastMessage({ type: 'success', text: 'All moderation papers passed! Remaining papers unlocked.' })
        setTimeout(() => setToastMessage({ type: '', text: '' }), 5000)
        fetchData()
      }
    } catch (err) {
      const data = err.response?.data
      if (data?.status === 'BLOCKED') {
        setComparisonResult(data)
      } else {
        setToastMessage({ type: 'error', text: data?.error || 'Comparison failed.' })
        setTimeout(() => setToastMessage({ type: '', text: '' }), 5000)
      }
    } finally { setComparingBundle(null) }
  }

  const handleEvaluateClick = (sheet, allSheets, subjectCode, role = 'assessor') => {
    // Build the pending queue, filtering out locked (non-sample) papers
    const bundleModStatus = modStatuses[sheet.bundle]
    const pendingIds = allSheets
      .filter(s => {
        if (s.status !== 'assigned' && s.status !== 'under_evaluation') return false
        // If moderation is active and not yet passed, only include sample papers
        if (role === 'assessor' && bundleModStatus && !bundleModStatus.assignment?.moderation_passed && bundleModStatus.bundle_status !== 'UNLOCKED') {
          const sampleIds = bundleModStatus.sample_sheet_ids || []
          if (!sampleIds.includes(s.id)) return false // locked paper
        }
        return true
      })
      .map(s => s.id)
    navigate(`/teacher/evaluate/${sheet.id}`, {
      state: { subjectCode, isCompleted: sheet.status === 'completed', pendingQueue: pendingIds, role }
    })
  }

  const getPaperModerationState = (sheet, modStatus) => {
    if (!modStatus) return null
    const sampleIds = modStatus.sample_sheet_ids || []
    const isSample = sampleIds.includes(sheet.id)

    if (!isSample) {
      // Non-moderation paper
      if (modStatus.bundle_status === 'UNLOCKED' || modStatus.assignment?.moderation_passed) {
        return null // Normal paper, unlocked
      }
      return { state: 'LOCKED', label: 'Locked', icon: '🔒', cls: 'mod-state-locked' }
    }

    // Moderation paper
    const paperStatus = modStatus.papers?.find(p => p.paper_id === sheet.id)
    if (!paperStatus || paperStatus.status === 'PENDING') {
      // Check if moderator has evaluated
      if (modStatus.moderator_evaluated < modStatus.sample_count) {
        return { state: 'WAITING', label: 'Waiting for Moderator', icon: '🟡', cls: 'mod-state-waiting' }
      }
      return { state: 'AVAILABLE', label: 'Ready for Comparison', icon: '🔵', cls: 'mod-state-available' }
    }
    if (paperStatus.status === 'PASSED') {
      return { state: 'PASSED', label: 'Passed', icon: '🟢', cls: 'mod-state-passed' }
    }
    if (paperStatus.status === 'FAILED') {
      return { state: 'FAILED', label: 'Needs Correction', icon: '🔴', cls: 'mod-state-failed' }
    }
    return null
  }

  const getModerationBanner = (bundleId) => {
    const ms = modStatuses[bundleId]
    if (!ms) return null
    const { bundle_status, sample_count } = ms
    const failedCount = ms.papers?.filter(p => p.status === 'FAILED').length || 0

    if (bundle_status === 'UNLOCKED') {
      return (
        <div className="mod-banner mod-banner-success">
          🟢 Moderation passed. All {sample_count} sample papers verified. Remaining papers unlocked.
        </div>
      )
    }
    if (bundle_status === 'FAILED') {
      return (
        <div className="mod-banner mod-banner-error">
          🔴 {failedCount} paper{failedCount > 1 ? 's' : ''} require{failedCount === 1 ? 's' : ''} correction. Click a failed paper to see comparison details.
        </div>
      )
    }
    if (ms.moderator_evaluated < sample_count || ms.assessor_evaluated < sample_count) {
      const parts = []
      if (ms.assessor_evaluated < sample_count) {
        parts.push(`You have evaluated ${ms.assessor_evaluated}/${sample_count} sample papers`)
      }
      if (ms.moderator_evaluated < sample_count) {
        parts.push(`Moderator has evaluated ${ms.moderator_evaluated}/${sample_count}`)
      }
      return (
        <div className="mod-banner mod-banner-warning">
          🟡 {parts.join('. ')}. Complete all sample evaluations to enable comparison.
        </div>
      )
    }
    return (
      <div className="mod-banner mod-banner-success">
        ✅ All {sample_count} sample papers evaluated by both sides. Click "Request Comparison" to proceed.
      </div>
    )
  }

  const allBundles = activeTab === 'assessment' ? assessmentBundles : moderationBundles

  const stats = {
    total_bundles: assessmentBundles.length + moderationBundles.length,
    assigned: sheets.filter(s => s.status === 'assigned').length,
    completed: sheets.filter(s => s.status === 'completed').length,
    flagged: sheets.filter(s => s.status === 'flagged').length,
  }

  return (
    <>
      <div className="page-container fade-in">
        {toastMessage.text && (
          <div className={`toast toast-${toastMessage.type === 'error' ? 'error' : 'success'}`} style={{ marginBottom: '1.5rem' }}>
            {toastMessage.text}
          </div>
        )}
        <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1>Dashboard</h1>
            <p>Your assigned marking bundles</p>
          </div>
          <button className="btn btn-secondary" onClick={() => setShowPasswordModal(true)}>
            Change Password
          </button>
        </div>

        {/* Stats */}
        <div className="grid-4" style={{ marginBottom: '2rem' }}>
          <div className="card stat-card">
            <div className="stat-value" style={{ color: 'var(--color-primary-light)' }}>{stats.total_bundles}</div>
            <div className="stat-label">Total Bundles</div>
          </div>
          <div className="card stat-card">
            <div className="stat-value" style={{ color: 'var(--color-info)' }}>{stats.assigned}</div>
            <div className="stat-label">Sheets Pending</div>
          </div>
          <div className="card stat-card">
            <div className="stat-value" style={{ color: 'var(--color-success)' }}>{stats.completed}</div>
            <div className="stat-label">Sheets Completed</div>
          </div>
          <div className="card stat-card">
            <div className="stat-value" style={{ color: 'var(--color-danger)' }}>{stats.flagged}</div>
            <div className="stat-label">Sheets Flagged</div>
          </div>
        </div>

        {/* Tabs */}
        <div className="mod-tabs" style={{ marginBottom: '1rem' }}>
          <button
            className={`mod-tab ${activeTab === 'assessment' ? 'mod-tab-active' : ''}`}
            onClick={() => { setActiveTab('assessment'); setExpandedBundle(null) }}
          >
            📝 Assessment Bundles
            {assessmentBundles.length > 0 && <span className="mod-tab-count">{assessmentBundles.length}</span>}
          </button>
          <button
            className={`mod-tab ${activeTab === 'moderation' ? 'mod-tab-active' : ''}`}
            onClick={() => { setActiveTab('moderation'); setExpandedBundle(null) }}
          >
            🔍 Moderation Bundles
            {moderationBundles.length > 0 && <span className="mod-tab-count">{moderationBundles.length}</span>}
          </button>
        </div>

        {loading ? (
          <LoadingSpinner message="Loading assigned bundles..." />
        ) : (
          <div className="table-container" style={{ borderRadius: '12px', border: '1px solid var(--border-color)' }}>
            <table>
              <thead>
                <tr>
                  <th>Bundle #</th>
                  <th>Subject</th>
                  <th>Total Sheets</th>
                  <th>Grading Progress</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {allBundles.map((bundle) => {
                  const bundleSheets = sheets.filter(s => s.bundle === bundle.id)
                  const modStatus = modStatuses[bundle.id]
                  
                  const bundleGraded = activeTab === 'moderation' 
                    ? (modStatus?.moderator_evaluated || 0) 
                    : bundleSheets.filter(s => s.status === 'completed').length
                    
                  const totalToGrade = activeTab === 'moderation'
                    ? (modStatus?.sample_count || 0)
                    : bundleSheets.length

                  return (
                    <React.Fragment key={bundle.id}>
                      <tr
                        style={{ cursor: 'pointer', backgroundColor: expandedBundle === bundle.id ? 'var(--background-secondary)' : 'transparent', borderBottom: expandedBundle === bundle.id ? 'none' : '1px solid var(--border-color)' }}
                        onClick={() => toggleBundle(bundle.id)}
                      >
                        <td style={{ fontWeight: 600 }}>#{bundle.bundle_number}</td>
                        <td>
                          <div>{bundle.subject_name || 'Subject'}</div>
                          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{bundle.subject_code}</div>
                        </td>
                        <td>{activeTab === 'moderation' ? (modStatus?.sample_count || '—') : totalToGrade} sheets</td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <div style={{ flex: 1, background: 'var(--border-color)', height: '6px', borderRadius: '3px', overflow: 'hidden' }}>
                              <div style={{ background: bundleGraded === totalToGrade ? 'var(--color-success)' : 'var(--color-primary)', height: '100%', width: `${totalToGrade > 0 ? (bundleGraded / totalToGrade) * 100 : 0}%` }}></div>
                            </div>
                            <span style={{ fontSize: '0.8rem', fontWeight: 500, color: 'var(--text-secondary)' }}>{bundleGraded}/{totalToGrade}</span>
                          </div>
                        </td>
                        <td>
                          <button className="btn btn-secondary btn-sm" onClick={(e) => { e.stopPropagation(); toggleBundle(bundle.id) }}>
                            {expandedBundle === bundle.id ? 'Close' : 'View Sheets'}
                          </button>
                        </td>
                      </tr>

                      {/* Expanded Sheets View */}
                      {expandedBundle === bundle.id && (
                        <tr>
                          <td colSpan="5" style={{ padding: 0 }}>
                            <div style={{ background: 'var(--background-primary)', borderBottom: '1px solid var(--border-color)', padding: '1.5rem', boxShadow: 'inset 0 4px 6px -4px rgba(0,0,0,0.1)' }}>

                              {/* Moderation banner (assessment tab only) */}
                              {activeTab === 'assessment' && bundle.moderation_assignment && getModerationBanner(bundle.id)}

                              {/* Request Comparison button */}
                              {activeTab === 'assessment' && bundle.moderation_assignment && modStatus && !modStatus.assignment?.moderation_passed && (() => {
                                const assessorDone = modStatus.assessor_evaluated || 0
                                const sampleTotal = modStatus.sample_count || 0
                                const assessorReady = assessorDone >= sampleTotal && sampleTotal > 0
                                const moderatorDone = modStatus.moderator_evaluated || 0
                                const moderatorReady = moderatorDone >= sampleTotal

                                return (
                                  <div style={{ marginBottom: '1rem', display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
                                    {assessorReady && moderatorReady ? (
                                      <button
                                        className="btn btn-primary btn-sm"
                                        onClick={() => handleRequestComparison(bundle.id)}
                                        disabled={comparingBundle === bundle.id}
                                      >
                                        {comparingBundle === bundle.id ? '⏳ Comparing...' : '📊 Request Comparison'}
                                      </button>
                                    ) : !assessorReady ? (
                                      <span style={{ fontSize: '0.85rem', color: 'var(--color-info)', fontWeight: 500 }}>
                                        📝 Evaluate {sampleTotal - assessorDone} more sample paper{sampleTotal - assessorDone > 1 ? 's' : ''} to enable comparison
                                      </span>
                                    ) : (
                                      <button
                                        className="btn btn-primary btn-sm"
                                        onClick={() => handleRequestComparison(bundle.id)}
                                        disabled={comparingBundle === bundle.id}
                                      >
                                        {comparingBundle === bundle.id ? '⏳ Comparing...' : '📊 Request Comparison'}
                                      </button>
                                    )}
                                    {comparisonResult?.status === 'BLOCKED' && (
                                      <span style={{ fontSize: '0.85rem', color: 'var(--color-warning)' }}>
                                        {comparisonResult.message}
                                      </span>
                                    )}
                                  </div>
                                )
                              })()}

                              <h4 style={{ fontSize: '0.9rem', color: 'var(--text-muted)', marginBottom: '1rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                {activeTab === 'moderation' ? 'Moderation Papers' : 'Answer Sheets'}
                              </h4>

                              {(() => {
                                let displaySheets = [...bundleSheets]
                                // For moderation tab, only show moderation samples
                                if (activeTab === 'moderation' && modStatus) {
                                  const sampleIds = modStatus.sample_sheet_ids || []
                                  displaySheets = displaySheets.filter(s => sampleIds.includes(s.id))
                                }
                                // For assessment tab, sort moderation papers to the top
                                if (activeTab === 'assessment' && modStatus) {
                                  const sampleIds = modStatus.sample_sheet_ids || []
                                  displaySheets.sort((a, b) => {
                                    const aIsSample = sampleIds.includes(a.id) ? 0 : 1
                                    const bIsSample = sampleIds.includes(b.id) ? 0 : 1
                                    return aIsSample - bIsSample
                                  })
                                }

                                if (displaySheets.length === 0) {
                                  return <div style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>No sheets found.</div>
                                }

                                return (
                                  <table style={{ margin: 0, background: 'var(--background-secondary)', borderRadius: '8px', overflow: 'hidden' }}>
                                    <thead>
                                      <tr style={{ background: 'var(--border-color)' }}>
                                        <th style={{ padding: '0.75rem 1rem' }}>S.No. & Barcode</th>
                                        <th style={{ padding: '0.75rem 1rem' }}>Status</th>
                                        {activeTab === 'assessment' && bundle.moderation_assignment && (
                                          <th style={{ padding: '0.75rem 1rem' }}>Moderation</th>
                                        )}
                                        <th style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>Action</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {displaySheets.map((sheet, idx) => {
                                        const modState = activeTab === 'assessment' && bundle.moderation_assignment
                                          ? getPaperModerationState(sheet, modStatus)
                                          : null
                                        const isLocked = modState?.state === 'LOCKED'
                                        const isFailed = modState?.state === 'FAILED'
                                        const paperComparison = modStatus?.papers?.find(p => p.paper_id === sheet.id)

                                        // For moderation tab: check if moderator has evaluated this sheet
                                        const modEvalIds = modStatus?.moderator_evaluated_sheet_ids || []
                                        const isModeratorEvaluated = activeTab === 'moderation' && modEvalIds.includes(sheet.id)

                                        return (
                                          <React.Fragment key={sheet.id}>
                                            <tr style={{ opacity: isLocked ? 0.5 : 1 }}>
                                              <td style={{ padding: '0.75rem 1rem' }}>
                                                <span style={{ color: 'var(--text-muted)', marginRight: '0.5rem' }}>#{idx + 1}</span>
                                                <span style={{ fontWeight: 600, fontFamily: 'monospace' }}>{sheet.token}</span>
                                                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginLeft: '0.5rem' }}>(v{sheet.pdf_version})</span>
                                              </td>
                                              <td style={{ padding: '0.75rem 1rem' }}>
                                                {activeTab === 'moderation' ? (
                                                  isModeratorEvaluated
                                                    ? <span className="badge badge-completed">Evaluated</span>
                                                    : <span className="badge badge-assigned">Pending</span>
                                                ) : (
                                                  <StatusBadge status={sheet.status} />
                                                )}
                                              </td>
                                              {activeTab === 'assessment' && bundle.moderation_assignment && (
                                                <td style={{ padding: '0.75rem 1rem' }}>
                                                  {modState ? (
                                                    <span className={`mod-state-badge ${modState.cls}`}>
                                                      {modState.icon} {modState.label}
                                                    </span>
                                                  ) : '—'}
                                                </td>
                                              )}
                                              <td style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>
                                                {isLocked ? (
                                                  <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>🔒 Locked</span>
                                                ) : isFailed ? (
                                                  <button
                                                    className="btn btn-danger btn-sm"
                                                    onClick={() => setExpandedPaper(expandedPaper === sheet.id ? null : sheet.id)}
                                                  >
                                                    {expandedPaper === sheet.id ? 'Hide Details' : 'View Comparison'}
                                                  </button>
                                                ) : (
                                                  <button
                                                    className="btn btn-primary btn-sm"
                                                    onClick={() => handleEvaluateClick(sheet, displaySheets, bundle.subject_code, activeTab === 'moderation' ? 'moderator' : 'assessor')}
                                                  >
                                                    {(activeTab === 'moderation' ? isModeratorEvaluated : sheet.status === 'completed') ? 'View Details' : 'Evaluate Paper'}
                                                  </button>
                                                )}
                                              </td>
                                            </tr>

                                            {/* Inline comparison panel for failed papers */}
                                            {isFailed && expandedPaper === sheet.id && paperComparison && (
                                              <tr>
                                                <td colSpan={bundle.moderation_assignment ? 4 : 3} style={{ padding: 0 }}>
                                                  <div className="comparison-panel">
                                                    <h5 style={{ marginBottom: '0.75rem', fontSize: '0.9rem' }}>📊 Mark Comparison</h5>
                                                    <table className="comparison-table">
                                                      <thead>
                                                        <tr>
                                                          <th>Question</th>
                                                          <th>Assessor</th>
                                                          <th>Moderator</th>
                                                        </tr>
                                                      </thead>
                                                      <tbody>
                                                        {paperComparison.question_comparison?.map((qc, i) => (
                                                          <tr key={i} className={qc.assessor !== qc.moderator ? 'comparison-mismatch' : ''}>
                                                            <td>{qc.question}</td>
                                                            <td>{qc.assessor}</td>
                                                            <td>{qc.moderator}</td>
                                                          </tr>
                                                        ))}
                                                      </tbody>
                                                      <tfoot>
                                                        <tr style={{ fontWeight: 700 }}>
                                                          <td>Total</td>
                                                          <td>{paperComparison.assessor_total}</td>
                                                          <td>{paperComparison.moderator_total}</td>
                                                        </tr>
                                                        <tr>
                                                          <td colSpan={3} style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                                                            Allowed difference: ±{paperComparison.allowed_difference}
                                                          </td>
                                                        </tr>
                                                      </tfoot>
                                                    </table>
                                                    <button
                                                      className="btn btn-primary"
                                                      style={{ marginTop: '0.75rem', width: '100%' }}
                                                      onClick={() => handleEvaluateClick(sheet, displaySheets, bundle.subject_code, 'assessor')}
                                                    >
                                                      🔄 Reopen Evaluation
                                                    </button>
                                                  </div>
                                                </td>
                                              </tr>
                                            )}
                                          </React.Fragment>
                                        )
                                      })}
                                    </tbody>
                                  </table>
                                )
                              })()}
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  )
                })}
                {allBundles.length === 0 && (
                  <tr>
                    <td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '3rem' }}>
                      {activeTab === 'moderation'
                        ? 'No moderation bundles assigned to you.'
                        : 'No bundles have been assigned to you yet.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Password Change Modal */}
      {showPasswordModal && (
        <div className="modal-backdrop" onClick={() => !location.state?.mustChangePassword && setShowPasswordModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Change Password</h2>
              {!location.state?.mustChangePassword && (
                <button className="btn btn-ghost btn-sm" onClick={() => setShowPasswordModal(false)}>✕</button>
              )}
            </div>
            <form onSubmit={handlePasswordChange}>
              <div className="form-group">
                <label className="form-label">Current Password</label>
                <input type="password" className="form-input" value={oldPwd} onChange={(e) => setOldPwd(e.target.value)} required />
              </div>
              <div className="form-group">
                <label className="form-label">New Password</label>
                <input type="password" className="form-input" value={newPwd} onChange={(e) => setNewPwd(e.target.value)} required minLength={8} />
              </div>
              {pwdMessage.text && (
                <div className={`toast ${pwdMessage.type === 'error' ? 'toast-error' : 'toast-success'}`} style={{ marginBottom: '1rem' }}>
                  {pwdMessage.text}
                </div>
              )}
              <div className="modal-footer">
                <button type="submit" className="btn btn-primary" disabled={pwdLoading}>
                  {pwdLoading ? <LoadingSpinner size={16} /> : 'Update Password'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  )
}

export default TeacherDashboard
