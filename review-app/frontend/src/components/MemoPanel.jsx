import { useState } from 'react'
import { api } from '../api/client'
import { fmtDateTime } from '../lib/format'

export default function MemoPanel({ caseId, memos, onChanged }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const add = async (e) => {
    e.preventDefault()
    if (!text.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      onChanged(await api.addMemo(caseId, { body: text }))
      setText('')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel">
      <h3>메모 · 사유</h3>
      <form onSubmit={add} className="memo-form">
        <textarea rows={2} value={text} placeholder="담당자 메모를 남기세요" onChange={(e) => setText(e.target.value)} />
        <button className="btn primary" disabled={!text.trim() || busy}>{busy ? '저장 중…' : '메모 추가'}</button>
      </form>
      {error && <p className="form-error">{error}</p>}
      {memos.length === 0 ? <p className="muted">작성된 메모가 없습니다.</p> : (
        <ul className="memo-list">
          {memos.map((m) => (
            <li key={m.id} className={m.kind === 'reason' ? 'reason' : ''}>
              <div className="memo-meta">
                <b>{m.kind === 'reason' ? '처리 사유' : '메모'}</b> · {m.actor} · {fmtDateTime(m.at)}
              </div>
              <div>{m.body}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
