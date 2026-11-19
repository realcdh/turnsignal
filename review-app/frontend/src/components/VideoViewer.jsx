import { useRef, useState } from 'react'
import { fmtSec } from '../lib/format'

const SPEEDS = [0.25, 0.5, 1, 1.5, 2]
const FPS = 30 // 프레임 이동은 근사값 (영상별 fps 를 아직 서버에서 받지 않음)
const LOOP_PAD = 2 // 위반 시점 앞뒤 몇 초를 반복 재생할지

/**
 * 위반 클립 뷰어.
 *  - 재생속도(0.25x~2x), 프레임 단위 이동, 위반 구간 반복 재생
 *  - marker: 클립 안에서 AI 가 위반이라고 본 순간(초) → 타임라인에 표시
 *  - 부모에서 key={caseId} 로 감싸 케이스가 바뀌면 상태가 초기화되게 한다
 */
export default function VideoViewer({ src, downloadSrc, marker }) {
  const ref = useRef(null)
  const [duration, setDuration] = useState(0)
  const [time, setTime] = useState(0)
  const [speed, setSpeed] = useState(1)
  const [loop, setLoop] = useState(false)
  const [load, setLoad] = useState('loading') // loading | ready | error

  const seg = marker != null ? [Math.max(0, marker - LOOP_PAD), marker + LOOP_PAD] : null

  const onTimeUpdate = () => {
    const v = ref.current
    setTime(v.currentTime)
    if (loop && seg && v.currentTime >= seg[1]) v.currentTime = seg[0]
  }
  const changeSpeed = (s) => { setSpeed(s); ref.current.playbackRate = s }
  const step = (dir) => {
    const v = ref.current
    v.pause()
    v.currentTime = Math.min(Math.max(0, v.currentTime + dir / FPS), duration || v.duration)
  }
  const seek = (e) => {
    if (!duration) return
    const r = e.currentTarget.getBoundingClientRect()
    ref.current.currentTime = ((e.clientX - r.left) / r.width) * duration
  }
  const toggleLoop = () => {
    const next = !loop
    setLoop(next)
    if (next && seg) { ref.current.currentTime = seg[0]; ref.current.play() }
  }

  if (!src) return <div className="viewer-empty">클립 파일이 없습니다</div>

  return (
    <div className="viewer">
      <div className="video-wrap">
        {load === 'loading' && <div className="video-overlay">영상 불러오는 중…</div>}
        {load === 'error' && (
          <div className="video-overlay err">
            영상을 불러오지 못했습니다.
            <button className="btn small" onClick={() => { setLoad('loading'); ref.current.load() }}>다시 시도</button>
          </div>
        )}
        <video ref={ref} src={src} controls playsInline preload="metadata"
               onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
               onLoadedData={() => setLoad('ready')} onError={() => setLoad('error')}
               onTimeUpdate={onTimeUpdate} />
      </div>

      <div className="timeline" onClick={seek} title="클릭해서 이동">
        <div className="timeline-fill" style={{ width: duration ? `${(time / duration) * 100}%` : 0 }} />
        {seg && duration > 0 && (
          <div className="timeline-seg" style={{ left: `${(seg[0] / duration) * 100}%`, width: `${((seg[1] - seg[0]) / duration) * 100}%` }} />
        )}
        {marker != null && duration > 0 && (
          <div className="timeline-marker" style={{ left: `${(marker / duration) * 100}%` }} title={`AI 판정 시점 ${fmtSec(marker)}`} />
        )}
      </div>

      <div className="viewer-controls">
        <span className="time">{fmtSec(time)} / {fmtSec(duration)}</span>
        <div className="btn-group">
          <button className="btn small" onClick={() => step(-1)} title="1프레임 뒤로">◀ 1f</button>
          <button className="btn small" onClick={() => step(1)} title="1프레임 앞으로">1f ▶</button>
        </div>
        <div className="btn-group" role="group" aria-label="재생 속도">
          {SPEEDS.map((s) => (
            <button key={s} className={`btn small${speed === s ? ' on' : ''}`} onClick={() => changeSpeed(s)}>{s}x</button>
          ))}
        </div>
        {seg && (
          <button className={`btn small${loop ? ' on' : ''}`} onClick={toggleLoop}>위반 구간 반복</button>
        )}
        <a className="btn small" href={downloadSrc} download>클립 다운로드</a>
      </div>
    </div>
  )
}
