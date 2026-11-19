// 서버 통신 계층: 화면 컴포넌트는 fetch 를 직접 쓰지 않고 여기 함수만 호출한다.
// (더미 → 실서버 교체, 주소 변경이 이 파일 안에서만 일어나도록)

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status // 0 = 네트워크 단절
  }
}

async function request(path, options = {}) {
  let res
  try {
    res = await fetch(`/api${path}`, options)
  } catch {
    throw new ApiError('서버에 연결할 수 없습니다. 네트워크 또는 서버 상태를 확인해 주세요.', 0)
  }
  if (!res.ok) {
    let msg = `요청에 실패했습니다 (${res.status})`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') msg = body.detail
    } catch { /* 본문이 JSON 이 아니면 기본 문구 */ }
    throw new ApiError(msg, res.status)
  }
  return res.json()
}

const json = (method, body) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  listCases: (params) => request(`/cases?${params}`),
  getCase: (id) => request(`/cases/${id}`),
  changeStatus: (id, body) => request(`/cases/${id}/status`, json('PATCH', body)),
  addMemo: (id, body) => request(`/cases/${id}/memos`, json('POST', body)),
  clipUrl: (id, download = false) => `/api/cases/${id}/clip${download ? '?download=true' : ''}`,
  getStats: () => request('/stats'),
  getMeta: () => request('/meta'),
  uploadVideo: (file, region) => {
    const fd = new FormData()
    fd.append('file', file)
    if (region) fd.append('region', region)
    return request('/videos', { method: 'POST', body: fd })
  },
  getVideo: (id) => request(`/videos/${id}`),
}
