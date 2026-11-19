import { NavLink, Outlet } from 'react-router-dom'
import { api } from '../api/client'
import { useFetch } from '../hooks/useFetch'

const NAV = [
  { to: '/cases', label: '케이스 목록' },
  { to: '/statistics', label: '통계' },
  { to: '/upload', label: '영상 업로드' },
]

export default function Layout() {
  const { data: meta } = useFetch(() => api.getMeta(), [])
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">교통 위반 검토</div>
        <nav>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot" title={meta?.engine_reason || ''}>
          <span className={`dot ${meta?.engine_available ? 'on' : 'off'}`} />
          {meta ? (meta.engine_available ? 'AI 엔진 연결됨' : 'AI 엔진 없음 (시연 데이터)') : '확인 중…'}
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className="topbar-title">AI 분석 결과 검토 대시보드</span>
          <span className="topbar-user">담당자</span>
        </header>
        <main className="content"><Outlet /></main>
      </div>
    </div>
  )
}
