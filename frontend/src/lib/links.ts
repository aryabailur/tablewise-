/** /r/:slug deep link that opens the booking panel on a given night, party size and seating. */
export function restaurantLink(slug: string, opts: { date?: string | null; party?: number | null; time?: string | null; book?: boolean } = {}) {
  const u = new URLSearchParams();
  if (opts.date) u.set('date', opts.date);
  if (opts.party) u.set('party', String(opts.party));
  if (opts.time) u.set('time', opts.time);
  const q = u.toString();
  return `/${opts.book ? 'book' : 'r'}/${encodeURIComponent(slug)}${q ? `?${q}` : ''}${opts.time ? '#reserve' : ''}`;
}
