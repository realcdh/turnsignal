import { Link, useLocation, useParams } from 'react-router-dom'
import { api } from '../api/client'
import ActionPanel from '../components/ActionPanel'
import { ConfidenceBadge, StatusBadge, TypeBadge } from '../components/Badges'
import HistoryTimeline from '../components/HistoryTimeline'
import MemoPanel from '../components/MemoPanel'
import { ErrorState, Loading } from '../components/States'
import VideoViewer from '../components/VideoViewer'
import { useFetch } from '../hooks/useFetch'
import { fmtDateTime, fmtSec } from '../lib/format'

export default function CaseDetail() {
  const { id } = useParams()
  const location = useLocation()
  const back = `/cases${location.state?.search || ''}` // 목록으로 돌아가면 필터 상태 유지
  const { data: c, error, loading, reload, setData } = useFetch(() => api.getCase(id), [id])

  if (loading && !c) return <Loading rows={4} />
  if (error) return (<><Link to={back} className="back">← 목록으로</Link><ErrorState error={error} onRetry={reload} /></>)

  return (
    <div className="detail">
      <Link to={back} className="back">← 목록으로</Link>
      <div className="detail-title">
        <h2>케이스 #{c.id}</h2>
        <TypeBadge type={c.type} /> <StatusBadge status={c.status} />
      </div>

      <div className="detail-grid">
        <div>
          <VideoViewer key={c.id} src={c.has_clip ? api.clipUrl(c.id) : null}
                       downloadSrc={api.clipUrl(c.id, true)} marker={c.clip_start} />
        </div>

        <div className="detail-side">
          <div className="panel">
            <h3>AI 판정 정보</h3>
            <dl className="info">
              <dt>판정</dt><dd>{c.verdict}</dd>
              <dt>신뢰도(추정)</dt><dd><ConfidenceBadge value={c.confidence} /></dd>
              <dt>발생 일시</dt><dd>{fmtDateTime(c.occurred_at)}</dd>
              <dt>지역</dt><dd>{c.region || '-'}</dd>
              <dt>원본 영상 시점</dt><dd>{fmtSec(c.t_sec)}</dd>
              <dt>차량 ID</dt><dd>{c.vehicle_id ?? '-'}</dd>
            </dl>
            <h4>판정 근거</h4>
            <p className="desc">{c.description}</p>
            <p className="muted small">AI 판정은 참고용입니다. 승인 전에 영상을 직접 확인하세요.</p>
          </div>
          <ActionPanel caseData={c} onChanged={setData} />
        </div>
      </div>

      {c.siblings.length > 0 && (
        <div className="panel">
          <h3>같은 영상의 다른 위반 클립 ({c.siblings.length})</h3>
          <div className="sibling-list">
            {c.siblings.map((s) => (
              <Link key={s.id} to={`/cases/${s.id}`} state={location.state} className="sibling">
                <span>#{s.id}</span><TypeBadge type={s.type} /><span>{fmtSec(s.t_sec)}</span><StatusBadge status={s.status} />
              </Link>
            ))}
          </div>
        </div>
      )}

      <div className="two-col">
        <MemoPanel caseId={c.id} memos={c.memos} onChanged={setData} />
        <HistoryTimeline history={c.history} />
      </div>
    </div>
  )
}
