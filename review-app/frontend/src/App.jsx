import { Link, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import CaseDetail from './pages/CaseDetail'
import CaseList from './pages/CaseList'
import Statistics from './pages/Statistics'
import Upload from './pages/Upload'

// 공통 레이아웃(사이드바·상단바)을 감싸는 상위 라우트 → 이후 로그인/권한 라우트를 이 위에 얹기 쉬움
export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/cases" replace />} />
        <Route path="cases" element={<CaseList />} />
        <Route path="cases/:id" element={<CaseDetail />} />
        <Route path="statistics" element={<Statistics />} />
        <Route path="upload" element={<Upload />} />
        <Route path="*" element={<div className="state-box"><h3>페이지를 찾을 수 없습니다</h3><Link to="/cases" className="btn">목록으로</Link></div>} />
      </Route>
    </Routes>
  )
}
