import { useCallback, useEffect, useEffectEvent, useMemo, useRef, useState, type CSSProperties, type FormEvent, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import confetti from 'canvas-confetti';
import { CircleAlert, LoaderCircle, Minus, Plus, RotateCcw } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { Availability, Booking, BookingSource, Slot } from '../lib/types';
import { ApiError, BOOKING_CHANGED, createBooking, errorMessage, getAvailability, notifyBookingsChanged } from '../lib/api';
import { MONTHS, WEEKDAYS, formatDay, nextDays, parseISODate, toISODate } from '../lib/time';
import { zoneLabel } from '../lib/zones';
import Ticket from './Ticket';

function celebrate() {
  const opts = { colors: ['#ff7a3d', '#e3bc76', '#fbe9d0', '#b8441d', '#7d1f45'], disableForReducedMotion: true, zIndex: 80 };
  confetti({ ...opts, particleCount: 110, spread: 80, startVelocity: 45, origin: { x: 0.5, y: 0.6 } });
  window.setTimeout(() => {
    confetti({ ...opts, particleCount: 60, angle: 60, spread: 60, origin: { x: 0, y: 0.75 } });
    confetti({ ...opts, particleCount: 60, angle: 120, spread: 60, origin: { x: 1, y: 0.75 } });
  }, 180);
}

function Step({ n, title, aside, children }: { n: string; title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <div>
      <div className="mb-4 flex min-w-0 items-baseline justify-between gap-3">
        <h3 className="flex shrink-0 items-baseline gap-3">
          <span className="font-display text-sm italic text-gold">{n}</span>
          <span className="text-xs font-semibold uppercase tracking-[0.26em] text-muted">{title}</span>
        </h3>
        {aside && <span className="min-w-0 truncate text-right text-xs text-faint">{aside}</span>}
      </div>
      {children}
    </div>
  );
}

function DateStrip({ days, value, onChange }: { days: Date[]; value: string; onChange: (iso: string) => void }) {
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const sc = scroller.current;
    const el = sc?.querySelector<HTMLElement>(`[data-iso="${value}"]`);
    if (sc && el) sc.scrollTo({ left: el.offsetLeft - sc.clientWidth / 2 + el.clientWidth / 2, behavior: 'smooth' });
  }, [value]);
  return (
    <div
      ref={scroller}
      className="no-scrollbar mask-fade-x relative flex snap-x snap-mandatory scroll-px-4 gap-2.5 overflow-x-auto overscroll-x-contain px-4 py-3 sm:snap-proximity sm:scroll-px-6 sm:gap-3 sm:px-6"
    >
      {days.map((d, i) => {
        const iso = toISODate(d);
        const sel = iso === value;
        return (
          <motion.button
            key={iso}
            data-iso={iso}
            type="button"
            onClick={() => onChange(iso)}
            aria-pressed={sel}
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: i * 0.03 }}
            whileHover={{ y: -3 }}
            whileTap={{ scale: 0.95 }}
            className={`relative flex w-[68px] shrink-0 touch-manipulation snap-center flex-col items-center rounded-2xl border px-2 pb-3 pt-2.5 transition-colors sm:w-[76px] ${
              sel ? 'border-transparent text-on-ember' : 'border-line bg-glass text-fg hover:border-line-strong'
            }`}
          >
            {sel && (
              <motion.span
                layoutId="date-glow"
                className="ember-fill absolute inset-0 rounded-2xl shadow-[0_10px_40px_-8px_var(--ember)]"
                transition={{ type: 'spring', stiffness: 380, damping: 30 }}
              />
            )}
            <span className="relative text-[11px] font-semibold uppercase tracking-[0.14em] opacity-80 sm:text-[10px] sm:tracking-[0.16em]">
              {i === 0 ? 'Tonight' : i === 1 ? 'Tmrw' : WEEKDAYS[d.getDay()]}
            </span>
            <span className="relative mt-1 font-display text-3xl leading-none">{d.getDate()}</span>
            <span className="relative mt-1 text-xs uppercase tracking-wider opacity-70 sm:text-[11px]">{MONTHS[d.getMonth()]}</span>
          </motion.button>
        );
      })}
    </div>
  );
}

function PartyDial({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  const [prev, setPrev] = useState(value);
  const [dir, setDir] = useState(1);
  if (value !== prev) {
    setPrev(value);
    setDir(value > prev ? 1 : -1);
  }
  const R = 64;
  const btn =
    'grid size-12 shrink-0 touch-manipulation place-items-center rounded-full border border-line bg-glass text-fg transition hover:border-ember/60 hover:text-ember disabled:opacity-30 sm:size-11';
  return (
    <div className="flex items-center justify-center gap-4 sm:gap-6">
      <button type="button" className={btn} onClick={() => onChange(Math.max(1, value - 1))} disabled={value <= 1} aria-label="Fewer guests">
        <Minus className="size-5 sm:size-4" />
      </button>
      <div className="relative size-40 shrink-0 sm:size-44" role="spinbutton" aria-valuenow={value} aria-valuemin={1} aria-valuemax={12} aria-label="Party size">
        <svg viewBox="0 0 180 180" className="absolute inset-0 h-full w-full -rotate-90">
          <defs>
            <linearGradient id="dial-grad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" style={{ stopColor: 'var(--gold)' }} />
              <stop offset="1" style={{ stopColor: 'var(--ember)' }} />
            </linearGradient>
          </defs>
          <circle cx="90" cy="90" r={R} fill="none" strokeWidth="10" style={{ stroke: 'var(--line)' }} />
          <motion.circle
            cx="90"
            cy="90"
            r={R}
            fill="none"
            strokeWidth="10"
            strokeLinecap="round"
            stroke="url(#dial-grad)"
            initial={false}
            animate={{ pathLength: value / 12 }}
            transition={{ type: 'spring', stiffness: 140, damping: 20 }}
            style={{ filter: 'drop-shadow(0 0 8px rgb(255 122 61 / .55))' }}
          />
          {Array.from({ length: 12 }, (_, i) => {
            const a = (i / 12) * Math.PI * 2;
            return (
              <circle
                key={i}
                cx={90 + Math.cos(a) * 82}
                cy={90 + Math.sin(a) * 82}
                r={i < value ? 2.6 : 1.6}
                style={{ fill: i < value ? 'var(--ember)' : 'var(--fg-faint)', transition: 'all .3s' }}
              />
            );
          })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <div className="relative h-16 w-24 overflow-hidden">
            <AnimatePresence initial={false} custom={dir} mode="popLayout">
              <motion.span
                key={value}
                custom={dir}
                variants={{
                  enter: (d: number) => ({ y: d > 0 ? 44 : -44, opacity: 0 }),
                  center: { y: 0, opacity: 1 },
                  exit: (d: number) => ({ y: d > 0 ? -44 : 44, opacity: 0 }),
                }}
                initial="enter"
                animate="center"
                exit="exit"
                transition={{ type: 'spring', stiffness: 300, damping: 26 }}
                className="absolute inset-0 text-center font-display text-6xl leading-[4rem]"
              >
                {value}
              </motion.span>
            </AnimatePresence>
          </div>
          <span className="text-xs uppercase tracking-[0.24em] text-muted sm:text-[11px]">{value === 1 ? 'guest' : 'guests'}</span>
        </div>
      </div>
      <button type="button" className={btn} onClick={() => onChange(Math.min(12, value + 1))} disabled={value >= 12} aria-label="More guests">
        <Plus className="size-5 sm:size-4" />
      </button>
    </div>
  );
}

/** Phones get an even grid of 44px-tall pills; from sm up it is the original wrapping row. */
const SLOT_ROW = 'grid grid-cols-[repeat(auto-fill,minmax(4.5rem,1fr))] gap-2 sm:flex sm:flex-wrap';
const SLOT_PILL = 'min-h-11 justify-center px-3 text-[15px] sm:min-h-0 sm:px-4 sm:py-2 sm:text-sm';

/** Staggers the shimmer sweep so a row of placeholders reads as one travelling wave. */
const wave = (i: number) => ({ '--shimmer-delay': `${i * 70}ms` }) as CSSProperties;

/** Placeholder pills with the same box as a real time pill (padding, type size, tabular digits). */
function SlotSkeletons() {
  return (
    <div role="status" aria-busy="true">
      <span className="sr-only">Checking which seatings are free…</span>
      <div aria-hidden className={SLOT_ROW}>
        {Array.from({ length: 11 }, (_, i) => (
          <span key={i} className={`shimmer flex items-center rounded-full font-medium tabular-nums ${SLOT_PILL}`} style={wave(i)}>
            <span className="invisible">00:00</span>
          </span>
        ))}
      </div>
      <div aria-hidden className="mt-3 flex h-4 items-center">
        <span className="shimmer-bar block h-2 w-36 rounded-full" />
      </div>
    </div>
  );
}

/** Placeholder table chips: a name block and a zone/seats line, sized like the real chips. */
function TableSkeletons() {
  return (
    <div aria-busy="true">
      <span className="sr-only">Loading tables…</span>
      <div aria-hidden className="flex flex-wrap gap-2">
        {['w-24', 'w-28', 'w-20'].map((w, i) => (
          <span key={w} className="shimmer flex items-center gap-2.5 rounded-2xl px-4 py-2.5" style={wave(i + 2)}>
            <span className="flex h-7 items-center">
              <span className="shimmer-bar block h-4 w-9 rounded-full" />
            </span>
            <span className={`shimmer-bar block h-2.5 rounded-full ${w}`} />
          </span>
        ))}
      </div>
    </div>
  );
}

function TimeSlots({ slots, pending, loading, error, value, onChange, onRetry, animKey }: {
  slots: Slot[]; pending: boolean; loading: boolean; error: string | null; value: string | null; onChange: (t: string) => void; onRetry: () => void; animKey: string;
}) {
  if (pending) return <SlotSkeletons />;
  if (error)
    return (
      <div className="flex items-start gap-3 rounded-2xl border border-danger/30 bg-danger/10 p-4 text-sm text-fg">
        <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
        <div className="flex-1">{error}</div>
        <button type="button" onClick={onRetry} className="inline-flex items-center gap-1 text-xs text-ember hover:underline">
          <RotateCcw className="h-3 w-3" /> Retry
        </button>
      </div>
    );
  if (!slots.length) return <p className="text-sm text-muted">No seatings on this date.</p>;
  const open = slots.filter((s) => s.available).length;
  return (
    <div>
      <motion.div key={animKey} initial="hidden" animate="show" variants={{ show: { transition: { staggerChildren: 0.035 } } }} className={SLOT_ROW}>
        {slots.map((s) => {
          const sel = s.time === value;
          return (
            <motion.button
              key={s.time}
              type="button"
              disabled={!s.available}
              onClick={() => onChange(s.time)}
              aria-pressed={sel}
              variants={{ hidden: { opacity: 0, y: 10, scale: 0.9 }, show: { opacity: 1, y: 0, scale: 1 } }}
              whileHover={s.available ? { y: -2 } : undefined}
              className={`relative flex touch-manipulation items-center rounded-full font-medium tabular-nums transition-colors ${SLOT_PILL} ${
                !s.available
                  ? 'cursor-not-allowed border border-dashed border-line text-faint line-through'
                  : sel
                    ? 'text-on-ember'
                    : 'border border-ember/40 bg-ember/[0.08] text-fg shadow-[0_0_24px_-8px_var(--ember)] hover:border-ember/80 hover:bg-ember/15'
              }`}
            >
              {sel && <motion.span layoutId="slot-glow" className="ember-fill absolute inset-0 rounded-full shadow-[0_0_30px_-4px_var(--ember)]" />}
              <span className="relative">{s.time}</span>
            </motion.button>
          );
        })}
      </motion.div>
      <p className="mt-3 text-xs text-faint">
        {open} of {slots.length} seatings open{loading ? ' · refreshing…' : ''}
      </p>
    </div>
  );
}

export interface BookingPanelProps {
  slug: string;
  restaurantName: string;
  initialDate?: string | null;
  initialParty?: number | null;
  initialTime?: string | null;
  /** Booking-focused layout (the /book entry point): smaller heading. */
  compact?: boolean;
  source?: BookingSource;
}

const clampParty = (n: number | null | undefined) => (n && Number.isFinite(n) ? Math.min(12, Math.max(1, Math.round(n))) : 2);

export default function BookingPanel({ slug, restaurantName, initialDate, initialParty, initialTime, compact = false, source = 'web' }: BookingPanelProps) {
  const days = useMemo(() => {
    // Two weeks ahead, stretched if a deep link asks for a later night.
    const today = toISODate(new Date());
    const ahead = initialDate && /^\d{4}-\d{2}-\d{2}$/.test(initialDate) && initialDate > today ? Math.round((parseISODate(initialDate).getTime() - parseISODate(today).getTime()) / 86400000) + 1 : 0;
    return nextDays(Math.min(60, Math.max(14, ahead)));
  }, [initialDate]);
  const [date, setDate] = useState(() => {
    const first = toISODate(days[0]);
    return initialDate && days.some((d) => toISODate(d) === initialDate) ? initialDate : first;
  });
  const [party, setParty] = useState(() => clampParty(initialParty));
  const [avail, setAvail] = useState<Availability | null>(null);
  const [availFor, setAvailFor] = useState('');
  const [loading, setLoading] = useState(true);
  const [availError, setAvailError] = useState<string | null>(null);
  const [time, setTime] = useState<string | null>(initialTime && /^\d{2}:\d{2}$/.test(initialTime) ? initialTime : null);
  const [tableId, setTableId] = useState<number | null>(null);
  const [form, setForm] = useState({ name: '', phone: '', email: '', notes: '' });
  const [touched, setTouched] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [booking, setBooking] = useState<Booking | null>(null);
  const reqId = useRef(0);

  const load = useCallback(
    async (silent = false) => {
      const id = ++reqId.current;
      setLoading(true);
      if (!silent) setAvail(null);
      try {
        const a = await getAvailability(slug, date, party);
        if (id !== reqId.current) return;
        setAvail(a && Array.isArray(a.slots) ? a : { date, party_size: party, slots: [] });
        setAvailFor(`${date}|${party}`);
        setAvailError(null);
      } catch (e) {
        if (id !== reqId.current) return;
        setAvailError(errorMessage(e));
      } finally {
        if (id === reqId.current) setLoading(false);
      }
    },
    [slug, date, party],
  );

  useEffect(() => {
    const t = window.setTimeout(() => load(false), 150);
    return () => window.clearTimeout(t);
  }, [load]);

  const refresh = useEffectEvent(() => load(true));
  useEffect(() => {
    const h = () => refresh();
    window.addEventListener(BOOKING_CHANGED, h);
    return () => window.removeEventListener(BOOKING_CHANGED, h);
  }, []);

  const slots = avail?.slots ?? [];
  // Skeletons while there is nothing current to show: first load, a date/party change
  // (including the short debounce before the request) and retries after an error.
  // Silent refreshes keep the current slots on screen.
  const pending = avail ? availFor !== `${date}|${party}` : loading;
  const [checked, setChecked] = useState(avail);
  if (avail !== checked) {
    setChecked(avail);
    const s = avail?.slots.find((x) => x.time === time);
    if (avail && (!s || !s.available)) {
      setTime(null);
      setTableId(null);
    } else if (s && !s.available_tables.some((t) => t.id === tableId)) {
      setTableId(s.best_table?.id ?? s.available_tables[0]?.id ?? null);
    }
  }
  const slot = slots.find((s) => s.time === time) ?? null;

  const pickTime = (t: string) => {
    setTime(t);
    const s = slots.find((x) => x.time === t);
    setTableId(s?.best_table?.id ?? s?.available_tables[0]?.id ?? null);
    setSubmitError(null);
  };

  const table = slot?.available_tables.find((t) => t.id === tableId) ?? slot?.best_table ?? null;
  const nameMissing = !form.name.trim();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!slot) {
      setSubmitError('Choose a time first.');
      return;
    }
    if (nameMissing) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const b = await createBooking(slug, {
        guest_name: form.name.trim(),
        party_size: party,
        start_time: slot.start || `${date}T${slot.time}:00`,
        phone: form.phone.trim() || undefined,
        email: form.email.trim() || undefined,
        notes: form.notes.trim() || undefined,
        table_id: table?.id,
        source,
      });
      setBooking({ ...b, restaurant_name: b.restaurant_name ?? restaurantName, restaurant_slug: b.restaurant_slug ?? slug });
      celebrate();
      notifyBookingsChanged(b);
    } catch (err) {
      setSubmitError(errorMessage(err));
      if (err instanceof ApiError && err.status === 409) load(true);
    } finally {
      setSubmitting(false);
    }
  };

  const reset = () => {
    setBooking(null);
    setTime(null);
    setTableId(null);
    setTouched(false);
    setForm((f) => ({ ...f, notes: '' }));
  };

  return (
    <section id="reserve" className={`relative mx-auto max-w-6xl scroll-mt-24 px-4 sm:px-6 ${compact ? 'py-8 sm:py-10' : 'py-16 sm:py-24'}`}>
      <motion.div initial={{ opacity: 0, y: 30 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: '-80px' }} transition={{ duration: 0.8 }} className={compact ? 'mb-6 text-center' : 'mb-10 text-center'}>
        <p className="text-xs font-semibold uppercase tracking-[0.35em] text-ember">Reservations · {restaurantName}</p>
        <h2 className={`mt-3 text-balance font-wonk leading-[1.08] ${compact ? 'text-3xl sm:text-4xl' : 'text-[2.5rem] sm:text-6xl'}`}>
          Reserve your <em className="text-ember-gradient pr-1">evening</em>
        </h2>
        {!compact && <p className="mx-auto mt-4 max-w-xl text-pretty text-[15px] text-muted sm:text-base">Choose a night, tell us how many, and pick the seating that suits the mood.</p>}
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 40 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: '-60px' }} transition={{ duration: 0.9 }} className="glass rounded-3xl p-4 sm:rounded-[28px] sm:p-8 lg:p-10">
        <Step n="01" title="Choose a night" aside={formatDay(date)}>
          <div className="-mx-4 sm:-mx-8 lg:-mx-10">
            <DateStrip days={days} value={date} onChange={setDate} />
          </div>
        </Step>

        <div className="mt-8 grid gap-9 sm:mt-10 sm:gap-10 lg:grid-cols-[320px_minmax(0,1fr)]">
          <Step n="02" title="Party size">
            <PartyDial value={party} onChange={setParty} />
          </Step>
          <div className="min-w-0 space-y-9 sm:space-y-10">
            <Step n="03" title="Time">
              <TimeSlots slots={slots} pending={pending} loading={loading} error={availError} value={time} onChange={pickTime} onRetry={() => load(false)} animKey={`${date}-${party}`} />
            </Step>
            <Step n="04" title="Your table" aside={slot && !pending ? `${slot.available_tables.length} free at ${slot.time}` : undefined}>
              {pending ? (
                <TableSkeletons />
              ) : !slot ? (
                <p className="text-sm text-muted">Pick a time to see which tables are free.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {slot.available_tables.map((t) => {
                    const sel = t.id === table?.id;
                    return (
                      <motion.button
                        key={t.id}
                        type="button"
                        layout
                        onClick={() => setTableId(t.id)}
                        aria-pressed={sel}
                        className={`relative min-h-11 max-w-full touch-manipulation rounded-2xl border px-4 py-2.5 text-left text-sm transition ${sel ? 'border-ember bg-ember/15 shadow-[0_0_30px_-8px_var(--ember)]' : 'border-line bg-glass hover:border-ember/50'}`}
                      >
                        <span className="font-display text-lg">{t.name}</span>
                        <span className="ml-2 text-xs text-muted">
                          {zoneLabel(t.zone)} · {t.capacity} seats
                        </span>
                        {slot.best_table?.id === t.id && <span className="ml-2 text-[11px] uppercase tracking-widest text-gold sm:text-[10px]">best</span>}
                      </motion.button>
                    );
                  })}
                </div>
              )}
            </Step>
          </div>
        </div>

        <div className="mt-8 border-t border-line pt-8 sm:mt-10 sm:pt-10">
          <AnimatePresence mode="wait">
            {booking ? (
              <motion.div key="ticket" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex w-full flex-col items-center gap-6">
                <Ticket booking={booking} />
                <div className="flex flex-wrap justify-center gap-2">
                  <Link to={`/bookings/${encodeURIComponent(booking.code)}`} className="glass-soft inline-flex min-h-11 touch-manipulation items-center rounded-full px-5 py-2.5 text-sm text-fg hover:text-ember">
                    Manage booking
                  </Link>
                  <button type="button" onClick={reset} className="glass-soft min-h-11 touch-manipulation rounded-full px-5 py-2.5 text-sm text-fg hover:text-ember">
                    Book another table
                  </button>
                </div>
              </motion.div>
            ) : (
              <motion.form key="form" onSubmit={submit} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, y: -10 }} noValidate>
                <Step n="05" title="Your details">
                  <div className="grid grid-cols-1 gap-6 sm:gap-8 md:grid-cols-[minmax(0,1fr)_300px]">
                    <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
                      <label className="block sm:col-span-2">
                        <span className="mb-1.5 block text-[13px] text-muted sm:text-xs">Name *</span>
                        <input className="field text-base" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Ananya Rao" autoComplete="name" aria-invalid={touched && nameMissing} />
                        {touched && nameMissing && <span className="mt-1 block text-[13px] text-danger sm:text-xs">Please tell us who the table is for.</span>}
                      </label>
                      <label className="block">
                        <span className="mb-1.5 block text-[13px] text-muted sm:text-xs">Phone</span>
                        <input className="field text-base" type="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="+91 98200 12345" autoComplete="tel" inputMode="tel" />
                      </label>
                      <label className="block">
                        <span className="mb-1.5 block text-[13px] text-muted sm:text-xs">Email</span>
                        <input className="field text-base" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="ananya@example.com" autoComplete="email" inputMode="email" autoCapitalize="off" spellCheck={false} />
                      </label>
                      <label className="block sm:col-span-2">
                        <span className="mb-1.5 block text-[13px] text-muted sm:text-xs">Notes</span>
                        <textarea className="field min-h-24 resize-y text-base" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Allergies, celebrations, seating wishes…" />
                      </label>
                    </div>
                    <div className="glass-soft flex min-w-0 flex-col rounded-3xl p-4 sm:p-5">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-faint sm:text-[10px]">Your evening</p>
                      <dl className="mt-4 space-y-2.5 text-sm">
                        {[
                          ['Date', formatDay(date)],
                          ['Time', time ?? '—'],
                          ['Guests', String(party)],
                          ['Table', table ? `${table.name} · ${zoneLabel(table.zone)}` : '—'],
                        ].map(([k, v]) => (
                          <div key={k} className="flex justify-between gap-3">
                            <dt className="text-muted">{k}</dt>
                            <dd className="min-w-0 break-words text-right font-medium">{v}</dd>
                          </div>
                        ))}
                      </dl>
                      <AnimatePresence>
                        {submitError && (
                          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
                            <div className="mt-4 flex gap-2 rounded-2xl border border-danger/30 bg-danger/10 p-3 text-[13px] text-fg sm:text-xs">
                              <CircleAlert className="h-4 w-4 shrink-0 text-danger" /> {submitError}
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                      <button
                        type="submit"
                        disabled={submitting || !slot}
                        className="group ember-fill relative mt-auto inline-flex min-h-12 w-full touch-manipulation items-center justify-center gap-2 overflow-hidden rounded-full px-6 py-3.5 text-sm font-semibold text-on-ember shadow-[0_0_40px_-8px_var(--ember)] transition disabled:cursor-not-allowed disabled:opacity-40 [&:not(:first-child)]:mt-5"
                      >
                        <span className="sheen" />
                        {submitting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
                        {submitting ? 'Reserving…' : 'Confirm reservation'}
                      </button>
                    </div>
                  </div>
                </Step>
              </motion.form>
            )}
          </AnimatePresence>
        </div>
      </motion.div>
    </section>
  );
}
