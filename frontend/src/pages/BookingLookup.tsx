import { useEffect, useState, type FormEvent } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowRight, CircleAlert, LoaderCircle, RotateCcw, Search } from 'lucide-react';
import Ticket from '../components/Ticket';
import type { Booking } from '../lib/types';
import { ApiError, BOOKING_CHANGED, cancelBooking, errorMessage, getBooking, lastBooking, notifyBookingsChanged } from '../lib/api';
import { formatDay, hhmm, parseLocal } from '../lib/time';
import { zoneLabel } from '../lib/zones';
import { useDocumentTitle } from '../lib/jsonld';
import { nameFromSlug } from '../lib/restaurants';
import { restaurantLink } from '../lib/links';

const CODE_RE = /^[A-Z]{2,4}-[A-Z0-9]{3,6}$/;
const normalise = (s: string) => s.trim().toUpperCase().replace(/\s+/g, '');

function CodeForm({ initial = '' }: { initial?: string }) {
  const navigate = useNavigate();
  const [code, setCode] = useState(initial);
  const [touched, setTouched] = useState(false);
  const c = normalise(code);
  const valid = CODE_RE.test(c);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (valid) navigate(`/bookings/${encodeURIComponent(c)}`);
  };
  return (
    <form onSubmit={submit} noValidate className="glass-strong mx-auto flex max-w-md items-center gap-2 rounded-full p-1.5">
      <Search className="ml-3 h-4 w-4 shrink-0 text-faint" />
      <label className="min-w-0 flex-1">
        <span className="sr-only">Booking code</span>
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          placeholder="EMB-7K2P"
          autoCapitalize="characters"
          autoComplete="off"
          spellCheck={false}
          aria-invalid={touched && !valid}
          className="h-11 w-full bg-transparent font-mono text-base uppercase tracking-[0.2em] text-fg outline-none placeholder:text-faint"
        />
      </label>
      <button type="submit" className="ember-fill inline-flex h-11 shrink-0 items-center gap-1.5 rounded-full px-5 text-sm font-semibold text-on-ember shadow-[0_0_30px_-8px_var(--ember)]">
        Find <ArrowRight className="h-4 w-4" />
      </button>
      {touched && !valid && <span className="sr-only">Codes look like EMB-7K2P</span>}
    </form>
  );
}

export default function BookingLookup() {
  const { code: raw } = useParams();
  const code = raw ? normalise(raw) : '';
  useDocumentTitle(code ? `${code} · Tablewise` : 'My booking · Tablewise');
  const [nonce, setNonce] = useState(0);
  const [result, setResult] = useState<{ key: string; booking: Booking | null; error: string | null; notFound: boolean }>({ key: '', booking: null, error: null, notFound: false });
  const [confirming, setConfirming] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const key = `${code}|${nonce}`;

  useEffect(() => {
    if (!code) return;
    let live = true;
    getBooking(code)
      .then((b) => live && setResult({ key, booking: b, error: null, notFound: false }))
      .catch((e) => live && setResult({ key, booking: null, error: errorMessage(e), notFound: e instanceof ApiError && e.status === 404 }));
    return () => {
      live = false;
    };
  }, [code, key]);
  useEffect(() => {
    const h = () => setNonce((n) => n + 1);
    window.addEventListener(BOOKING_CHANGED, h);
    return () => window.removeEventListener(BOOKING_CHANGED, h);
  }, []);
  useEffect(() => {
    if (!confirming) return;
    const t = window.setTimeout(() => setConfirming(false), 4000);
    return () => window.clearTimeout(t);
  }, [confirming]);

  const loading = !!code && result.key.split('|')[0] !== code;
  const booking = !loading ? result.booking : null;
  const recent = lastBooking();

  const cancel = async () => {
    if (!booking) return;
    setCancelling(true);
    setCancelError(null);
    try {
      const u = await cancelBooking(booking.code);
      const next: Booking = { ...booking, ...u, status: 'cancelled' };
      setResult((r) => ({ ...r, booking: next }));
      notifyBookingsChanged(next);
    } catch (e) {
      setCancelError(errorMessage(e));
    } finally {
      setCancelling(false);
      setConfirming(false);
    }
  };

  const restaurantName = booking ? booking.restaurant_name ?? (booking.restaurant_slug ? nameFromSlug(booking.restaurant_slug) : 'Tablewise') : '';
  const upcoming = booking ? booking.status !== 'cancelled' && parseLocal(booking.start_time) > new Date() : false;

  return (
    <section className="mx-auto max-w-3xl px-4 pb-28 pt-32 sm:px-6 sm:pt-36">
      <div className="text-center">
        <p className="text-xs font-semibold uppercase tracking-[0.35em] text-ember">My booking</p>
        <h1 className="mt-3 font-wonk text-4xl sm:text-5xl">{code ? 'Your reservation' : 'Find your reservation'}</h1>
        <p className="mx-auto mt-3 max-w-md text-sm text-muted">Enter the code from your confirmation - it looks like EMB-7K2P.</p>
        <div className="mt-7">
          <CodeForm key={code} initial={code} />
        </div>
        {!code && recent?.code && (
          <p className="mt-4 text-xs text-faint">
            Last booked on this device:{' '}
            <Link to={`/bookings/${encodeURIComponent(recent.code)}`} className="font-mono text-ember hover:underline">
              {recent.code}
            </Link>
          </p>
        )}
      </div>

      <div className="mt-10">
        <AnimatePresence mode="wait">
          {!code ? null : loading ? (
            <motion.div key="loading" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex justify-center py-10 text-muted">
              <LoaderCircle className="h-6 w-6 animate-spin text-ember" />
            </motion.div>
          ) : booking ? (
            <motion.div key={`b-${booking.code}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex flex-col items-center gap-6">
              <Ticket booking={booking} />
              <dl className="glass grid w-full max-w-md grid-cols-2 gap-x-4 gap-y-3 rounded-3xl p-5 text-sm">
                {[
                  ['Restaurant', restaurantName],
                  ['When', `${formatDay(booking.start_time.slice(0, 10))} · ${hhmm(booking.start_time)}`],
                  ['Party', `${booking.party_size} ${booking.party_size === 1 ? 'guest' : 'guests'}`],
                  ['Table', booking.table_name ? `${booking.table_name} · ${zoneLabel(booking.zone)}` : '—'],
                  ['Status', booking.status === 'cancelled' ? 'Cancelled' : 'Confirmed'],
                  ['Name', booking.guest_name],
                ].map(([k, v]) => (
                  <div key={k} className="min-w-0">
                    <dt className="text-[10px] uppercase tracking-[0.22em] text-faint">{k}</dt>
                    <dd className={`mt-0.5 break-words ${k === 'Status' && booking.status === 'cancelled' ? 'text-danger' : ''}`}>{v}</dd>
                  </div>
                ))}
              </dl>
              {cancelError && (
                <div className="flex w-full max-w-md items-start gap-2 rounded-2xl border border-danger/30 bg-danger/10 p-3 text-sm">
                  <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-danger" /> {cancelError}
                </div>
              )}
              <div className="flex flex-wrap justify-center gap-2">
                {booking.restaurant_slug && (
                  <Link to={restaurantLink(booking.restaurant_slug)} className="glass-soft inline-flex min-h-11 items-center rounded-full px-5 py-2.5 text-sm hover:text-ember">
                    View {restaurantName}
                  </Link>
                )}
                {booking.status !== 'cancelled' && (
                  <button
                    type="button"
                    disabled={cancelling}
                    onClick={() => (confirming ? cancel() : setConfirming(true))}
                    className={`inline-flex min-h-11 items-center gap-2 rounded-full px-5 py-2.5 text-sm font-medium transition ${confirming ? 'bg-danger text-white' : 'border border-danger/40 text-danger hover:bg-danger/10'} disabled:opacity-50`}
                  >
                    {cancelling && <LoaderCircle className="h-4 w-4 animate-spin" />}
                    {cancelling ? 'Cancelling…' : confirming ? 'Tap again to cancel' : upcoming ? 'Cancel booking' : 'Cancel'}
                  </button>
                )}
              </div>
            </motion.div>
          ) : (
            <motion.div key="err" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="glass mx-auto max-w-md rounded-3xl p-6 text-center">
              <CircleAlert className="mx-auto h-6 w-6 text-danger" />
              <p className="mt-3 font-display text-xl">{result.notFound ? `We couldn't find ${code}` : 'Something went wrong'}</p>
              <p className="mt-1 text-sm text-muted">{result.notFound ? 'Check the code on your confirmation and try again.' : result.error}</p>
              {!result.notFound && (
                <button type="button" onClick={() => setNonce((n) => n + 1)} className="mt-4 inline-flex items-center gap-1 text-sm text-ember hover:underline">
                  <RotateCcw className="h-3.5 w-3.5" /> Retry
                </button>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </section>
  );
}
