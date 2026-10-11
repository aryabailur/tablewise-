import { useCallback, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { ChevronLeft, ChevronRight, CircleAlert, Store, Users } from 'lucide-react';
import type { Booking, BookingStatus, Table } from '../lib/types';
import { BOOKING_CHANGED, cancelBooking, errorMessage, getTables, lastBooking, listBookings, notifyBookingsChanged, updateBooking } from '../lib/api';
import { formatDay, parseISODate, parseLocal, toISODate } from '../lib/time';
import { ZONE_ORDER, zoneColor, zoneLabel } from '../lib/zones';
import { useAllRestaurants } from '../lib/restaurants';
import { STATUSES, STATUS_LABEL, hasAllergies, isCelebration, statusColor, statusOf } from '../lib/booking';
import BookingDrawer from './BookingDrawer';

const DEFAULT_SLUG = 'ember-vine';
const toMin = (hm: string | undefined, fallback: number) => {
  const m = /^(\d{1,2}):(\d{2})/.exec(hm ?? '');
  return m ? +m[1] * 60 + +m[2] : fallback;
};
const mins = (iso: string) => {
  const d = parseLocal(iso);
  return d.getHours() * 60 + d.getMinutes();
};
const endOf = (b: Booking) => (b.end_time ? mins(b.end_time) : mins(b.start_time) + (b.duration_min || 90));

/** The visible window of the timeline, derived from the restaurant's opening hours. */
interface Span { start: number; end: number }
const pctIn = (sp: Span, m: number) => `${((Math.min(sp.end, Math.max(sp.start, m)) - sp.start) / (sp.end - sp.start)) * 100}%`;

/** Open on the night of the most recent booking if it's still upcoming, otherwise tonight. */
function initialDate(): string {
  const today = toISODate(new Date());
  const day = lastBooking()?.start_time.slice(0, 10);
  return day && day >= today ? day : today;
}
function initialSlug(): string {
  const q = new URLSearchParams(window.location.search).get('restaurant');
  return q || lastBooking()?.restaurant_slug || DEFAULT_SLUG;
}

interface BarActions { highlight: string | null; selected: string | null; onOpen: (code: string) => void }

function Bar({ b, span, actions }: { b: Booking; span: Span; actions: BarActions }) {
  const st = mins(b.start_time);
  const en = endOf(b);
  const status = statusOf(b);
  const cancelled = status === 'cancelled';
  const faded = cancelled || status === 'no_show';
  const color = statusColor(status);
  const { highlight, selected, onOpen } = actions;
  const allergy = hasAllergies(b);
  const party = isCelebration(b);
  return (
    <motion.button
      type="button"
      onClick={() => onOpen(b.code)}
      initial={{ opacity: 0, scaleX: 0.6 }}
      animate={{ opacity: faded ? 0.6 : 1, scaleX: 1 }}
      aria-label={`${b.guest_name}, ${b.party_size} guests, ${STATUS_LABEL[status]}, ${b.code}${allergy ? ', has allergies' : ''}. Open details`}
      title={`${b.guest_name} · ${b.party_size} guests · ${b.code} · ${STATUS_LABEL[status]}${b.source ? ` · via ${b.source}` : ''}${allergy ? ` · allergies: ${b.allergies?.join(', ')}` : ''}`}
      className={`absolute inset-y-1.5 flex cursor-pointer items-center gap-2 overflow-hidden rounded-xl border px-2.5 text-left text-xs text-fg outline-none transition-[filter] hover:brightness-125 focus-visible:ring-2 focus-visible:ring-[var(--ember)] ${cancelled ? 'bar-cancelled z-0 line-through' : 'z-10'} ${highlight === b.code || selected === b.code ? 'ring-2 ring-[var(--ember)] shadow-[0_0_18px_var(--ember)]' : ''}`}
      style={{
        left: pctIn(span, st),
        width: `calc(${pctIn(span, en)} - ${pctIn(span, st)})`,
        transformOrigin: 'left center',
        borderColor: `color-mix(in oklab, ${color} 60%, transparent)`,
        ...(cancelled ? {} : { background: `linear-gradient(90deg, color-mix(in oklab, ${color} 34%, transparent), color-mix(in oklab, ${color} 12%, transparent))` }),
      }}
    >
      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} aria-hidden />
      {allergy && (
        <span className="shrink-0 text-sm leading-none" aria-hidden title="Allergies">
          ⚠️
        </span>
      )}
      {party && (
        <span className="shrink-0 text-sm leading-none" aria-hidden title={b.occasion === 'birthday' ? 'Birthday' : 'Anniversary'}>
          🎂
        </span>
      )}
      <span className="truncate font-semibold">{b.guest_name}</span>
      <span className="flex shrink-0 items-center gap-0.5 text-fg/80">
        <Users className="h-3 w-3" />
        {b.party_size}
      </span>
      <span className="ml-auto shrink-0 font-mono text-xs text-fg/85">{b.code}</span>
    </motion.button>
  );
}

function Row({ label, sub, items, span, cols, actions }: { label: string; sub?: string; items: Booking[]; span: Span; cols: number; actions: BarActions }) {
  return (
    <div className="flex border-b border-line last:border-b-0">
      <div className="w-28 shrink-0 px-4 py-3">
        <div className="font-display text-base leading-none text-fg">{label}</div>
        {sub && <div className="mt-1 text-xs text-fg/75">{sub}</div>}
      </div>
      <div className="relative h-14 flex-1" style={{ backgroundImage: 'linear-gradient(to right, var(--line) 1px, transparent 1px)', backgroundSize: `${100 / cols}% 100%` }}>
        {items.map((b) => (
          <Bar key={b.code} b={b} span={span} actions={actions} />
        ))}
      </div>
    </div>
  );
}

export default function AdminTimeline() {
  const { restaurants } = useAllRestaurants();
  const [slug, setSlug] = useState(initialSlug);
  const [date, setDate] = useState(initialDate);
  const [highlight, setHighlight] = useState<string | null>(() => lastBooking()?.code ?? null);
  const [upcoming, setUpcoming] = useState<{ slug: string; days: [string, number][] }>({ slug: '', days: [] });
  const [tablesState, setTablesState] = useState<{ slug: string; tables: Table[] }>({ slug: '', tables: [] });
  const [data, setData] = useState<{ key: string; bookings: Booking[]; error: string | null }>({ key: '', bookings: [], error: null });
  const [actionError, setActionError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [showCancelled, setShowCancelled] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [drawerError, setDrawerError] = useState<string | null>(null);

  const restaurant = restaurants.find((r) => r.slug === slug) ?? null;
  const open = toMin(restaurant?.hours_open, 17 * 60);
  let close = toMin(restaurant?.hours_close, 23 * 60 + 30);
  if (close <= open) close = 24 * 60;
  const spanStart = Math.floor(open / 60) * 60;
  const span: Span = { start: spanStart, end: Math.max(spanStart + 60, Math.min(24 * 60, Math.ceil(close / 30) * 30)) };
  const SPAN = span.end - span.start;
  const hours: number[] = [];
  for (let h = span.start / 60; h * 60 < span.end; h++) hours.push(h);
  const cols = SPAN / 30;

  // Keep the URL shareable (?restaurant=slug) without adding history entries.
  useEffect(() => {
    const u = new URL(window.location.href);
    u.searchParams.set('restaurant', slug);
    window.history.replaceState(window.history.state, '', u.pathname + u.search + u.hash);
  }, [slug]);

  useEffect(() => {
    let live = true;
    getTables(slug)
      .then((t) => live && setTablesState({ slug, tables: Array.isArray(t) ? t : [] }))
      .catch(() => live && setTablesState({ slug, tables: [] }));
    return () => {
      live = false;
    };
  }, [slug]);
  const tables = tablesState.slug === slug ? tablesState.tables : [];

  const key = `${slug}|${date}`;
  useEffect(() => {
    let live = true;
    listBookings(date, slug)
      .then((b) => live && setData({ key, bookings: Array.isArray(b) ? b : [], error: null }))
      .catch((e) => live && setData((prev) => ({ key, bookings: prev.key === key ? prev.bookings : [], error: errorMessage(e) })));
    return () => {
      live = false;
    };
  }, [key, date, slug, nonce]);
  const current = data.key === key;
  const state: 'loading' | 'ready' | 'error' = !current ? 'loading' : data.error ? 'error' : 'ready';
  const bookings = current ? data.bookings : [];
  const error = actionError ?? (current ? data.error : null);

  // Nights that have bookings, so reservations on other dates are one click away.
  useEffect(() => {
    let live = true;
    listBookings(undefined, slug)
      .then((all) => {
        if (!live) return;
        const today = toISODate(new Date());
        const counts = new Map<string, number>();
        for (const b of Array.isArray(all) ? all : []) {
          const day = b.start_time.slice(0, 10);
          if (b.status !== 'cancelled' && day >= today && (!b.restaurant_slug || b.restaurant_slug === slug)) counts.set(day, (counts.get(day) ?? 0) + 1);
        }
        setUpcoming({ slug, days: [...counts].sort(([a], [b]) => a.localeCompare(b)).slice(0, 10) });
      })
      .catch(() => undefined /* the day view shows its own error */);
    return () => {
      live = false;
    };
  }, [slug, nonce]);
  const upcomingDays = upcoming.slug === slug ? upcoming.days : [];

  useEffect(() => {
    const onChange = (e: Event) => {
      const b = (e as CustomEvent<Booking | undefined>).detail;
      if (b?.start_time) {
        if (b.restaurant_slug) setSlug(b.restaurant_slug);
        setDate(b.start_time.slice(0, 10)); // jump to the night of the booking that just changed
        setHighlight(b.code);
      }
      setNonce((n) => n + 1);
    };
    const refresh = () => setNonce((n) => n + 1);
    window.addEventListener(BOOKING_CHANGED, onChange);
    const t = window.setInterval(refresh, 30000);
    return () => {
      window.removeEventListener(BOOKING_CHANGED, onChange);
      window.clearInterval(t);
    };
  }, []);
  useEffect(() => {
    if (!highlight) return;
    const t = window.setTimeout(() => setHighlight(null), 8000);
    return () => window.clearTimeout(t);
  }, [highlight]);
  const applyUpdate = async (code: string, status: BookingStatus, call: () => Promise<Booking>) => {
    setBusy(true);
    setDrawerError(null);
    try {
      const u = await call();
      const patch = u && typeof u === 'object' ? u : null;
      setData((d) => ({ ...d, bookings: d.bookings.map((b): Booking => (b.code === code ? { ...b, ...patch, status: patch?.status ?? status } : b)) }));
      setActionError(null);
      notifyBookingsChanged();
    } catch (e) {
      setDrawerError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const setStatus = (code: string, status: BookingStatus) => applyUpdate(code, status, () => updateBooking(code, { status }));
  const cancel = (code: string) => applyUpdate(code, 'cancelled', () => cancelBooking(code));
  const openBooking = (code: string) => {
    setDrawerError(null);
    setSelected(code);
  };
  const closeDrawer = useCallback(() => setSelected(null), []);
  const actions: BarActions = { highlight, selected, onOpen: openBooking };

  const shift = (n: number) => {
    const d = parseISODate(date);
    d.setDate(d.getDate() + n);
    setDate(toISODate(d));
  };
  const retry = () => {
    setActionError(null);
    setNonce((n) => n + 1);
  };

  const live = bookings.filter((b) => b.status !== 'cancelled' && b.status !== 'no_show');
  const visible = showCancelled ? bookings : bookings.filter((b) => b.status !== 'cancelled');
  const covers = live.reduce((s, b) => s + b.party_size, 0);
  const used = live.reduce((s, b) => s + Math.max(0, Math.min(span.end, endOf(b)) - Math.max(span.start, mins(b.start_time))), 0);
  const activeTables = tables.filter((t) => t.is_active !== false);
  const occupancy = activeTables.length ? Math.round((used / (activeTables.length * SPAN)) * 100) : 0;
  const rowsFor = (t: Table) => visible.filter((b) => b.table_id === t.id || (b.table_id == null && b.table_name === t.name));
  const known = new Set(tables.map((t) => t.id));
  const unassigned = visible.filter((b) => !(b.table_id != null && known.has(b.table_id)) && !tables.some((t) => t.name === b.table_name));
  const zones = [...new Set(tables.map((t) => t.zone))].sort((a, b) => {
    const ia = ZONE_ORDER.indexOf(a);
    const ib = ZONE_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
  });

  const now = new Date();
  const nowMin = now.getHours() * 60 + now.getMinutes();
  const showNow = date === toISODate(now) && nowMin >= span.start && nowMin <= span.end;
  const options = restaurants.length ? restaurants.map((r) => ({ slug: r.slug, name: r.name })) : [{ slug, name: slug }];

  return (
    <section className="mx-auto max-w-6xl px-4 pb-24 pt-28 sm:px-6">
      <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.35em] text-ember">Admin · Floor manager</p>
          <h1 className="mt-2 font-wonk text-4xl sm:text-5xl">The book</h1>
          <label className="mt-4 inline-flex items-center gap-2 rounded-full border border-line bg-glass py-1 pl-3 pr-1 text-sm">
            <Store className="h-4 w-4 text-ember" />
            <span className="sr-only">Restaurant</span>
            <select value={slug} onChange={(e) => setSlug(e.target.value)} className="cursor-pointer rounded-full bg-transparent py-1.5 pr-2 text-fg outline-none [&>option]:bg-[var(--bg-elev)]">
              {options.map((o) => (
                <option key={o.slug} value={o.slug}>
                  {o.name}
                </option>
              ))}
            </select>
          </label>
          {restaurant && (
            <p className="mt-2 text-xs text-faint">
              {restaurant.area} · {restaurant.hours_open}–{restaurant.hours_close} · {tables.length} tables
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => shift(-1)} aria-label="Previous day" className="grid h-10 w-10 place-items-center rounded-full border border-line bg-glass hover:text-ember">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <input type="date" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} className="field w-auto min-w-0 py-2" />
          <button type="button" onClick={() => shift(1)} aria-label="Next day" className="grid h-10 w-10 place-items-center rounded-full border border-line bg-glass hover:text-ember">
            <ChevronRight className="h-4 w-4" />
          </button>
          <button type="button" onClick={() => setDate(toISODate(new Date()))} className="rounded-full border border-line bg-glass px-4 py-2 text-sm hover:text-ember">
            Today
          </button>
        </div>
      </div>

      {upcomingDays.length > 0 && (
        <div className="scroll-thin mt-6 flex items-center gap-2 overflow-x-auto pb-1">
          <span className="shrink-0 text-[10px] font-semibold uppercase tracking-[0.26em] text-faint">Upcoming</span>
          {upcomingDays.map(([day, n]) => (
            <button
              key={day}
              type="button"
              onClick={() => setDate(day)}
              aria-pressed={day === date}
              className={`shrink-0 rounded-full border px-3 py-1.5 text-xs transition ${day === date ? 'border-ember bg-ember/15 text-ember' : 'border-line bg-glass text-muted hover:text-ember'}`}
            >
              {formatDay(day)} · {n}
            </button>
          ))}
        </div>
      )}

      <div className="mt-8 grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          ['Covers', String(covers)],
          ['Bookings', String(live.length)],
          ['Occupancy', `${occupancy}%`],
          ['Cancelled', String(bookings.filter((b) => b.status === 'cancelled').length)],
        ].map(([k, v], i) => (
          <motion.div key={k} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }} className="glass rounded-3xl p-5">
            <div className="text-[10px] font-semibold uppercase tracking-[0.26em] text-faint">{k}</div>
            <div className="mt-2 font-display text-4xl">{v}</div>
          </motion.div>
        ))}
      </div>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-3 text-sm">
        <p className="text-muted">{formatDay(date)}</p>
        <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg/85" aria-label="Status legend">
          {STATUSES.map((s) => (
            <li key={s} className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm border" style={{ background: `color-mix(in oklab, ${statusColor(s)} 45%, transparent)`, borderColor: statusColor(s) }} />
              {STATUS_LABEL[s]}
            </li>
          ))}
          <li className="flex items-center gap-1">⚠️ Allergies</li>
          <li className="flex items-center gap-1">🎂 Celebration</li>
        </ul>
        <label className="flex items-center gap-2 text-xs text-muted">
          <input type="checkbox" checked={showCancelled} onChange={(e) => setShowCancelled(e.target.checked)} className="accent-[var(--ember)]" /> Show cancelled
        </label>
      </div>

      {error && (
        <div className="mt-4 flex items-center gap-2 rounded-2xl border border-danger/30 bg-danger/10 p-3 text-sm">
          <CircleAlert className="h-4 w-4 text-danger" /> <span className="flex-1">{error}</span>
          <button type="button" onClick={retry} className="text-ember hover:underline">
            Retry
          </button>
        </div>
      )}

      <div className="glass mt-4 overflow-hidden rounded-[28px]">
        <div className="scroll-thin overflow-x-auto">
          <div className="relative min-w-[820px]">
            <div className="flex border-b border-line">
              <div className="w-28 shrink-0 px-4 py-3 text-[11px] uppercase tracking-[0.2em] text-fg/75">Table</div>
              <div className="relative h-10 flex-1">
                {hours.map((h) => (
                  <span key={h} className="absolute top-3 -translate-x-1/2 text-xs tabular-nums text-muted first:translate-x-0" style={{ left: pctIn(span, h * 60) }}>
                    {h % 24}:00
                  </span>
                ))}
              </div>
            </div>
            {state === 'loading' && !bookings.length ? (
              <div className="space-y-2 p-4">
                {Array.from({ length: 6 }, (_, i) => (
                  <div key={i} className="skeleton h-10 rounded-xl" />
                ))}
              </div>
            ) : (
              <>
                {zones.map((z) => {
                  const ts = tables.filter((t) => t.zone === z).sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
                  return (
                    <div key={z}>
                      <div className="flex items-center gap-2 bg-glass px-4 py-1.5 text-[10px] font-semibold uppercase tracking-[0.24em]" style={{ color: zoneColor(z) }}>
                        <span className="h-1.5 w-1.5 rounded-full" style={{ background: zoneColor(z) }} /> {zoneLabel(z)}
                      </div>
                      {ts.map((t) => (
                        <Row key={t.id} label={t.name} sub={`${t.capacity} seats${t.is_active === false ? ' · off' : ''}`} items={rowsFor(t)} span={span} cols={cols} actions={actions} />
                      ))}
                    </div>
                  );
                })}
                {unassigned.length > 0 && <Row label="—" sub="Unassigned" items={unassigned} span={span} cols={cols} actions={actions} />}
                {!tables.length && !unassigned.length && <p className="p-8 text-center text-sm text-muted">No tables to show yet.</p>}
              </>
            )}
            {showNow && (
              <div className="pointer-events-none absolute bottom-0 top-0 z-20 w-px bg-ember shadow-[0_0_12px_var(--ember)]" style={{ left: `calc(7rem + (100% - 7rem) * ${(nowMin - span.start) / SPAN})` }} />
            )}
          </div>
        </div>
      </div>
      <BookingDrawer booking={bookings.find((b) => b.code === selected) ?? null} busy={busy} error={drawerError} onClose={closeDrawer} onStatus={setStatus} onCancel={cancel} />
      {state === 'ready' && !bookings.length && <p className="mt-6 text-center text-sm text-muted">No reservations yet for this night{upcomingDays.length ? ' - pick a night under Upcoming.' : '.'}</p>}
    </section>
  );
}
