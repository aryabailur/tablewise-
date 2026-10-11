import { Briefcase, Cake, Heart, Leaf, MessageSquareText, Sparkles, TriangleAlert, Wine } from 'lucide-react';
import type { Booking, BookingStatus, Occasion } from '../lib/types';
import { STATUS_LABEL, allergyLabel, dietaryLabel, hasExtras, occasionLabel, statusColor } from '../lib/booking';

/** Status pill for all five booking statuses; colours come from --st-* theme tokens. */
export function StatusPill({ status, className = '' }: { status: BookingStatus; className?: string }) {
  const c = statusColor(status);
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${className}`}
      style={{ color: c, borderColor: `color-mix(in oklab, ${c} 45%, transparent)`, background: `color-mix(in oklab, ${c} 14%, transparent)` }}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function OccasionIcon({ occasion, className = 'h-4 w-4' }: { occasion: Occasion | undefined; className?: string }) {
  switch (occasion) {
    case 'birthday':
      return <Cake className={className} />;
    case 'anniversary':
      return <Heart className={className} />;
    case 'business':
      return <Briefcase className={className} />;
    case 'date':
      return <Wine className={className} />;
    default:
      return <Sparkles className={className} />;
  }
}

export function AllergyChip({ allergy }: { allergy: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold"
      style={{ color: 'var(--allergy)', borderColor: 'color-mix(in oklab, var(--allergy) 50%, transparent)', background: 'color-mix(in oklab, var(--allergy) 14%, transparent)' }}
    >
      <TriangleAlert className="h-3 w-3" /> {allergyLabel(allergy)}
    </span>
  );
}

export function DietChip({ label }: { label: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold"
      style={{ color: 'var(--diet)', borderColor: 'color-mix(in oklab, var(--diet) 50%, transparent)', background: 'color-mix(in oklab, var(--diet) 14%, transparent)' }}
    >
      <Leaf className="h-3 w-3" /> {label}
    </span>
  );
}

/** Allergies, dietary, occasion and special requests; renders nothing when the guest left them all empty. */
export function BookingExtrasView({ booking, inkClass = 'opacity-60' }: { booking: Booking; inkClass?: string }) {
  if (!hasExtras(booking)) return null;
  const { allergies = [], dietary, occasion, special_requests } = booking;
  return (
    <div className="space-y-3 text-sm">
      {allergies.length > 0 && (
        <div>
          <div className={`text-[10px] uppercase tracking-[0.22em] ${inkClass}`}>Allergies</div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {allergies.map((a) => (
              <AllergyChip key={a} allergy={a} />
            ))}
          </div>
        </div>
      )}
      {dietary && dietary !== 'none' && (
        <div>
          <div className={`text-[10px] uppercase tracking-[0.22em] ${inkClass}`}>Dietary</div>
          <div className="mt-1.5">
            <DietChip label={dietaryLabel(dietary)} />
          </div>
        </div>
      )}
      {occasion && occasion !== 'none' && (
        <div>
          <div className={`text-[10px] uppercase tracking-[0.22em] ${inkClass}`}>Occasion</div>
          <div className="mt-1 flex items-center gap-1.5 font-medium">
            <OccasionIcon occasion={occasion} /> {occasionLabel(occasion)}
          </div>
        </div>
      )}
      {special_requests?.trim() && (
        <div>
          <div className={`text-[10px] uppercase tracking-[0.22em] ${inkClass}`}>Special requests</div>
          <p className="mt-1 flex gap-1.5 whitespace-pre-wrap break-words">
            <MessageSquareText className="mt-0.5 h-4 w-4 shrink-0 opacity-70" /> {special_requests}
          </p>
        </div>
      )}
    </div>
  );
}
