import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from 'recharts'
import { api } from '../api/client'
import { ErrorState, Loading } from '../components/States'
import { useFetch } from '../hooks/useFetch'
import { STATUS, TYPES } from '../lib/constants'

// 통계 화면 뼈대. 지금은 서버가 집계한 값을 그대로 차트에 넣는다.
// (고규민 담당: 필터 연동 / 히트맵 / 집계 유틸은 여기서 확장)
export default function Statistics() {
  const { data: s, error, loading, reload } = useFetch(() => api.getStats(), [])
  if (loading && !s) return <Loading rows={4} />
  if (error) return <ErrorState error={error} onRetry={reload} />

  const byType = s.by_type.map((r) => ({ name: TYPES[r.type]?.label || r.type, n: r.n, fill: TYPES[r.type]?.color }))
  const byStatus = s.by_status.map((r) => ({ name: STATUS[r.status]?.label || r.status, n: r.n, fill: STATUS[r.status]?.color }))

  return (
    <div className="stats">
      <h2>통계</h2>
      <div className="kpis">
        <div className="kpi"><span>전체 케이스</span><b>{s.total}</b></div>
        <div className="kpi"><span>처리 완료</span><b>{s.processed}</b></div>
        <div className="kpi"><span>처리율</span><b>{Math.round(s.process_rate * 100)}%</b></div>
        <div className={`kpi${s.pending_over_7d ? ' warn' : ''}`}><span>7일 넘게 대기</span><b>{s.pending_over_7d}</b></div>
      </div>

      <div className="chart-grid">
        <div className="panel">
          <h3>위반 유형별 건수</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={byType}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="name" /><YAxis allowDecimals={false} /><Tooltip />
              <Bar dataKey="n" name="건수">{byType.map((d) => <Cell key={d.name} fill={d.fill || '#64748b'} />)}</Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="panel">
          <h3>처리 상태 분포</h3>
          <ResponsiveContainer width="100%" height={240}>
            <PieChart>
              <Pie isAnimationActive={false} data={byStatus} dataKey="n" nameKey="name" innerRadius={50} outerRadius={85} label>
                {byStatus.map((d) => <Cell key={d.name} fill={d.fill} />)}
              </Pie>
              <Legend /><Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="panel wide">
          <h3>일자별 발생 추이</h3>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={s.by_day}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="day" tickFormatter={(d) => d.slice(5)} /><YAxis allowDecimals={false} /><Tooltip />
              <Line isAnimationActive={false} type="monotone" dataKey="n" name="건수" stroke="#1d4ed8" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="panel wide">
          <h3>지역별 건수</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={s.by_region}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="region" /><YAxis allowDecimals={false} /><Tooltip />
              <Bar dataKey="n" name="건수" fill="#0f766e" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
