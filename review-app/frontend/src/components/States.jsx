// 로딩 · 에러 · 빈 화면 (네트워크 단절 / 서버 오류 / 404 를 구분해서 안내)

export function Loading({ rows = 6 }) {
  return (
    <div className="skeleton-list" aria-busy="true" aria-label="불러오는 중">
      {Array.from({ length: rows }).map((_, i) => <div key={i} className="skeleton" />)}
    </div>
  )
}

export function ErrorState({ error, onRetry }) {
  const status = error?.status
  let title = '문제가 발생했습니다'
  if (status === 0) title = '서버에 연결할 수 없습니다'
  else if (status === 404) title = '존재하지 않는 항목입니다'
  else if (status >= 500) title = '서버 오류가 발생했습니다'
  return (
    <div className="state-box error">
      <h3>{title}</h3>
      <p>{error?.message}</p>
      {status !== 404 && onRetry && <button className="btn" onClick={onRetry}>다시 시도</button>}
    </div>
  )
}

export function Empty({ title, children }) {
  return (
    <div className="state-box">
      <h3>{title}</h3>
      {children}
    </div>
  )
}
