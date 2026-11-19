import { fmtDateTime } from '../lib/format'
import { StatusBadge } from './Badges'

export default function HistoryTimeline({ history }) {
  return (
    <div className="panel">
      <h3>처리 이력</h3>
      {history.length === 0 ? <p className="muted">아직 처리 이력이 없습니다.</p> : (
        <ol className="timeline-list">
          {history.map((h) => (
            <li key={h.id}>
              <div className="tl-head">
                {h.from_status && <><StatusBadge status={h.from_status} /> → </>}
                <StatusBadge status={h.to_status} />
              </div>
              <div className="muted">{h.actor} · {fmtDateTime(h.at)}</div>
              {h.reason && <div>{h.reason}</div>}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
