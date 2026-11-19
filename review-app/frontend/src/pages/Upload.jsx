import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { REGIONS } from '../lib/constants'

// 영상 업로드 → 서버가 백그라운드로 분석 → 2초마다 진행 상태를 확인(폴링)
export default function Upload() {
  const [file, setFile] = useState(null)
  const [region, setRegion] = useState('')
  const [job, setJob] = useState(null) // 서버가 돌려준 video 상태
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const timer = useRef(null)

  useEffect(() => () => clearInterval(timer.current), [])

  const poll = (id) => {
    clearInterval(timer.current)
    timer.current = setInterval(async () => {
      try {
        const v = await api.getVideo(id)
        setJob(v)
        if (v.status === 'done' || v.status === 'error') clearInterval(timer.current)
      } catch (e) {
        setError(e.message)
        clearInterval(timer.current)
      }
    }, 2000)
  }

  const submit = async (e) => {
    e.preventDefault()
    if (!file) return
    setBusy(true); setError(null); setJob(null)
    try {
      const { id } = await api.uploadVideo(file, region)
      setJob({ id, status: 'queued', progress: 0, filename: file.name })
      poll(id)
    } catch (err) {
      setError(err.message) // 엔진 미설치(503), 형식 오류(415) 등 서버 사유를 그대로 보여줌
    } finally {
      setBusy(false)
    }
  }

  const label = { queued: '대기 중', running: '분석 중', done: '완료', error: '오류' }

  return (
    <div className="upload">
      <h2>영상 업로드</h2>
      <p className="muted">블랙박스 영상을 올리면 AI가 신호위반·깜빡이 미점등 차선변경을 찾아 케이스로 등록합니다. (영상 1분당 1~10분 소요)</p>
      <form onSubmit={submit} className="panel upload-form">
        <label className="field">
          <span>영상 파일 (mp4, mov, avi, mkv)</span>
          <input type="file" accept="video/*,.mkv" onChange={(e) => setFile(e.target.files[0] || null)} />
        </label>
        <label className="field">
          <span>지역 (선택)</span>
          <select value={region} onChange={(e) => setRegion(e.target.value)}>
            <option value="">선택 안 함</option>
            {REGIONS.map((r) => <option key={r}>{r}</option>)}
          </select>
        </label>
        <button className="btn primary" disabled={!file || busy}>{busy ? '업로드 중…' : '업로드 및 분석 시작'}</button>
      </form>

      {error && <p className="form-error">{error}</p>}

      {job && (
        <div className="panel">
          <h3>{job.filename}</h3>
          <div className="progress"><div style={{ width: `${Math.round((job.progress || 0) * 100)}%` }} /></div>
          <p>{label[job.status]} {job.status === 'running' && `· ${Math.round((job.progress || 0) * 100)}%`}</p>
          {job.message && <p className="muted">{job.message}</p>}
          {job.status === 'done' && <Link className="btn primary" to="/cases?sort=newest">케이스 목록 보기</Link>}
        </div>
      )}
    </div>
  )
}
