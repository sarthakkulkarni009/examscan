import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { getSheetPdfUrl, flagSheet } from '../../api/answerSheets'
import { getEvaluation, submitEvaluation, saveDraft } from '../../api/evaluations'
import { getMarkingSchemes } from '../../api/markingSchemes'
import PDFViewer from '../../components/PDFViewer'
import QuestionMarkRow from '../../components/QuestionMarkRow'
import LoadingSpinner from '../../components/LoadingSpinner'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

const FLAG_REASONS = [
  { value: 'Blurry',        label: 'Blurry' },
  { value: 'Malpractice',   label: 'Malpractice' },
  { value: 'Missing Pages', label: 'Missing Pages' },
  { value: 'Other',         label: 'Other' },
]

function EvaluationScreen() {
  const { id } = useParams()
  const { user, accessToken, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const { pendingQueue = [], role: evalRole = 'assessor' } = location.state || {}

  const [scheme,         setScheme]         = useState(null)
  const [existingResult, setExistingResult] = useState(null)
  const [loading,        setLoading]        = useState(true)
  const [submitting,     setSubmitting]     = useState(false)
  const [message,        setMessage]        = useState({ type: '', text: '' })
  const [isSubmitted, setIsSubmitted] = useState(!!location.state?.isCompleted)
  const [markedPdfUrl, setMarkedPdfUrl] = useState(null)

  // Flag state
  const [showFlagMenu, setShowFlagMenu] = useState(false)
  const [flagReason,   setFlagReason]   = useState('')
  const [flagging,     setFlagging]     = useState(false)

  // ── Click-to-mark state ───────────────────────────────────────────────────
  const [activeQuestionId, setActiveQuestionId] = useState(null)
  const [placements, setPlacements] = useState({})
  // { [compositeKey]: { value, page, xPercent, yPercent } | null }
  const [showNoQHint, setShowNoQHint] = useState(false)
  const [lastSaved, setLastSaved] = useState(null)

  // Track visible PDF page
  const visiblePageRef = useRef(1)
  const handleVisiblePageChange = useCallback((page) => {
    visiblePageRef.current = page
  }, [])

  // Flatten all question parts from the marking scheme
  const allQuestions = useMemo(() => {
    if (!scheme?.sections) return []
    const qs = []
    scheme.sections.forEach(q => {
      q.sub_questions?.forEach(sq => {
        sq.parts?.forEach(p => {
          qs.push({
            key: `${q.name}_${sq.name}_${p.name}`,
            label: `${q.name} · ${sq.name} · ${p.name}`,
            shortLabel: `${sq.name}·${p.name}`,
            maxMarks: p.max_marks,
            sectionName: q.name,
            sqName: sq.name,
            partName: p.name,
            qRule: q.rule,
            qRuleCount: q.rule_count,
            sqRule: sq.rule,
            sqRuleCount: sq.rule_count,
          })
        })
      })
    })
    return qs
  }, [scheme])

  const totalQuestions = allQuestions.length
  const markedCount = Object.values(placements).filter(p => p !== null && p !== undefined).length
  const unattemptedCount = totalQuestions - markedCount
  const totalMarks = Object.values(placements)
    .filter(p => p !== null && p !== undefined)
    .reduce((sum, p) => sum + p.value, 0)

  // Group questions by section for rendering
  const sectionGroups = useMemo(() => {
    if (!scheme?.sections) return []
    return scheme.sections.map(q => ({
      name: q.name,
      rule: q.rule,
      ruleCount: q.rule_count,
      questions: allQuestions.filter(aq => aq.sectionName === q.name),
    }))
  }, [scheme, allQuestions])

  // ── Load data ─────────────────────────────────────────────────────────────
  useEffect(() => {
    // Reset state immediately on ID change so old data doesn't bleed into the next paper
    setExistingResult(null)
    setMarkedPdfUrl(null)
    setPlacements({})
    setActiveQuestionId(null)
    setIsSubmitted(!!location.state?.isCompleted)
    setMessage({ type: '', text: '' })
    setLoading(true)

    const fetchData = async () => {
      try {
        let subjectCode = location.state?.subjectCode

        if (!subjectCode) {
          const { getAnswerSheets } = await import('../../api/answerSheets')
          const sheetsRes = await getAnswerSheets()
          const allSheets = sheetsRes.data.results || sheetsRes.data || []
          const currentSheet = allSheets.find((s) => s.id === parseInt(id))
          if (currentSheet) subjectCode = currentSheet.subject_code
        }

        if (subjectCode) {
          const schemesRes = await getMarkingSchemes({ subject_code: subjectCode })
          const schemes = schemesRes.data.results || schemesRes.data || []
          if (schemes.length > 0) {
            setScheme(schemes[0])
          } else {
            setMessage({ type: 'error', text: `No marking scheme found for subject ${subjectCode}.` })
          }
        } else {
          setMessage({ type: 'error', text: `Could not identify subject for sheet #${id}. Return to Dashboard and try again.` })
        }

        // Try to fetch existing evaluation (may have draft badge positions)
        try {
          const evalRes = await getEvaluation(id, evalRole)
          const result  = evalRes.data
          setExistingResult(result)

          // Lock the form if the sheet is completed or a marked PDF already exists
          if (result.answer_sheet_status === 'completed' || result.marked_pdf_path) {
            setIsSubmitted(true)
          }

          // If a marked PDF exists, build its URL so we show it instead of original
          if (result.marked_pdf_path) {
            setMarkedPdfUrl(`${BASE_URL}/api/evaluations/${result.id}/marked-pdf/`)
          }

          // ── Pre-populate placements from saved data ───────────────────
          if (result.mark_positions && result.mark_positions.length > 0) {
            const populated = {}
            result.mark_positions.forEach((pos) => {
              populated[pos.question_id] = {
                value:    pos.value,
                page:     pos.page,
                xPercent: pos.x_percent,
                yPercent: pos.y_percent,
              }
            })
            setPlacements(populated)
          }
        } catch {
          // No existing evaluation — fine
        }
      } catch {
        setMessage({ type: 'error', text: 'Failed to load evaluation data.' })
      } finally {
        setLoading(false)
      }
    }

    fetchData()
  }, [id, location.state])

  // ── Click-to-mark handlers ─────────────────────────────────────────────

  // Set first question active once scheme loads
  useEffect(() => {
    if (allQuestions.length > 0 && !activeQuestionId && !isSubmitted) {
      setActiveQuestionId(allQuestions[0].key)
    }
  }, [allQuestions, activeQuestionId, isSubmitted])

  const handleIncrement = useCallback((qKey) => {
    const q = allQuestions.find(q => q.key === qKey)
    if (!q) return
    setPlacements(prev => {
      const cur = prev[qKey]
      if (cur === null || cur === undefined) {
        return { ...prev, [qKey]: { value: 1, page: visiblePageRef.current, xPercent: 5, yPercent: 10 } }
      }
      if (cur.value >= q.maxMarks) return prev
      return { ...prev, [qKey]: { ...cur, value: cur.value + 0.5 } }
    })
  }, [allQuestions])

  const handleDecrement = useCallback((qKey) => {
    setPlacements(prev => {
      const cur = prev[qKey]
      if (!cur) return prev
      if (cur.value <= 0) return prev
      return { ...prev, [qKey]: { ...cur, value: cur.value - 0.5 } }
    })
  }, [])

  const handleClear = useCallback((qKey) => {
    setPlacements(prev => {
      const next = { ...prev }
      delete next[qKey]
      return next
    })
  }, [])

  const handleManualInput = useCallback((qKey, value) => {
    setPlacements(prev => {
      const cur = prev[qKey]
      return {
        ...prev,
        [qKey]: {
          value,
          page: cur?.page ?? visiblePageRef.current,
          xPercent: cur?.xPercent ?? 5,
          yPercent: cur?.yPercent ?? 10,
        }
      }
    })
  }, [])

  const handleQuestionClick = useCallback((qKey, source) => {
    if (source === 'tab') {
      const idx = allQuestions.findIndex(q => q.key === qKey)
      const next = allQuestions[idx + 1]
      if (next) setActiveQuestionId(next.key)
    } else {
      setActiveQuestionId(qKey)
    }
  }, [allQuestions])

  // PDF click — place or move sticker
  const handlePdfClick = useCallback((pageNumber, xPct, yPct) => {
    if (!activeQuestionId) {
      setShowNoQHint(true)
      setTimeout(() => setShowNoQHint(false), 1500)
      return
    }
    setPlacements(prev => {
      const existing = prev[activeQuestionId]
      if (existing === null || existing === undefined) {
        return { ...prev, [activeQuestionId]: { value: 0, page: pageNumber, xPercent: xPct, yPercent: yPct } }
      }
      return { ...prev, [activeQuestionId]: { ...existing, page: pageNumber, xPercent: xPct, yPercent: yPct } }
    })
  }, [activeQuestionId])

  // Sticker move (drag)
  const handleStickerMove = useCallback((qKey, newX, newY) => {
    setPlacements(prev => ({
      ...prev,
      [qKey]: { ...prev[qKey], xPercent: newX, yPercent: newY }
    }))
  }, [])

  // Tab key navigation
  useEffect(() => {
    const handleGlobalTab = (e) => {
      if (e.key === 'Tab' && !e.target.matches('input')) {
        e.preventDefault()
        const idx = allQuestions.findIndex(q => q.key === activeQuestionId)
        const next = allQuestions[idx + 1]
        if (next) setActiveQuestionId(next.key)
      }
    }
    window.addEventListener('keydown', handleGlobalTab)
    return () => window.removeEventListener('keydown', handleGlobalTab)
  }, [activeQuestionId, allQuestions])

  /** Convert placements → API payload */
  const buildMarkPositionsPayload = useCallback((pos) => {
    return Object.entries(pos)
      .filter(([, p]) => p !== null && p !== undefined)
      .map(([question_id, p]) => ({
        question_id,
        value: p.value,
        page: p.page,
        x_percent: p.xPercent,
        y_percent: p.yPercent,
      }))
  }, [])

  /** Build section_results from placements for submit/draft */
  const buildSectionResults = useCallback(() => {
    if (!scheme?.sections) return []
    return scheme.sections.map(q => ({
      name: q.name,
      rule: q.rule,
      rule_count: q.rule_count,
      sub_questions: q.sub_questions.map(sq => ({
        name: sq.name,
        rule: sq.rule,
        rule_count: sq.rule_count,
        parts: sq.parts.map(p => {
          const key = `${q.name}_${sq.name}_${p.name}`
          const pl = placements[key]
          return {
            name: p.name,
            max_marks: p.max_marks,
            marks_obtained: (pl !== null && pl !== undefined) ? pl.value : null,
          }
        })
      }))
    }))
  }, [scheme, placements])

  // ── Auto-save draft ───────────────────────────────────────────────────────
  const draftSaving = useRef(false)

  const triggerDraftSave = useCallback(async () => {
    if (draftSaving.current) return
    const sr = buildSectionResults()
    if (!sr || sr.length === 0) return
    draftSaving.current = true
    try {
      await saveDraft({
        answer_sheet: parseInt(id),
        section_results: sr,
        mark_positions: buildMarkPositionsPayload(placements),
        role: evalRole,
      })
      setLastSaved(new Date())
    } catch {
      // Silent fail
    } finally {
      draftSaving.current = false
    }
  }, [id, buildSectionResults, buildMarkPositionsPayload, placements])

  useEffect(() => {
    const interval = setInterval(() => {
      if (!isSubmitted) triggerDraftSave()
    }, 30000)
    return () => clearInterval(interval)
  }, [triggerDraftSave, isSubmitted])

  // Save on tab/window close
  useEffect(() => {
    const handleUnload = () => {
      const token = sessionStorage.getItem('access_token')
      const base = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
      const body = JSON.stringify({
        answer_sheet: parseInt(id),
        section_results: buildSectionResults(),
        mark_positions: buildMarkPositionsPayload(placements),
      })
      navigator.sendBeacon &&
        navigator.sendBeacon(
          `${base}/api/evaluations/draft/`,
          new Blob([body], { type: 'application/json' })
        )
    }
    window.addEventListener('beforeunload', handleUnload)
    return () => window.removeEventListener('beforeunload', handleUnload)
  }, [id, placements, buildSectionResults, buildMarkPositionsPayload])

  // ── Submit ────────────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    setSubmitting(true)
    setMessage({ type: '', text: '' })
    const sectionResults = buildSectionResults()

    try {
      const payload = {
        answer_sheet:           parseInt(id),
        section_results:        sectionResults,
        pdf_version_at_grading: 1,
        mark_positions:         buildMarkPositionsPayload(placements),
        role:                   evalRole,
      }

      const res = await submitEvaluation(payload)
      const result = res.data
      setExistingResult(result)
      setIsSubmitted(true)
      if (result.marked_pdf_path) {
        setMarkedPdfUrl(`${BASE_URL}/api/evaluations/${result.id}/marked-pdf/`)
      }
      
      const answerSheetId = parseInt(id)
      const remainingQueue = pendingQueue.filter(qId => qId !== answerSheetId)

      if (remainingQueue.length > 0) {
        const nextId = remainingQueue[0]
        navigate(`/teacher/evaluate/${nextId}`, {
          state: { ...location.state, pendingQueue: remainingQueue }
        })
      } else if (pendingQueue.includes(answerSheetId)) {
        navigate('/teacher/dashboard', { state: { bundleCompleted: true } })
      } else {
        setMessage({ type: 'success', text: `✓ Evaluation submitted! Total: ${totalMarks} marks.` })
      }
    } catch (err) {
      const errData = err.response?.data
      if (typeof errData === 'object' && !errData.error) {
        const messages = Object.entries(errData)
          .map(([field, msgs]) => `${field}: ${Array.isArray(msgs) ? msgs.join(', ') : msgs}`)
          .join('; ')
        setMessage({ type: 'error', text: messages })
      } else {
        setMessage({ type: 'error', text: errData?.error || 'Submission failed.' })
      }
    } finally {
      setSubmitting(false)
    }
  }

  // ── Re-Evaluate ───────────────────────────────────────────────────────────
  // Unlocks the form so the teacher can correct marks and re-submit
  const handleReEvaluate = useCallback(() => {
    setIsSubmitted(false)
    setMarkedPdfUrl(null)   // revert to original PDF while re-evaluating
    setMessage({ type: '', text: '' })
  }, [])

  // ── Flag ──────────────────────────────────────────────────────────────────
  const handleFlag = async () => {
    if (!flagReason) return
    setFlagging(true)
    try {
      await flagSheet(id, { flag_reason: flagReason })
      setMessage({ type: 'success', text: 'Sheet flagged for review.' })
      setShowFlagMenu(false)
    } catch (err) {
      setMessage({ type: 'error', text: err.response?.data?.error || 'Failed to flag sheet.' })
    } finally {
      setFlagging(false)
    }
  }

  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <LoadingSpinner message="Loading evaluation..." />
      </div>
    )
  }

  // When submitted and a marked PDF exists, show the annotated version.
  // Otherwise, fallback to the original PDF.
  const pdfUrl = (isSubmitted && markedPdfUrl) ? markedPdfUrl : getSheetPdfUrl(id)

  return (
    <>
      {/* Top bar */}
      <div style={{
        height:          '64px',
        background:      'var(--bg-secondary)',
        borderBottom:    '1px solid var(--border-color)',
        display:         'flex',
        alignItems:      'center',
        justifyContent:  'space-between',
        padding:         '0 var(--space-xl)',
        position:        'sticky',
        top:             0,
        zIndex:          100,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => navigate('/teacher/dashboard')}
            style={{ padding: 0 }}
          >
            ← Back
          </button>
          <span className="logo" style={{ fontSize: '1.25rem', fontWeight: 800 }}>
            {evalRole === 'moderator' ? '🔍 Moderation Mode' : 'Evaluation Mode'}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <span style={{ fontSize: '0.85rem', fontWeight: 500 }}>{user?.fullName}</span>
          <button
            className="btn btn-danger btn-sm"
            onClick={() => setShowFlagMenu(!showFlagMenu)}
            id="flag-toggle-btn"
          >
            🚩 Flag Issue
          </button>
        </div>
      </div>

      {/* Flag dropdown */}
      {showFlagMenu && (
        <div style={{
          position: 'fixed', top: '64px', right: '1rem', zIndex: 200,
          background: 'var(--bg-card)', border: '1px solid var(--border-color)',
          borderRadius: 'var(--radius-md)', padding: '1rem', width: '260px',
          boxShadow: 'var(--shadow-lg)',
        }}>
          <select
            className="form-select"
            value={flagReason}
            onChange={(e) => setFlagReason(e.target.value)}
            style={{ marginBottom: '0.5rem' }}
          >
            <option value="">Select reason...</option>
            {FLAG_REASONS.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>
          <button
            className="btn btn-danger btn-sm"
            style={{ width: '100%' }}
            onClick={handleFlag}
            disabled={!flagReason || flagging}
          >
            {flagging ? 'Flagging...' : 'Submit Flag'}
          </button>
        </div>
      )}

      {/* Amendment banner */}
      {existingResult?.was_amended && (
        <div
          id="amendment-banner"
          style={{
            background:  'linear-gradient(90deg, rgba(245,158,11,0.12), rgba(245,158,11,0.04))',
            border:      '1px solid rgba(245,158,11,0.3)',
            borderRadius: 0,
            padding:     '0.75rem var(--space-xl)',
            display:     'flex',
            alignItems:  'center',
            gap:         '0.75rem',
            fontSize:    'var(--font-size-sm)',
            color:       '#92400E',
          }}
        >
          <span style={{ fontSize: '1.2rem' }}>⚠️</span>
          <span>
            <strong>Marks amended by Exam Department</strong>
            {existingResult.amended_at && (
              <> on {new Date(existingResult.amended_at).toLocaleDateString('en-IN', {
                day: 'numeric', month: 'short', year: 'numeric',
                hour: '2-digit', minute: '2-digit',
              })}</>
            )}
            . The marks shown below reflect the updated values.
          </span>
        </div>
      )}

      {/* Toast message */}
      {message.text && (
        <div
          className={`toast ${message.type === 'error' ? 'toast-error' : 'toast-success'}`}
          style={{ position: 'fixed', top: '72px', left: '50%', transform: 'translateX(-50%)', zIndex: 300 }}
        >
          {message.text}
        </div>
      )}

      {/* Split layout */}
      <div className="split-layout">
        {/* Left: PDF Viewer with sticker overlays */}
        <div className="panel-left">
          <PDFViewer
            url={pdfUrl}
            token={accessToken}
            placements={(isSubmitted && markedPdfUrl) ? {} : placements}
            activeQuestionId={activeQuestionId}
            allQuestions={allQuestions}
            onPdfClick={isSubmitted ? undefined : handlePdfClick}
            onStickerMove={handleStickerMove}
            onStickerRemove={handleClear}
            onStickerClick={(qKey) => setActiveQuestionId(qKey)}
            onStickerIncrement={handleIncrement}
            onStickerDecrement={handleDecrement}
            onVisiblePageChange={handleVisiblePageChange}
            showNoQHint={showNoQHint}
            readOnly={isSubmitted}
          />
        </div>

        {/* Right: Click-to-mark panel */}
        <div className="panel-right" style={{ display: 'flex', flexDirection: 'column', padding: 0 }}>
          {/* Sticky header */}
          <div style={{
            padding: '14px 16px',
            borderBottom: '1px solid var(--border-color)',
            background: 'var(--bg-secondary)',
            position: 'sticky', top: 0, zIndex: 10,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>Marking scheme</span>
              <span style={{ fontSize: '14px', fontWeight: 600, color: '#1D9E75' }}>{markedCount} / {totalQuestions}</span>
            </div>
            {lastSaved && (
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '3px' }}>
                · Auto-saved {Math.round((Date.now() - lastSaved.getTime()) / 1000)}s ago
              </div>
            )}
            {pendingQueue.length > 0 && (
              <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '3px' }}>
                Sheet {pendingQueue.indexOf(parseInt(id)) + 1} of {pendingQueue.length}
              </div>
            )}
          </div>

          {/* Hint bar */}
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            padding: '8px 16px',
            background: activeQuestionId ? '#E1F5EE' : '#FFF8E1',
            borderBottom: `1px solid ${activeQuestionId ? '#5DCAA5' : '#FFE082'}`,
            fontSize: '13px',
            color: activeQuestionId ? '#085041' : '#F57F17',
          }}>
            <span>
              {activeQuestionId
                ? `${allQuestions.find(q => q.key === activeQuestionId)?.label || activeQuestionId} — click PDF to place sticker`
                : 'Select a question to begin marking'
              }
            </span>
          </div>

          {/* Scrollable question list */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {scheme ? sectionGroups.map(section => {
              const sectionTotal = section.questions.reduce((sum, q) => {
                const p = placements[q.key]
                return sum + ((p !== null && p !== undefined) ? p.value : 0)
              }, 0)
              const sectionMax = section.questions.reduce((sum, q) => sum + q.maxMarks, 0)

              return (
                <div key={section.name}>
                  {/* Section header */}
                  <div style={{
                    padding: '10px 16px',
                    background: 'var(--bg-primary)',
                    borderBottom: '1px solid var(--border-color)',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  }}>
                    <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                      {section.name}
                      {section.rule === 'any' && <span style={{ fontWeight: 400, marginLeft: '6px', fontSize: '12px' }}>Any {section.ruleCount}</span>}
                    </span>
                    <span style={{ fontSize: '13px', fontWeight: 600, color: '#1D9E75' }}>
                      {sectionTotal} / {sectionMax}
                    </span>
                  </div>

                  {/* Question rows */}
                  {section.questions.map(q => (
                    <QuestionMarkRow
                      key={q.key}
                      questionId={q.key}
                      label={q.label}
                      maxMarks={q.maxMarks}
                      placement={placements[q.key] ?? null}
                      isActive={activeQuestionId === q.key}
                      onClick={isSubmitted ? undefined : (src) => handleQuestionClick(q.key, src)}
                      onIncrement={isSubmitted ? undefined : () => handleIncrement(q.key)}
                      onDecrement={isSubmitted ? undefined : () => handleDecrement(q.key)}
                      onClear={isSubmitted ? undefined : () => handleClear(q.key)}
                      onManualInput={isSubmitted ? undefined : (v) => handleManualInput(q.key, v)}
                      disabled={isSubmitted}
                    />
                  ))}
                </div>
              )
            }) : (
              <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '3rem' }}>
                No marking scheme found. Contact the exam department.
              </div>
            )}
          </div>

          {/* Sticky footer */}
          {scheme && (
            <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border-color)', background: 'var(--bg-secondary)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', color: 'var(--text-muted)', marginBottom: '8px' }}>
                <span>{markedCount} marked</span>
                <span>{unattemptedCount} unattempted</span>
                <span>Total: {totalMarks}</span>
              </div>

              {unattemptedCount > 0 && (
                <div style={{
                  padding: '8px 12px', background: 'var(--bg-primary)',
                  border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)',
                  fontSize: '13px', color: 'var(--text-secondary)', textAlign: 'center', marginBottom: '8px',
                }}>
                  {unattemptedCount} unattempted — will show as — in results
                </div>
              )}

              {isSubmitted ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <div style={{
                    width: '100%', padding: '12px', textAlign: 'center',
                    background: 'linear-gradient(135deg, #22c55e, #16a34a)', color: '#fff',
                    fontWeight: 700, fontSize: '15px', borderRadius: 'var(--radius-md)',
                  }}>✓ Submitted</div>
                  <button className="btn btn-secondary" style={{ width: '100%' }} onClick={handleReEvaluate}>
                    🔄 Re-Evaluate
                  </button>
                </div>
              ) : (
                <button
                  onClick={handleSubmit}
                  disabled={markedCount === 0 || submitting}
                  style={{
                    width: '100%', padding: '12px',
                    background: markedCount > 0 ? '#1D9E75' : 'var(--bg-primary)',
                    color: markedCount > 0 ? '#fff' : 'var(--text-muted)',
                    border: 'none', borderRadius: 'var(--radius-md)',
                    fontSize: '15px', fontWeight: '600',
                    cursor: markedCount > 0 ? 'pointer' : 'not-allowed',
                  }}
                >
                  {submitting ? 'Submitting...'
                    : pendingQueue.filter(qid => qid !== parseInt(id)).length === 0 && pendingQueue.length > 0
                      ? 'Submit & Finish'
                      : pendingQueue.length > 0 ? 'Submit & Next →' : 'Submit Evaluation'}
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  )
}

export default EvaluationScreen
