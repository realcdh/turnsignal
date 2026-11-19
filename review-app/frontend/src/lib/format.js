export function fmtDateTime(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export function fmtSec(s) {
  if (s == null || Number.isNaN(s)) return '--:--'
  const m = Math.floor(s / 60)
  const r = (s % 60).toFixed(1).padStart(4, '0')
  return `${String(m).padStart(2, '0')}:${r}`
}

export function daysAgo(iso) {
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86400000)
}
