import { useEffect, useState } from 'react'
import { PERIODS, REGIONS, SORTS, STATUS, TYPES } from '../lib/constants'

// 필터 값은 전부 URL 쿼리(searchParams)에 들어 있다. 이 컴포넌트는 값을 읽고 바꾸기만 한다.
// (통계 화면에서도 같은 컴포넌트를 쓸 수 있도록 상태를 내부에 두지 않음)
export default function FilterPanel({ params, update }) {
  const urlQ = params.get('q') || ''
  const [q, setQ] = useState(urlQ)
  useEffect(() => { setQ(urlQ) }, [urlQ])                       // 필터 초기화 등 URL 변경 반영
  useEffect(() => {
    if (q === urlQ) return undefined
    const t = setTimeout(() => update({ q }), 300)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q])

  const multi = (key) => params.getAll(key)
  const toggle = (key, value) => {
    const cur = multi(key)
    update({ [key]: cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value] })
  }

  return (
    <aside className="filter-panel">
      <label className="field">
        <span>검색</span>
        <input type="search" placeholder="판정 내용 · 케이스 번호" value={q}
               onChange={(e) => setQ(e.target.value)} />
      </label>

      <fieldset>
        <legend>위반 유형</legend>
        {Object.entries(TYPES).map(([k, v]) => (
          <label key={k} className="check">
            <input type="checkbox" checked={multi('type').includes(k)} onChange={() => toggle('type', k)} />
            {v.label}
          </label>
        ))}
      </fieldset>

      <fieldset>
        <legend>처리 상태</legend>
        {Object.entries(STATUS).map(([k, v]) => (
          <label key={k} className="check">
            <input type="checkbox" checked={multi('status').includes(k)} onChange={() => toggle('status', k)} />
            {v.label}
          </label>
        ))}
      </fieldset>

      <label className="field">
        <span>기간</span>
        <select value={params.get('days') || ''} onChange={(e) => update({ days: e.target.value })}>
          {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
      </label>

      <fieldset>
        <legend>지역</legend>
        <div className="chips">
          {REGIONS.map((r) => (
            <button key={r} type="button" className={`chip${multi('region').includes(r) ? ' on' : ''}`}
                    onClick={() => toggle('region', r)}>{r}</button>
          ))}
        </div>
      </fieldset>

      <label className="field">
        <span>정렬</span>
        <select value={params.get('sort') || 'priority'} onChange={(e) => update({ sort: e.target.value })}>
          {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
      </label>
    </aside>
  )
}
