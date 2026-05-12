import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { submitBundle } from '../../api/bundles'
import { getBundleQualityCheck, replaceSheetImages } from '../../api/qualityCheck'
import { API_BASE_URL } from '../../api/config'
import LoadingSpinner from '../../components/LoadingSpinner'

// ── Page state constants ─────────────────────────────────
const STATE = {
  CLEAR: 'clear',
  BLURRY: 'blurry',
  ACCEPTABLE: 'acceptable',
}

// ── Score bar indicator ──────────────────────────────────
function ScoreBar({ score }) {
  const pct = Math.min(100, (score / 200) * 100)
  const color = score >= 120 ? '#10b981' : score >= 60 ? '#f59e0b' : '#ef4444'
  return (
    <div style={{ marginTop: '6px' }}>
      <div style={{ fontSize: '10px', color: '#94A3B8', marginBottom: '2px' }}>
        Sharpness: {score.toFixed(0)}
      </div>
      <div style={{ height: '4px', background: '#E2E8F0', borderRadius: '2px' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: '2px', transition: 'width 0.3s' }} />
      </div>
    </div>
  )
}

// ── Single thumbnail card ────────────────────────────────
function ThumbnailCard({ sheet, pageState, onRetake, onMarkAcceptable, onUndo, onPreview, isRetaking }) {
  const fileInputRef = useRef()
  const baseUrl = API_BASE_URL
  const thumbnailUrl = `${baseUrl}${sheet.thumbnail_url}`

  const borderColor = {
    [STATE.CLEAR]: '#10b981',
    [STATE.BLURRY]: '#ef4444',
    [STATE.ACCEPTABLE]: '#f59e0b',
  }[pageState]

  const overlayColor = {
    [STATE.BLURRY]: 'rgba(239,68,68,0.35)',
    [STATE.ACCEPTABLE]: 'rgba(245,158,11,0.25)',
  }[pageState]

  const handleFileChange = (e) => {
    const file = e.target.files?.[0]
    if (file) onRetake(sheet.sheet_id, file)
    e.target.value = ''
  }

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: '6px',
      flexShrink: 0,
    }}>
      {/* Thumbnail */}
      <div
        style={{
          position: 'relative',
          width: '130px',
          height: '170px',
          border: `2.5px solid ${borderColor}`,
          borderRadius: '8px',
          overflow: 'hidden',
          cursor: 'pointer',
          boxShadow: pageState === STATE.BLURRY ? `0 0 12px rgba(239,68,68,0.4)` : 'var(--shadow-sm)',
          transition: 'all 0.2s',
        }}
        onClick={() => !isRetaking && onPreview(sheet.sheet_id)}
      >
        {/* Image */}
        <img
          src={thumbnailUrl}
          alt={`Token ${sheet.token}`}
          style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
          onError={(e) => { e.target.style.background = '#E2E8F0'; e.target.style.display = 'none' }}
        />

        {/* Color overlay for blurry/acceptable */}
        {overlayColor && (
          <div style={{
            position: 'absolute', inset: 0,
            background: overlayColor,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            {pageState === STATE.BLURRY && (
              <div style={{
                background: '#ef4444', color: '#fff',
                fontSize: '11px', fontWeight: 700, padding: '4px 10px',
                borderRadius: '999px', display: 'flex', alignItems: 'center', gap: '4px',
              }}>
                ⚠ Blurry
              </div>
            )}
            {pageState === STATE.ACCEPTABLE && (
              <div style={{
                background: '#f59e0b', color: '#fff',
                fontSize: '11px', fontWeight: 700, padding: '4px 10px',
                borderRadius: '999px', display: 'flex', alignItems: 'center', gap: '4px',
              }}>
                ✓ Marked OK
              </div>
            )}
          </div>
        )}

        {/* Retaking spinner overlay */}
        {isRetaking && (
          <div style={{
            position: 'absolute', inset: 0, background: 'rgba(255,255,255,0.85)',
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '6px',
          }}>
            <LoadingSpinner size={24} />
            <span style={{ fontSize: '10px', color: '#64748B' }}>Uploading...</span>
          </div>
        )}

        {/* Clear checkmark */}
        {pageState === STATE.CLEAR && (
          <div style={{
            position: 'absolute', top: '6px', right: '6px',
            background: '#10b981', color: '#fff',
            width: '20px', height: '20px', borderRadius: '50%',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '11px', fontWeight: 700,
          }}>✓</div>
        )}
      </div>

      {/* Score bar */}
      <div style={{ width: '130px' }}>
        <div style={{ fontSize: '11px', color: '#64748B', textAlign: 'center', fontFamily: 'monospace' }}>
          {sheet.token?.slice(0, 10)}…
        </div>
        <ScoreBar score={sheet.score} />
      </div>

      {/* Action buttons */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', width: '130px' }}>
        {pageState === STATE.BLURRY && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png"
              style={{ display: 'none' }}
              onChange={handleFileChange}
            />
            <button
              className="btn btn-danger btn-sm"
              style={{ fontSize: '11px', padding: '4px 8px', width: '100%' }}
              onClick={() => fileInputRef.current?.click()}
              disabled={isRetaking}
            >
              📷 Retake
            </button>
            <button
              style={{
                background: 'none', border: 'none', color: '#f59e0b',
                fontSize: '10px', cursor: 'pointer', textDecoration: 'underline', padding: '2px 0',
              }}
              onClick={() => onMarkAcceptable(sheet.sheet_id)}
            >
              Mark as acceptable
            </button>
          </>
        )}
        {pageState === STATE.ACCEPTABLE && (
          <button
            style={{
              background: 'none', border: 'none', color: '#94A3B8',
              fontSize: '10px', cursor: 'pointer', textDecoration: 'underline', padding: '2px 0',
            }}
            onClick={() => onUndo(sheet.sheet_id)}
          >
            Undo
          </button>
        )}
      </div>
    </div>
  )
}

// ── Preview Modal ────────────────────────────────────────
function PreviewModal({ sheet, onClose }) {
  const baseUrl = API_BASE_URL
  if (!sheet) return null
  return (
    <div
      className="modal-backdrop"
      onClick={onClose}
      style={{ zIndex: 2000 }}
    >
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: '600px', padding: '1rem' }}
      >
        <div className="modal-header">
          <div>
            <h2 style={{ fontSize: '1rem' }}>Token: <code>{sheet.token}</code></h2>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '2px' }}>
              Sharpness score: {sheet.score}
            </p>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>✕</button>
        </div>
        <img
          src={`${baseUrl}${sheet.thumbnail_url}`}
          alt="Page preview"
          style={{ width: '100%', borderRadius: '8px', objectFit: 'contain', maxHeight: '70vh' }}
        />
      </div>
    </div>
  )
}

// ── Main ReviewScreen ────────────────────────────────────
export default function ReviewScreen() {
  const { bundleId } = useParams()
  const navigate = useNavigate()

  const [qualityData, setQualityData] = useState(null)
  const [pageStates, setPageStates] = useState({})    // { sheet_id: 'clear'|'blurry'|'acceptable' }
  const [retakingIds, setRetakingIds] = useState({})  // { sheet_id: true } while uploading
  const [scores, setScores] = useState({})            // { sheet_id: float } for live updates
  const [thumbnailBust, setThumbnailBust] = useState({}) // { sheet_id: timestamp } cache-bust
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [previewSheet, setPreviewSheet] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitMessage, setSubmitMessage] = useState({ type: '', text: '' })
  const scrollRef = useRef()

  const fetchQuality = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await getBundleQualityCheck(bundleId)
      const data = res.data
      setQualityData(data)

      // Initialize page states from results
      const states = {}
      const scoreMap = {}
      data.results.forEach((r) => {
        states[r.sheet_id] = r.is_blurry ? STATE.BLURRY : STATE.CLEAR
        scoreMap[r.sheet_id] = r.score
      })
      setPageStates(states)
      setScores(scoreMap)
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to run quality check. Please retry.')
    } finally {
      setLoading(false)
    }
  }, [bundleId])

  useEffect(() => {
    fetchQuality()
  }, [fetchQuality])

  // Auto-scroll to first blurry page after load
  useEffect(() => {
    if (!qualityData || !scrollRef.current) return
    const firstBlurry = qualityData.results.find((r) => pageStates[r.sheet_id] === STATE.BLURRY)
    if (firstBlurry) {
      const el = document.getElementById(`thumb-${firstBlurry.sheet_id}`)
      if (el) el.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
    }
  }, [qualityData])

  const retakeImage = async (sheetId, file) => {
    setRetakingIds((prev) => ({ ...prev, [sheetId]: true }))
    try {
      const formData = new FormData()
      formData.append('image', file)
      const res = await replaceSheetImages(sheetId, formData)
      const { quality } = res.data

      // Update state based on new quality
      setPageStates((prev) => ({
        ...prev,
        [sheetId]: quality.is_blurry ? STATE.BLURRY : STATE.CLEAR,
      }))
      setScores((prev) => ({ ...prev, [sheetId]: quality.score }))
      // Bust thumbnail cache
      setThumbnailBust((prev) => ({ ...prev, [sheetId]: Date.now() }))
    } catch (err) {
      alert(err.response?.data?.error || 'Retake failed. Please try again.')
    } finally {
      setRetakingIds((prev) => ({ ...prev, [sheetId]: false }))
    }
  }

  const markAcceptable = (sheetId) => {
    setPageStates((prev) => ({ ...prev, [sheetId]: STATE.ACCEPTABLE }))
  }

  const undoAcceptable = (sheetId) => {
    setPageStates((prev) => ({ ...prev, [sheetId]: STATE.BLURRY }))
  }

  const handleSubmit = async () => {
    setSubmitting(true)
    setSubmitMessage({ type: '', text: '' })
    try {
      await submitBundle(bundleId)
      setSubmitMessage({ type: 'success', text: 'Bundle submitted successfully!' })
      setTimeout(() => navigate('/scanning/session'), 1500)
    } catch (err) {
      setSubmitMessage({ type: 'error', text: err.response?.data?.error || 'Submission failed.' })
      setSubmitting(false)
    }
  }

  const blockedCount = Object.values(pageStates).filter((s) => s === STATE.BLURRY).length
  const canSubmit = blockedCount === 0 && !loading

  // ── Loading ──────────────────────────────────────────
  if (loading) {
    return (
      <div className="page-container fade-in" style={{ textAlign: 'center', paddingTop: '5rem' }}>
        <LoadingSpinner size={48} />
        <p style={{ marginTop: '1.5rem', color: 'var(--text-secondary)', fontSize: 'var(--font-size-lg)' }}>
          Checking image quality…
        </p>
        <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', marginTop: '0.5rem' }}>
          Running blur detection on all answer sheets
        </p>
      </div>
    )
  }

  // ── Error ────────────────────────────────────────────
  if (error) {
    return (
      <div className="page-container fade-in" style={{ textAlign: 'center', paddingTop: '5rem' }}>
        <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>⚠️</div>
        <h2 style={{ color: 'var(--color-danger)', marginBottom: '0.5rem' }}>Quality Check Failed</h2>
        <p style={{ color: 'var(--text-muted)', marginBottom: '1.5rem' }}>{error}</p>
        <button className="btn btn-primary" onClick={fetchQuality}>Retry</button>
      </div>
    )
  }

  const results = qualityData?.results || []

  return (
    <div className="page-container fade-in">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1>Review & Submit</h1>
          <p>Bundle #{bundleId} — Quality check complete. Review flagged sheets before submitting.</p>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={() => navigate(`/scanning/review/${bundleId}`)}>
          ← Back to Scanning
        </button>
      </div>

      {/* Alert Banner */}
      <div
        className="card"
        style={{
          marginBottom: '1.5rem',
          background: blockedCount > 0 ? 'rgba(239,68,68,0.05)' : 'rgba(16,185,129,0.05)',
          border: `1px solid ${blockedCount > 0 ? 'rgba(239,68,68,0.3)' : 'rgba(16,185,129,0.3)'}`,
          display: 'flex', alignItems: 'center', gap: '1rem',
        }}
      >
        <div style={{ fontSize: '2rem' }}>{blockedCount > 0 ? '🔴' : '🟢'}</div>
        <div>
          {blockedCount > 0 ? (
            <>
              <div style={{ fontWeight: 700, color: 'var(--color-danger)', marginBottom: '2px' }}>
                {blockedCount} sheet{blockedCount !== 1 ? 's' : ''} flagged for poor image quality
              </div>
              <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-secondary)' }}>
                Retake blurry pages or mark them as acceptable to enable submission.
              </div>
            </>
          ) : (
            <>
              <div style={{ fontWeight: 700, color: 'var(--color-success)', marginBottom: '2px' }}>
                All sheets cleared — ready to submit!
              </div>
              <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-secondary)' }}>
                {results.filter(r => pageStates[r.sheet_id] === STATE.ACCEPTABLE).length > 0
                  ? `${results.filter(r => pageStates[r.sheet_id] === STATE.ACCEPTABLE).length} sheet(s) manually marked as acceptable.`
                  : 'All images passed automatic quality check.'}
              </div>
            </>
          )}
        </div>
        <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
          <div style={{ fontSize: '1.5rem', fontWeight: 800 }}>
            {results.filter(r => pageStates[r.sheet_id] === STATE.CLEAR).length}
            <span style={{ fontSize: '0.9rem', fontWeight: 400, color: 'var(--text-muted)' }}>/{results.length}</span>
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Cleared</div>
        </div>
      </div>

      {/* Horizontal thumbnail strip */}
      <div className="card" style={{ marginBottom: '1.5rem', padding: '1.5rem' }}>
        <div style={{ fontSize: 'var(--font-size-sm)', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '1rem' }}>
          {results.length} Answer Sheet{results.length !== 1 ? 's' : ''} — scroll to review all
        </div>
        <div
          ref={scrollRef}
          style={{
            display: 'flex',
            overflowX: 'auto',
            gap: '1.25rem',
            paddingBottom: '1rem',
            scrollBehavior: 'smooth',
          }}
        >
          {results.map((sheet) => {
            const bust = thumbnailBust[sheet.sheet_id]
            const sheetWithBust = bust
              ? { ...sheet, thumbnail_url: `${sheet.thumbnail_url}?t=${bust}`, score: scores[sheet.sheet_id] ?? sheet.score }
              : { ...sheet, score: scores[sheet.sheet_id] ?? sheet.score }

            return (
              <div key={sheet.sheet_id} id={`thumb-${sheet.sheet_id}`}>
                <ThumbnailCard
                  sheet={sheetWithBust}
                  pageState={pageStates[sheet.sheet_id] || STATE.CLEAR}
                  onRetake={retakeImage}
                  onMarkAcceptable={markAcceptable}
                  onUndo={undoAcceptable}
                  onPreview={(id) => setPreviewSheet(sheetWithBust)}
                  isRetaking={!!retakingIds[sheet.sheet_id]}
                />
              </div>
            )
          })}
        </div>
      </div>

      {/* Summary stats */}
      <div className="grid-3" style={{ marginBottom: '1.5rem' }}>
        <div className="card" style={{ textAlign: 'center', padding: '1rem' }}>
          <div style={{ fontSize: '1.75rem', fontWeight: 800, color: 'var(--color-success)' }}>
            {results.filter(r => pageStates[r.sheet_id] === STATE.CLEAR).length}
          </div>
          <div style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Clear</div>
        </div>
        <div className="card" style={{ textAlign: 'center', padding: '1rem' }}>
          <div style={{ fontSize: '1.75rem', fontWeight: 800, color: 'var(--color-danger)' }}>
            {blockedCount}
          </div>
          <div style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Needs Retake</div>
        </div>
        <div className="card" style={{ textAlign: 'center', padding: '1rem' }}>
          <div style={{ fontSize: '1.75rem', fontWeight: 800, color: 'var(--color-accent)' }}>
            {results.filter(r => pageStates[r.sheet_id] === STATE.ACCEPTABLE).length}
          </div>
          <div style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Marked Acceptable</div>
        </div>
      </div>

      {/* Submit message */}
      {submitMessage.text && (
        <div className={`toast ${submitMessage.type === 'error' ? 'toast-error' : 'toast-success'}`} style={{ marginBottom: '1rem' }}>
          {submitMessage.text}
        </div>
      )}

      {/* Submit bar */}
      <div className="card" style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        background: canSubmit ? 'rgba(16,185,129,0.05)' : 'rgba(239,68,68,0.03)',
        border: `1px solid ${canSubmit ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.2)'}`,
      }}>
        <div>
          {canSubmit ? (
            <p style={{ color: 'var(--color-success)', fontWeight: 600, margin: 0 }}>
              ✓ Ready to submit bundle
            </p>
          ) : (
            <p style={{ color: 'var(--color-danger)', fontWeight: 600, margin: 0 }}>
              ⚠ {blockedCount} page{blockedCount !== 1 ? 's' : ''} still need attention
            </p>
          )}
          <p style={{ color: 'var(--text-secondary)', fontSize: 'var(--font-size-xs)', margin: '2px 0 0' }}>
            {canSubmit
              ? 'All pages reviewed. This action cannot be undone.'
              : 'Retake blurry pages or mark them as acceptable.'}
          </p>
        </div>
        <button
          className={`btn btn-lg ${canSubmit ? 'btn-success' : 'btn-secondary'}`}
          style={{ minWidth: '180px' }}
          onClick={handleSubmit}
          disabled={!canSubmit || submitting}
          id="submit-bundle-btn"
        >
          {submitting ? <LoadingSpinner size={20} /> : (canSubmit ? 'Submit Bundle →' : `${blockedCount} pages need attention`)}
        </button>
      </div>

      {/* Preview modal */}
      {previewSheet && (
        <PreviewModal sheet={previewSheet} onClose={() => setPreviewSheet(null)} />
      )}
    </div>
  )
}
