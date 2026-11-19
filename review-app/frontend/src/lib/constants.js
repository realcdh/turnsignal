// 디자인 시스템(2주차): 위반 유형 색상과 처리 상태 색상을 분리해서 정의
export const TYPES = {
  signal_violation: { label: '신호위반', color: '#b91c1c', bg: '#fee2e2' },
  lane_change_no_signal: { label: '깜빡이 미점등 차선변경', color: '#a16207', bg: '#fef3c7' },
}
// 아직 엔진에 없는 유형 (계획서 4종 중 나머지) — 필터에는 노출하지 않음
export const TYPES_PLANNED = ['정지선 위반 이륜차', '안전거리 미확보']

export const STATUS = {
  pending: { label: '대기', color: '#475569', bg: '#e2e8f0' },
  approved: { label: '승인', color: '#15803d', bg: '#dcfce7' },
  rejected: { label: '반려', color: '#b91c1c', bg: '#fee2e2' },
  held: { label: '보류', color: '#1d4ed8', bg: '#dbeafe' },
}

export const REGIONS = ['강남구', '서초구', '송파구', '마포구', '영등포구', '성동구', '강서구', '노원구']

export const PERIODS = [
  { value: '', label: '전체 기간' },
  { value: '1', label: '오늘' },
  { value: '7', label: '최근 7일' },
  { value: '30', label: '최근 30일' },
]

export const SORTS = [
  { value: 'priority', label: '우선순위순' },
  { value: 'confidence', label: '신뢰도순' },
  { value: 'newest', label: '최신순' },
  { value: 'oldest', label: '오래된순' },
]

// 엔진이 신뢰도를 주지 않아 서버가 규칙 기반 추정값을 넣고 있음 → 화면에도 '추정'으로 표기
export function confidenceLevel(c) {
  if (c == null) return { label: '-', key: 'none' }
  if (c >= 0.85) return { label: '높음', key: 'high' }
  if (c >= 0.65) return { label: '보통', key: 'mid' }
  return { label: '낮음', key: 'low' }
}
