import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import FilterPanel from '../components/FilterPanel'
import { ConfidenceBadge, StatusBadge, TypeBadge } from '../components/Badges'
import { Empty, ErrorState, Loading } from '../components/States'
import { useFetch } from '../hooks/useFetch'
import { PERIODS, STATUS, TYPES } from '../lib/constants'
import { daysAgo, fmtDateTime } from '../lib/format'

const SIZE = 20

export default function CaseList() {
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const query = params.toString()

  // 필터·정렬·페이지는 전부 URL 쿼리에 저장 → 상세에 갔다 와도 유지되고 링크로 공유 가능
  const update = (patch) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) {
      next.delete(k)
      if (Array.isArray(v)) v.forEach((x) => next.append(k, x))
      else if (v) next.set(k, v)
    }
    if (!('page' in patch)) next.delete('page') // 조건이 바뀌면 1페이지부터
    setParams(next, { replace: true })
  }

  const { data, error, loading, reload } = useFetch(() => {
    const q = new URLSearchParams(params)
    q.set('size', SIZE)
    return api.listCases(q)
  }, [query])

  const tags = [
    ...params.getAll('type').map((v) => ({ key: 'type', v, label: TYPES[v]?.label || v })),
    ...params.getAll('status').map((v) => ({ key: 'status', v, label: STATUS[v]?.label || v })),
    ...params.getAll('region').map((v) => ({ key: 'region', v, label: v })),
    ...(params.get('days') ? [{ key: 'days', v: params.get('days'), label: PERIODS.find((p) => p.value === params.get('days'))?.label }] : []),
    ...(params.get('q') ? [{ key: 'q', v: params.get('q'), label: `검색: ${params.get('q')}` }] : []),
  ]
  const removeTag = (t) => update({ [t.key]: t.key === 'days' || t.key === 'q' ? '' : params.getAll(t.key).filter((x) => x !== t.v) })
  const reset = () => update({ type: [], status: [], region: [], days: '', q: '' })

  const page = Number(params.get('page') || 1)
  const pages = data ? Math.max(1, Math.ceil(data.total / SIZE)) : 1

  return (
    <div className="list-layout">
      <FilterPanel params={params} update={update} />

      <section className="list-main">
        <div className="list-head">
          <h2>케이스 목록 {data && <small>{data.total.toLocaleString()}건</small>}</h2>
          {tags.length > 0 && (
            <div className="tags">
              {tags.map((t) => (
                <button key={`${t.key}-${t.v}`} className="tag" onClick={() => removeTag(t)} title="조건 해제">{t.label} ✕</button>
              ))}
              <button className="link-btn" onClick={reset}>전체 초기화</button>
            </div>
          )}
        </div>

        {loading && !data && <Loading />}
        {error && <ErrorState error={error} onRetry={reload} />}
        {data && data.items.length === 0 && (
          <Empty title="조건에 맞는 케이스가 없습니다">
            {tags.length > 0 && <button className="btn" onClick={reset}>필터 초기화</button>}
          </Empty>
        )}

        {data && data.items.length > 0 && (
          <>
            <div className={`table${loading ? ' dim' : ''}`}>
              <div className="row head">
                <span>번호</span><span>위반 유형</span><span>판정</span><span>발생 일시</span>
                <span>지역</span><span>신뢰도(추정)</span><span>상태</span>
              </div>
              {data.items.map((c) => {
                const stale = c.status === 'pending' && daysAgo(c.occurred_at) >= 7
                return (
                  <Link key={c.id} to={`/cases/${c.id}`} state={{ search: location.search }} className={`row${stale ? ' stale' : ''}`}>
                    <span>#{c.id}</span>
                    <span><TypeBadge type={c.type} /></span>
                    <span className="ellipsis">{c.verdict}</span>
                    <span>{fmtDateTime(c.occurred_at)}{stale && <em className="stale-flag">7일+ 대기</em>}</span>
                    <span>{c.region || '-'}</span>
                    <span><ConfidenceBadge value={c.confidence} /></span>
                    <span><StatusBadge status={c.status} /></span>
                  </Link>
                )
              })}
            </div>

            <div className="pager">
              <button className="btn small" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}>이전</button>
              <span>{page} / {pages}</span>
              <button className="btn small" disabled={page >= pages} onClick={() => update({ page: String(page + 1) })}>다음</button>
            </div>
          </>
        )}
      </section>
    </div>
  )
}
