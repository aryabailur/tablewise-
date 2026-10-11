import { useLayoutEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import type { Booking } from '../lib/types';
import { formatDay, hhmm } from '../lib/time';

const ZONE_LABEL: Record<string, string> = { window: 'Window', garden: 'Garden', bar: 'Bar', private: 'Private' };
export const zoneLabel = (z: string | null | undefined) => (z ? ZONE_LABEL[z] ?? z : '—');

function Barcode({ code }: { code: string }) {
  const bars = Array.from(code + code).map((c, i) => 1 + ((c.charCodeAt(0) * (i + 3)) % 4));
  let x = 0;
  return (
    <svg viewBox={`0 0 ${bars.reduce((s, b) => s + b + 2, 0)} 30`} className="h-8 w-40" preserveAspectRatio="none" aria-hidden>
      {bars.map((b, i) => {
        const r = <rect key={i} x={x} y={0} width={b} height={30} style={{ fill: 'currentColor' }} />;
        x += b + 2;
        return r;
      })}
    </svg>
  );
}

/** Ticket-style confirmation card with perforation and notch cut-outs. */
export default function Ticket({ booking, compact = false, action }: { booking: Booking; compact?: boolean; action?: string }) {
  const topRef = useRef<HTMLDivElement>(null);
  const [cutY, setCutY] = useState(compact ? 80 : 210);
  useLayoutEffect(() => {
    const el = topRef.current;
    if (!el) return;
    const update = () => setCutY(el.offsetHeight);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const n = compact ? 9 : 15;
  const mask = `radial-gradient(circle ${n}px at 0 ${cutY}px, transparent ${n - 0.5}px, #000 ${n}px) left / 51% 100% no-repeat, radial-gradient(circle ${n}px at 100% ${cutY}px, transparent ${n - 0.5}px, #000 ${n}px) right / 51% 100% no-repeat`;
  const date = booking.start_time.slice(0, 10);
  const cancelled = booking.status === 'cancelled' || action === 'cancelled';
  const status = action === 'modified' ? 'Updated' : cancelled ? 'Cancelled' : 'Confirmed';
  return (
    <motion.div
      initial={{ opacity: 0, y: 24, rotateX: -18, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, rotateX: 0, scale: 1 }}
      transition={{ type: 'spring', stiffness: 160, damping: 20 }}
      style={{ filter: 'drop-shadow(0 24px 40px rgb(0 0 0 / .45)) drop-shadow(0 0 30px rgb(255 122 61 / .18))', perspective: 800 }}
      className={compact ? 'w-full' : 'mx-auto w-full max-w-md'}
    >
      <div className="ticket relative overflow-hidden rounded-3xl" style={{ WebkitMask: mask, mask }}>
        <div className="sheen sheen-once" />
        <div ref={topRef} className={compact ? 'px-5 pb-4 pt-4' : 'px-7 pb-7 pt-6'}>
          <div className="flex items-center justify-between text-[10px] font-semibold uppercase tracking-[0.28em] opacity-70">
            <span>Ember &amp; Vine</span>
            <span className={`flex items-center gap-1.5 ${cancelled ? 'text-danger' : 'text-ember'}`}>
              <span className="h-1.5 w-1.5 rounded-full bg-current" /> {status}
            </span>
          </div>
          {!compact && <p className="mt-5 text-xs uppercase tracking-[0.2em] opacity-60">Reservation for</p>}
          <p className={compact ? 'mt-2 text-sm opacity-80' : 'mt-1 font-display text-2xl'}>{booking.guest_name}</p>
          <p
            className={`font-display font-semibold tracking-tight text-ember-gradient ${compact ? 'mt-1 text-3xl' : 'mt-4 text-6xl'} ${cancelled ? 'line-through opacity-60' : ''}`}
          >
            {booking.code}
          </p>
          {!compact && <p className="mt-1 text-[11px] uppercase tracking-[0.24em] opacity-50">Booking code</p>}
        </div>
        <div className="mx-6 border-t-2 border-dashed" style={{ borderColor: 'color-mix(in oklab, currentColor 22%, transparent)' }} />
        <div className={`grid grid-cols-3 gap-y-4 ${compact ? 'px-5 py-4 text-xs' : 'px-7 py-6 text-sm'}`}>
          {[
            ['Date', formatDay(date)],
            ['Time', hhmm(booking.start_time)],
            ['Guests', String(booking.party_size)],
            ['Table', booking.table_name ?? '—'],
            ['Zone', zoneLabel(booking.zone)],
            ['Until', booking.end_time ? hhmm(booking.end_time) : '—'],
          ].map(([k, v]) => (
            <div key={k}>
              <div className="text-[10px] uppercase tracking-[0.22em] opacity-50">{k}</div>
              <div className={`mt-1 font-display ${compact ? 'text-base' : 'text-lg'}`}>{v}</div>
            </div>
          ))}
        </div>
        {!compact && (
          <div className="flex items-center justify-between px-7 pb-6 opacity-70">
            <Barcode code={booking.code} />
            <span className="font-mono text-xs tracking-widest">{booking.code}</span>
          </div>
        )}
      </div>
    </motion.div>
  );
}
