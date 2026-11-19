import { STATUS, TYPES, confidenceLevel } from '../lib/constants'

export function TypeBadge({ type }) {
  const t = TYPES[type] || { label: type, color: '#334155', bg: '#e2e8f0' }
  return <span className="badge" style={{ color: t.color, background: t.bg }}>{t.label}</span>
}

export function StatusBadge({ status }) {
  const s = STATUS[status] || STATUS.pending
  return <span className="badge" style={{ color: s.color, background: s.bg }}>{s.label}</span>
}

export function ConfidenceBadge({ value }) {
  const lv = confidenceLevel(value)
  return (
    <span className={`conf conf-${lv.key}`} title="엔진이 신뢰도를 제공하지 않아 판정 종류별 규칙으로 추정한 값입니다">
      {lv.label}{value != null && ` · ${Math.round(value * 100)}%`}
    </span>
  )
}
