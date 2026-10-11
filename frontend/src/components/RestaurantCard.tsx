import { motion } from 'framer-motion';
import { Link, useNavigate } from 'react-router-dom';
import { MapPin, Star } from 'lucide-react';
import type { RestaurantListItem } from '../lib/types';
import { priceSymbols, rupees } from '../lib/format';
import { restaurantLink } from '../lib/links';

const FALLBACK_COVER = 'linear-gradient(135deg,#ff7a3d,#5a0f2e)';

function SlotPills({ r, date, party, mini }: { r: RestaurantListItem; date?: string; party?: number; mini?: boolean }) {
  const slots = Array.isArray(r.next_slots) ? r.next_slots.slice(0, 3) : [];
  if (!slots.length) return <p className={`text-faint ${mini ? 'text-[11px]' : 'text-xs'}`}>No open seatings for this search</p>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {slots.map((t) => (
        <Link
          key={t}
          to={restaurantLink(r.slug, { date, party, time: t })}
          onClick={(e) => e.stopPropagation()}
          className={`relative inline-flex items-center rounded-full border border-ember/40 bg-ember/[0.08] font-medium tabular-nums text-fg shadow-[0_0_20px_-8px_var(--ember)] transition hover:border-ember/80 hover:bg-ember/20 hover:text-ember ${
            mini ? 'px-2.5 py-1 text-[11px]' : 'min-h-9 px-3.5 py-1.5 text-sm'
          }`}
        >
          {t}
        </Link>
      ))}
    </div>
  );
}

/** Discover-grid card; `mini` is the compact variant shown inside the concierge chat. */
export default function RestaurantCard({ r, date, party, mini = false, index = 0, onNavigate }: { r: RestaurantListItem; date?: string; party?: number; mini?: boolean; index?: number; onNavigate?: () => void }) {
  const navigate = useNavigate();
  const href = restaurantLink(r.slug, { date, party });
  const go = () => {
    onNavigate?.();
    navigate(href);
  };
  const cuisine = (r.cuisine ?? []).join(' · ');
  return (
    <motion.article
      layout={!mini}
      initial={{ opacity: 0, y: mini ? 8 : 24 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ delay: Math.min(index, 8) * (mini ? 0.05 : 0.06), duration: 0.45 }}
      whileHover={mini ? undefined : { y: -4 }}
      onClick={go}
      onClickCapture={(e) => {
        if ((e.target as HTMLElement).closest('a')) onNavigate?.();
      }}
      className={`group glass flex cursor-pointer flex-col overflow-hidden ${mini ? 'rounded-2xl' : 'rounded-[26px]'}`}
    >
      <div className={`relative overflow-hidden ${mini ? 'h-16' : 'h-40'}`}>
        <div className="absolute inset-0 transition-transform duration-700 group-hover:scale-[1.06]" style={{ background: r.cover_image || FALLBACK_COVER }} />
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-transparent" />
        <div className="absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 p-3 sm:p-4">
          <h3 className={`min-w-0 font-wonk leading-tight text-white drop-shadow ${mini ? 'truncate text-lg' : 'text-2xl'}`}>
            <Link to={href} onClick={(e) => e.stopPropagation()} className="outline-none focus-visible:underline">
              {r.name}
            </Link>
          </h3>
          {typeof r.rating === 'number' && (
            <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-black/45 px-2 py-0.5 text-xs font-semibold text-white backdrop-blur">
              <Star className="h-3 w-3 fill-current text-gold" /> {r.rating.toFixed(1)}
            </span>
          )}
        </div>
      </div>
      <div className={`flex flex-1 flex-col ${mini ? 'gap-2 p-3' : 'gap-3 p-4 sm:p-5'}`}>
        <div className={`flex flex-wrap items-center gap-x-2 gap-y-1 text-muted ${mini ? 'text-[11px]' : 'text-sm'}`}>
          <span className="min-w-0 truncate">{cuisine}</span>
          <span className="text-faint">·</span>
          <span className="inline-flex items-center gap-1">
            <MapPin className="h-3 w-3" /> {r.area}
          </span>
        </div>
        {!mini && (
          <div className="flex items-center justify-between gap-2 text-sm">
            <span className="text-fg">
              {rupees(r.avg_cost_for_two)} <span className="text-faint">for two</span>
            </span>
            <span className="font-mono tracking-wider" aria-label={`Price level ${r.price_level} of 4`}>
              <span className="text-gold">{priceSymbols(r.price_level)}</span>
              <span className="text-faint">{'₹'.repeat(Math.max(0, 4 - priceSymbols(r.price_level).length))}</span>
            </span>
          </div>
        )}
        {!mini && r.tags?.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {r.tags.map((t) => (
              <span key={t} className="rounded-full border border-line px-2 py-0.5 text-[11px] text-faint">
                {t}
              </span>
            ))}
          </div>
        )}
        <div className={mini ? '' : 'mt-auto pt-1'}>
          <SlotPills r={r} date={date} party={party} mini={mini} />
        </div>
      </div>
    </motion.article>
  );
}
