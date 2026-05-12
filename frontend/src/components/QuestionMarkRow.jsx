/**
 * QuestionMarkRow
 *
 * A single row in the right panel for one question part.
 * Shows: status dot, question label, max marks, −/input/+ controls, clear button.
 *
 * Props:
 *   questionId        — string (composite key e.g. "Q1_1a_i")
 *   label             — string (display label e.g. "Q1 · 1a · i")
 *   maxMarks          — number
 *   placement         — { value, page, xPercent, yPercent } | null | undefined
 *   isActive          — boolean — true if this is the currently selected question
 *   onClick(source?)  — called when row is clicked (sets active). source='tab' for Tab key.
 *   onIncrement()     — called when + clicked
 *   onDecrement()     — called when − clicked
 *   onClear()         — called when ✕ clicked (resets to unattempted)
 *   onManualInput(v)  — called when teacher types directly in the input
 */
import { useRef, useEffect } from 'react'

export default function QuestionMarkRow({
  questionId, label, maxMarks,
  placement, isActive,
  onClick, onIncrement, onDecrement, onClear, onManualInput,
  disabled = false,
}) {
  const inputRef = useRef(null)
  const value    = placement?.value ?? null
  const isMarked = placement !== null && placement !== undefined
  const isZero   = isMarked && value === 0
  const atMax    = isMarked && value >= maxMarks
  const atMin    = isMarked && value <= 0

  // Auto-focus input when row becomes active
  useEffect(() => {
    if (isActive && inputRef.current) {
      inputRef.current.focus({ preventScroll: true })
    }
  }, [isActive])

  // Dot color
  const dotColor = !isMarked ? '#CBD5E0'
                 : isZero    ? '#E24B4A'
                 : '#1D9E75'

  // Input style
  const inputBg    = !isMarked ? '#FFFFFF'
                   : isZero    ? '#FCEBEB'
                   : '#EAF3DE'
  const inputColor = !isMarked ? '#94A3B8'
                   : isZero    ? '#791F1F'
                   : '#27500A'

  const handleKeyDown = (e) => {
    if (disabled) return
    if (e.key === 'Tab') {
      e.preventDefault()
      // Parent handles Tab navigation
      onClick?.('tab')
    }
    if (e.key === 'ArrowUp')   { e.preventDefault(); onIncrement?.() }
    if (e.key === 'ArrowDown') { e.preventDefault(); onDecrement?.() }
  }

  const handleInputChange = (e) => {
    if (disabled) return
    const raw = e.target.value
    if (raw === '' || raw === '—') {
      onClear?.()
      return
    }
    const parsed = parseFloat(raw)
    if (isNaN(parsed)) return
    if (parsed < 0 || parsed > maxMarks) return
    // Round to nearest 0.5 to allow half marks
    const rounded = Math.round(parsed * 2) / 2
    onManualInput?.(rounded)
  }

  return (
    <div
      onClick={() => !disabled && onClick?.()}
      style={{
        display: 'flex',
        alignItems: 'center',
        padding: '12px 16px',
        borderBottom: '1px solid var(--border-light)',
        borderLeft: isActive ? '3px solid #1D9E75' : '3px solid transparent',
        background: isActive ? '#E1F5EE' : '#FFFFFF',
        cursor: disabled ? 'default' : 'pointer',
        gap: '10px',
        transition: 'background 0.1s ease',
        opacity: disabled ? 0.6 : 1,
        pointerEvents: disabled ? 'none' : 'auto',
      }}
    >
      {/* Status dot */}
      <div style={{
        width: '9px',
        height: '9px',
        borderRadius: '50%',
        background: dotColor,
        flexShrink: 0,
        transition: 'background 0.15s ease',
      }} />

      {/* Question label */}
      <span style={{
        fontSize: '14px',
        fontWeight: '500',
        color: isActive ? '#085041' : 'var(--text-primary)',
        flex: 1,
        minWidth: 0,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
      }}>
        {label}
      </span>

      {/* Max marks */}
      <span style={{
        fontSize: '13px',
        color: 'var(--text-muted)',
        flexShrink: 0,
      }}>
        / {maxMarks}
      </span>

      {/* − / input / + controls */}
      <div
        style={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}
        onClick={e => e.stopPropagation()}
      >
        {/* Decrement button */}
        <button
          onClick={disabled ? undefined : onDecrement}
          disabled={disabled || !isMarked || atMin}
          style={{
            width: '30px', height: '30px',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            border: '1px solid var(--border-color)',
            borderRight: 'none',
            borderRadius: '5px 0 0 5px',
            background: 'var(--bg-primary)',
            color: (!isMarked || atMin) ? 'var(--text-muted)' : 'var(--text-primary)',
            cursor: (!isMarked || atMin) ? 'not-allowed' : 'pointer',
            fontSize: '16px',
            fontWeight: '600',
            opacity: (!isMarked || atMin) ? 0.35 : 1,
            lineHeight: 1,
            transition: 'opacity 0.1s ease',
          }}
        >
          −
        </button>

        {/* Value input */}
        <input
          ref={inputRef}
          type="number"
          min={0}
          max={maxMarks}
          step={0.5}
          value={isMarked ? value : ''}
          placeholder="—"
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onClick={e => e.stopPropagation()}
          readOnly={disabled}
          style={{
            width: '46px',
            height: '30px',
            textAlign: 'center',
            fontSize: '14px',
            fontWeight: '700',
            border: 'none',
            borderTop: '1px solid var(--border-color)',
            borderBottom: '1px solid var(--border-color)',
            borderRadius: 0,
            background: inputBg,
            color: inputColor,
            outline: 'none',
            MozAppearance: 'textfield',
            WebkitAppearance: 'none',
            fontFamily: 'var(--font-family)',
            transition: 'background 0.15s ease, color 0.15s ease',
          }}
        />

        {/* Increment button */}
        <button
          onClick={disabled ? undefined : onIncrement}
          disabled={disabled || atMax}
          style={{
            width: '30px', height: '30px',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            border: '1px solid var(--border-color)',
            borderLeft: 'none',
            borderRadius: '0 5px 5px 0',
            background: 'var(--bg-primary)',
            color: atMax ? 'var(--text-muted)' : 'var(--text-primary)',
            cursor: atMax ? 'not-allowed' : 'pointer',
            fontSize: '16px',
            fontWeight: '600',
            opacity: atMax ? 0.35 : 1,
            lineHeight: 1,
            transition: 'opacity 0.1s ease',
          }}
        >
          +
        </button>
      </div>

      {/* Clear button — only active when question has a placement */}
      <button
        onClick={(e) => { e.stopPropagation(); if (!disabled) onClear?.() }}
        style={{
          background: 'none',
          border: 'none',
          fontSize: '14px',
          color: 'var(--text-muted)',
          cursor: isMarked ? 'pointer' : 'default',
          opacity: isMarked ? 0.7 : 0.15,
          padding: '0 0 0 4px',
          pointerEvents: isMarked ? 'auto' : 'none',
          flexShrink: 0,
          transition: 'opacity 0.1s ease',
        }}
        title={isMarked ? 'Clear — mark as unattempted' : ''}
      >
        ✕
      </button>
    </div>
  )
}
