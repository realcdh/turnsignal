import { useReducer } from 'react'
import { api } from '../api/client'
import { STATUS } from '../lib/constants'

const ACTIONS = [
  { to: 'approved', label: '승인', cls: 'approve' },
  { to: 'rejected', label: '반려', cls: 'reject', reason: true },
  { to: 'held', label: '보류', cls: 'hold', reason: true },
]

// 처리 흐름: idle → confirming(확인 모달) → submitting → idle(성공) / confirming(실패, 에러 표시)
function reducer(s, a) {
  switch (a.type) {
    case 'open': return { phase: 'confirming', target: a.target, reason: '', error: null }
    case 'reason': return { ...s, reason: a.value, error: null }
    case 'submit': return { ...s, phase: 'submitting', error: null }
    case 'fail': return { ...s, phase: 'confirming', error: a.error }
    case 'close': return { phase: 'idle', target: null, reason: '', error: null }
    default: return s
  }
}

export default function ActionPanel({ caseData, onChanged }) {
  const [s, dispatch] = useReducer(reducer, { phase: 'idle', target: null, reason: '', error: null })
  const current = caseData.status
  const needReason = s.target?.reason
  const canSubmit = s.phase === 'confirming' && (!needReason || s.reason.trim())

  const submit = async () => {
    dispatch({ type: 'submit' })
    try {
      const updated = await api.changeStatus(caseData.id, { status: s.target.to, reason: s.reason })
      dispatch({ type: 'close' })
      onChanged(updated)
    } catch (e) {
      dispatch({ type: 'fail', error: e.message }) // 실패하면 상태는 그대로 두고 사유만 보여줌
    }
  }

  return (
    <div className="panel">
      <h3>처리</h3>
      <div className="action-row">
        {ACTIONS.filter((a) => a.to !== current).map((a) => (
          <button key={a.to} className={`btn action ${a.cls}`} onClick={() => dispatch({ type: 'open', target: a })}>
            {a.label}
          </button>
        ))}
        {current !== 'pending' && (
          <button className="btn" onClick={() => dispatch({ type: 'open', target: { to: 'pending', label: '대기로 되돌리기' } })}>
            대기로 되돌리기
          </button>
        )}
      </div>

      {s.phase !== 'idle' && (
        <div className="modal-backdrop" onClick={() => s.phase === 'confirming' && dispatch({ type: 'close' })}>
          <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <h3>케이스 #{caseData.id} — {s.target.label}</h3>
            <p className="muted">
              현재 상태 <b>{STATUS[current].label}</b> → <b>{STATUS[s.target.to].label}</b> 로 변경합니다.
            </p>
            {needReason && (
              <label className="field">
                <span>사유 (필수)</span>
                <textarea rows={3} autoFocus value={s.reason} placeholder="처리 사유를 입력하세요"
                          onChange={(e) => dispatch({ type: 'reason', value: e.target.value })} />
              </label>
            )}
            {s.error && <p className="form-error">{s.error}</p>}
            <div className="modal-actions">
              <button className="btn" disabled={s.phase === 'submitting'} onClick={() => dispatch({ type: 'close' })}>취소</button>
              <button className="btn primary" disabled={!canSubmit} onClick={submit}>
                {s.phase === 'submitting' ? '처리 중…' : '확인'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
