export const pad = (n: number) => String(n).padStart(2, '0');
export const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export const toISODate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export function parseISODate(s: string): Date {
  const [y, m, d] = s.slice(0, 10).split('-').map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}
/** Naive local ISO datetime ("2026-10-12T20:00:00") parsed as local time. */
export function parseLocal(s: string): Date {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(s);
  return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) : new Date(s);
}
export const hhmm = (iso: string) => {
  const d = parseLocal(iso);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
export const formatDay = (isoDate: string) => {
  const d = parseISODate(isoDate);
  return `${WEEKDAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
};
export function nextDays(n: number): Date[] {
  const t = new Date();
  return Array.from({ length: n }, (_, i) => new Date(t.getFullYear(), t.getMonth(), t.getDate() + i));
}
