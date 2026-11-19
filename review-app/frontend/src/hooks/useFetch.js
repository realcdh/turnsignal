import { useCallback, useEffect, useRef, useState } from 'react'

// 로딩 · 에러 · 재시도를 한 곳에서 처리하는 훅.
// fn 은 useCallback 등으로 안정화하거나, deps 배열로 다시 요청할 조건을 넘긴다.
export function useFetch(fn, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const seq = useRef(0) // 늦게 도착한 이전 응답이 최신 화면을 덮어쓰지 않도록

  const run = useCallback(() => {
    const my = ++seq.current
    setState((s) => ({ ...s, loading: true, error: null }))
    fn()
      .then((data) => my === seq.current && setState({ data, error: null, loading: false }))
      .catch((error) => my === seq.current && setState({ data: null, error, loading: false }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => { run() }, [run])
  return { ...state, reload: run, setData: (data) => setState((s) => ({ ...s, data })) }
}
