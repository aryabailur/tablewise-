import { useCallback, useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { ChevronLeft, ChevronRight, CircleAlert, Users, X } from 'lucide-react';
import type { Booking, Table } from '../lib/types';
import { BOOKING_CHANGED, cancelBooking, errorMessage, getTables, lastBooking, listBookings, notifyBookingsChanged } from '../lib/api';
import { formatDay, parseISODate, parseLocal, toISODate } from '../lib/time';
import { zoneLabel } from './Ticket';

const START = 17 * 60;
const END = 23 * 60 + 30;
const SPAN = END - START;
const HOURS = [17, 18, 19, 20, 21, 22, 23];
const ZONES = ['window', 'bar', 'garden', 'private'] as const;
const ZONE_COLOR: Record<string, string> = { window: 'var(--z-window)', garden: 'var(--z-garden)', bar: 'var(--z-bar)', private: 'var(--z-private)' };
const mins = (iso: string) => {
  const d = parseLocal(iso);
  return d.getHours() * 60 + d.getMinutes();
};
const pct = (m: number) => `${((Math.min(END, Math.max(START, m)) - START) / SPAN) * 100}%`;

/** Open on the night of the most recent booking if it's still upcoming, otherwise tonight. */
function initialDate(): string {
  const today = toISODate(new Date());
  const day = lastBooking()?.start_time.slice(0, 10);
  return day && day >= today ? day : today;
}

export default function AdminTimeline() {
  const [date, setDate] = useState(initialDate);
  const [highlight, setHighlight] = useState<string | null>(() => lastBooking()?.code ?? null);
  const [upcoming, setUpcoming] = useState<[string, number][]>([]);
  const [tables, setTables] = useState<Table[]>([]);
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState<string | null>(null);
  const [showCancelled, setShowCancelled] = useState(true);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const reqId = useRef(0);

  useEffect(() => {
    getTables()
      .then((t) => {
        if (Array.isArray(t)) setTables(t);
      })
      .catch(() => undefined);
  }, []);

  const load = useCallback(
    async (silent = false) => {
      const id = ++reqId.current;
      if (!silent) setState('loading');
      try {
        const b = await listBookings(date);
        if (id !== reqId.current) return;
        setBookings(Array.isArray(b) ? b : []);
        setState('ready');
        setError(null);
      } catch (e) {
        if (id !== reqId.current) return;
        setError(errorMessage(e));
        setState('error');
      }
    },
    [date],
  );
  useEffect(() => {
    load();
  }, [load]);
  const loadRef = useRef(load);
  loadRef.current = load;

  // Nights that have bookings, so reservations on other dates are one click away.
  const loadUpcoming = useCallback(async () => {
    try {
      const all = await listBookings();
      const today = toISODate(new Date());
      const counts = new Map<string, number>();
      for (const b of Array.isArray(all) ? all : []) {
        const day = b.start_time.slice(0, 10);
        if (b.status !== 'cancelled' && day >= today) counts.set(day, (counts.get(day) ?? 0) + 1);
      }
      setUpcoming([...counts].sort(([a], [b]) => a.localeCompare(b)).slice(0, 10));
    } catch {
      /* the day view shows its own error */
    }
  }, []);
  useEffect(() => {
    loadUpcoming();
  }, [loadUpcoming]);

  useEffect(() => {
    const onChange = (e: Event) => {
      const b = (e as CustomEvent<Booking | undefined>).detail;
      if (b?.start_time) {
        setDate(b.start_time.slice(0, 10)); // jump to the night of the booking that just changed
        setHighlight(b.code);
      }
      loadRef.current(true);
      loadUpcoming();
    };
    const refresh = () => {
      loadRef.current(true);
      loadUpcoming();
    };
    window.addEventListener(BOOKING_CHANGED, onChange);
    const t = window.setInterval(refresh, 30000);
    return () => {
      window.removeEventListener(BOOKING_CHANGED, onChange);
      window.clearInterval(t);
    };
  }, [loadUpcoming]);
  useEffect(() => {
    if (!highlight) return;
    const t = window.setTimeout(() => setHighlight(null), 8000);
    return () => window.clearTimeout(t);
  }, [highlight]);
  useEffect(() => {
    if (!confirm) return;
    const t = window.setTimeout(() => setConfirm(null), 3500);
    return () => window.clearTimeout(t);
  }, [confirm]);

  const cancel = async (code: string) => {
    setBusy(code);
    try {
      const u = await cancelBooking(code);
      setBookings((bs) => bs.map((b): Booking => (b.code === code ? { ...b, ...u, status: 'cancelled' } : b)));
      notifyBookingsChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
      setConfirm(null);
    }
  };

  const shift = (n: number) => {
    const d = parseISODate(date);
    d.setDate(d.getDate() + n);
    setDate(toISODate(d));
  };

  const live = bookings.filter((b) => b.status !== 'cancelled');
  const visible = showCancelled ? bookings : live;
  const covers = live.reduce((s, b) => s + b.party_size, 0);
  const used = live.reduce((s, b) => {
    const st = mins(b.start_time);
    const en = b.end_time ? mins(b.end_time) : st + (b.duration_min || 90);
    return s + Math.max(0, Math.min(END, en) - Math.max(START, st));
  }, 0);
  const occupancy = tables.length ? Math.round((used / (tables.length * SPAN)) * 100) : 0;
  const rowsFor = (t: Table) => visible.filter((b) => b.table_id === t.id || (b.table_id == null && b.table_name === t.name));
  const known = new Set(tables.map((t) => t.id));
  const unassigned = visible.filter((b) => !(b.table_id != null && known.has(b.table_id)) && !tables.some((t) => t.name === b.table_name));

  const now = new Date();
  const nowMin = now.getHours() * 60 + now.getMinutes();
  const showNow = date === toISODate(now) && nowMin >= START && nowMin <= END;

  const Bar = ({ b }: { b: Booking }) => {
    const st = mins(b.start_time);
    const en = b.end_time ? mins(b.end_time) : st + (b.duration_min || 90);
    const cancelled = b.status === 'cancelled';
    const color = ZONE_COLOR[b.zone ?? ''] ?? 'var(--ember)';
    return (
      <motion.div
        initial={{ opacity: 0, scaleX: 0.6 }}
        animate={{ opacity: cancelled ? 0.5 : 1, scaleX: 1 }}
        title={`${b.guest_name} · ${b.party_size} guests · ${b.code}${b.notes ? ` · ${b.notes}` : ''}`}
        className={`group/bar absolute inset-y-1.5 flex items-center gap-2 overflow-hidden rounded-xl border px-2.5 text-xs ${cancelled ? 'bar-cancelled z-0 border-line line-through' : 'z-10'} ${highlight === b.code ? 'ring-2 ring-[var(--ember)] shadow-[0_0_18px_var(--ember)]' : ''}`}
        style={{
          left: pct(st),
          width: `calc(${pct(en)} - ${pct(st)})`,
          transformOrigin: 'left center',
          ...(cancelled ? {} : { background: `linear-gradient(90deg, color-mix(in oklab, ${color} 38%, transparent), color-mix(in oklab, ${color} 14%, transparent))`, borderColor: `color-mix(in oklab, ${color} 55%, transparent)` }),
        }}
      >
        <span className="truncate font-medium">{b.guest_name}</span>
        <span className="flex shrink-0 items-center gap-0.5 text-muted">
          <Users className="h-3 w-3" />
          {b.party_size}
        </span>
        <span className="ml-auto shrink-0 font-mono text-[10px] text-faint">{b.code}</span>
        {!cancelled && (
          <button
            type="button"
            disabled={busy === b.code}
            onClick={() => (confirm === b.code ? cancel(b.code) : setConfirm(b.code))}
            className={`shrink-0 rounded-full transition ${confirm === b.code ? 'bg-danger px-2 py-0.5 text-[10px] font-semibold text-white' : 'grid h-5 w-5 place-items-center bg-black/30 text-white opacity-0 group-hover/bar:opacity-100 focus:opacity-100'}`}
            aria-label={`Cancel ${b.code}`}
          >
            {confirm === b.code ? 'Cancel?' : <X className="h-3 w-3" />}
          </button>
        )}
      </motion.div>
    );
  };

  const Row = ({ label, sub, items }: { label: string; sub?: string; items: Booking[] }) => (
    <div className="flex border-b border-line last:border-b-0">
      <div className="w-28 shrink-0 px-4 py-3">
        <div className="font-display text-base leading-none">{label}</div>
        {sub && <div className="mt-1 text-[10px] text-faint">{sub}</div>}
      </div>
      <div className="relative h-14 flex-1" style={{ backgroundImage: 'linear-gradient(to right, var(--line) 1px, transparent 1px)', backgroundSize: `${100 / 13}% 100%` }}>
        {items.map((b) => (
          <Bar key={b.code} b={b} />
        ))}
      </div>
    </div>
  );

  return (
    <section className="mx-auto max-w-6xl px-4 pb-24 pt-28 sm:px-6">
      <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.35em] text-ember">Admin · Floor manager</p>
          <h1 className="mt-2 font-wonk text-4xl sm:text-5xl">The book</h1>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => shift(-1)} aria-label="Previous day" className="grid h-10 w-10 place-items-center rounded-full border border-line bg-glass hover:text-ember">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <input type="date" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} className="field w-auto py-2" />
          <button type="button" onClick={() => shift(1)} aria-label="Next day" className="grid h-10 w-10 place-items-center rounded-full border border-line bg-glass hover:text-ember">
            <ChevronRight className="h-4 w-4" />
          </button>
          <button type="button" onClick={() => setDate(toISODate(new Date()))} className="rounded-full border border-line bg-glass px-4 py-2 text-sm hover:text-ember">
            Today
          </button>
        </div>
      </div>

      {upcoming.length > 0 && (
        <div className="scroll-thin mt-6 flex items-center gap-2 overflow-x-auto pb-1">
          <span className="shrink-0 text-[10px] font-semibold uppercase tracking-[0.26em] text-faint">Upcoming</span>
          {upcoming.map(([day, n]) => (
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
          ['Cancelled', String(bookings.length - live.length)],
        ].map(([k, v], i) => (
          <motion.div key={k} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }} className="glass rounded-3xl p-5">
            <div className="text-[10px] font-semibold uppercase tracking-[0.26em] text-faint">{k}</div>
            <div className="mt-2 font-display text-4xl">{v}</div>
          </motion.div>
        ))}
      </div>

      <div className="mt-6 flex items-center justify-between text-sm">
        <p className="text-muted">{formatDay(date)}</p>
        <label className="flex items-center gap-2 text-xs text-muted">
          <input type="checkbox" checked={showCancelled} onChange={(e) => setShowCancelled(e.target.checked)} className="accent-[var(--ember)]" /> Show cancelled
        </label>
      </div>

      {state === 'error' && (
        <div className="mt-4 flex items-center gap-2 rounded-2xl border border-danger/30 bg-danger/10 p-3 text-sm">
          <CircleAlert className="h-4 w-4 text-danger" /> <span className="flex-1">{error}</span>
          <button type="button" onClick={() => load()} className="text-ember hover:underline">
            Retry
          </button>
        </div>
      )}

      <div className="glass mt-4 overflow-hidden rounded-[28px]">
        <div className="scroll-thin overflow-x-auto">
          <div className="relative min-w-[820px]">
            <div className="flex border-b border-line">
              <div className="w-28 shrink-0 px-4 py-3 text-[10px] uppercase tracking-[0.2em] text-faint">Table</div>
              <div className="relative h-10 flex-1">
                {HOURS.map((h) => (
                  <span key={h} className="absolute top-3 -translate-x-1/2 text-xs tabular-nums text-muted first:translate-x-0" style={{ left: pct(h * 60) }}>
                    {h}:00
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
                {ZONES.map((z) => {
                  const ts = tables.filter((t) => t.zone === z).sort((a, b) => a.name.localeCompare(b.name));
                  if (!ts.length) return null;
                  return (
                    <div key={z}>
                      <div className="flex items-center gap-2 bg-glass px-4 py-1.5 text-[10px] font-semibold uppercase tracking-[0.24em]" style={{ color: ZONE_COLOR[z] }}>
                        <span className="h-1.5 w-1.5 rounded-full" style={{ background: ZONE_COLOR[z] }} /> {zoneLabel(z)}
                      </div>
                      {ts.map((t) => (
                        <Row key={t.id} label={t.name} sub={`${t.capacity} seats`} items={rowsFor(t)} />
                      ))}
                    </div>
                  );
                })}
                {unassigned.length > 0 && <Row label="—" sub="Unassigned" items={unassigned} />}
                {!tables.length && !unassigned.length && <p className="p-8 text-center text-sm text-muted">No tables to show yet.</p>}
              </>
            )}
            {showNow && (
              <div className="pointer-events-none absolute bottom-0 top-0 z-20 w-px bg-ember shadow-[0_0_12px_var(--ember)]" style={{ left: `calc(7rem + (100% - 7rem) * ${(nowMin - START) / SPAN})` }} />
            )}
          </div>
        </div>
      </div>
      {state === 'ready' && !bookings.length && <p className="mt-6 text-center text-sm text-muted">No reservations yet for this night{upcoming.length ? ' - pick a night under Upcoming.' : '.'}</p>}
    </section>
  );
}
