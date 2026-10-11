import { useEffect, useState, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Armchair, Ban, CircleAlert, CircleCheck, Clock, LoaderCircle, Mail, MapPin, Phone, UserX, Users, X } from 'lucide-react';
import type { Booking, BookingStatus } from '../lib/types';
import { formatDay, hhmm } from '../lib/time';
import { zoneLabel } from '../lib/zones';
import { statusOf } from '../lib/booking';
import { AllergyChip, BookingExtrasView, StatusPill } from './BookingBits';

interface Props {
  booking: Booking | null;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onStatus: (code: string, status: BookingStatus) => void;
  onCancel: (code: string) => void;
}

const ACTIONS: { status: Exclude<BookingStatus, 'confirmed' | 'cancelled'>; label: string; Icon: typeof Armchair }[] = [
  { status: 'seated', label: 'Mark seated', Icon: Armchair },
  { status: 'completed', label: 'Mark completed', Icon: CircleCheck },
  { status: 'no_show', label: 'Mark no-show', Icon: UserX },
];

function Info({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 items-start gap-2.5">
      <span className="mt-0.5 shrink-0 text-muted">{icon}</span>
      <div className="min-w-0">
        <div className="text-[10px] uppercase tracking-[0.22em] text-muted">{label}</div>
        <div className="mt-0.5 break-words text-sm text-fg">{children}</div>
      </div>
    </div>
  );
}

function DrawerBody({ booking: b, busy, error, onClose, onStatus, onCancel }: Props & { booking: Booking }) {
  const [confirming, setConfirming] = useState(false);
  const st = statusOf(b);
  useEffect(() => {
    if (!confirming) return;
    const t = window.setTimeout(() => setConfirming(false), 4000);
    return () => window.clearTimeout(t);
  }, [confirming]);
  return (
    <>
      <div className="flex items-start justify-between gap-3 border-b border-line p-5">
        <div className="min-w-0">
          <p className="font-mono text-sm tracking-widest text-ember">{b.code}</p>
          <h2 id="booking-drawer-title" className="mt-1 break-words font-display text-2xl text-fg">
            {b.guest_name}
          </h2>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusPill status={st} />
            {b.source && <span className="rounded-full border border-line bg-glass px-2.5 py-0.5 text-xs font-medium uppercase tracking-wider text-fg">via {b.source}</span>}
          </div>
        </div>
        <button type="button" onClick={onClose} aria-label="Close details" className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-line bg-glass text-fg hover:text-ember">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="scroll-thin flex-1 space-y-6 overflow-y-auto p-5">
        {(b.allergies?.length ?? 0) > 0 && (
          <div className="rounded-2xl border p-3" style={{ borderColor: 'color-mix(in oklab, var(--allergy) 45%, transparent)', background: 'color-mix(in oklab, var(--allergy) 8%, transparent)' }}>
            <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.2em]" style={{ color: 'var(--allergy)' }}>
              <CircleAlert className="h-3.5 w-3.5" /> Allergy warning
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {b.allergies?.map((a) => (
                <AllergyChip key={a} allergy={a} />
              ))}
            </div>
          </div>
        )}
        <div className="grid grid-cols-2 gap-4">
          <Info icon={<Users className="h-4 w-4" />} label="Party">
            {b.party_size} {b.party_size === 1 ? 'guest' : 'guests'}
          </Info>
          <Info icon={<Clock className="h-4 w-4" />} label="When">
            {formatDay(b.start_time.slice(0, 10))}
            <br />
            {hhmm(b.start_time)}–{b.end_time ? hhmm(b.end_time) : '—'}
          </Info>
          <Info icon={<MapPin className="h-4 w-4" />} label="Table">
            {b.table_name ?? 'Unassigned'} · {zoneLabel(b.zone)}
          </Info>
          <Info icon={<Phone className="h-4 w-4" />} label="Phone">
            {b.phone ? <a href={`tel:${b.phone}`} className="hover:text-ember">{b.phone}</a> : '—'}
          </Info>
          <div className="col-span-2">
            <Info icon={<Mail className="h-4 w-4" />} label="Email">
              {b.email ? <a href={`mailto:${b.email}`} className="hover:text-ember">{b.email}</a> : '—'}
            </Info>
          </div>
        </div>
        <BookingExtrasView booking={{ ...b, allergies: [] }} inkClass="text-muted" />
        {b.notes?.trim() && (
          <div>
            <div className="text-[10px] uppercase tracking-[0.22em] text-muted">Notes</div>
            <p className="mt-1 whitespace-pre-wrap break-words text-sm text-fg">{b.notes}</p>
          </div>
        )}
      </div>

      <div className="space-y-3 border-t border-line p-5">
        {error && (
          <div className="flex items-start gap-2 rounded-2xl border border-danger/30 bg-danger/10 p-3 text-sm text-fg">
            <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-danger" /> {error}
          </div>
        )}
        {st === 'cancelled' ? (
          <p className="text-sm text-muted">This booking was cancelled and can no longer be changed.</p>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-2">
              {ACTIONS.map(({ status, label, Icon }) => (
                <button
                  key={status}
                  type="button"
                  disabled={busy || st === status}
                  onClick={() => onStatus(b.code, status)}
                  className="flex min-h-11 flex-col items-center justify-center gap-1 rounded-2xl border px-2 py-2 text-xs font-medium text-fg transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-45"
                  style={{ borderColor: `color-mix(in oklab, var(--st-${status}) 50%, transparent)`, background: `color-mix(in oklab, var(--st-${status}) 12%, transparent)` }}
                >
                  <Icon className="h-4 w-4" style={{ color: `var(--st-${status})` }} />
                  {label}
                </button>
              ))}
            </div>
            <button
              type="button"
              disabled={busy}
              onClick={() => (confirming ? onCancel(b.code) : setConfirming(true))}
              className={`inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold transition disabled:opacity-50 ${confirming ? 'bg-danger text-white' : 'border border-danger/40 text-danger hover:bg-danger/10'}`}
            >
              {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Ban className="h-4 w-4" />}
              {confirming ? 'Tap again to confirm cancellation' : 'Cancel booking'}
            </button>
          </>
        )}
      </div>
    </>
  );
}

/** Right-hand slide-in drawer with a booking's full details and host actions. Esc or a click outside closes it. */
export default function BookingDrawer(props: Props) {
  const { booking, onClose } = props;
  const open = !!booking;
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {booking && (
        <motion.div key="drawer" className="fixed inset-0 z-[70]" initial={{ opacity: 1 }} exit={{ opacity: 1 }}>
          <motion.div className="absolute inset-0 bg-black/45 backdrop-blur-[2px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} aria-hidden />
          <motion.aside
            role="dialog"
            aria-modal="true"
            aria-labelledby="booking-drawer-title"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', stiffness: 320, damping: 34 }}
            className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col border-l border-line bg-[var(--bg-elev)] text-fg shadow-[-30px_0_60px_-30px_rgb(0_0_0/0.6)]"
          >
            <DrawerBody key={booking.code} {...props} booking={booking} />
          </motion.aside>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
