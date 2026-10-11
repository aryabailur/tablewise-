import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import Markdown from 'react-markdown';
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeft, CircleAlert, Clock, MapPin, RotateCcw, Sparkles, Star } from 'lucide-react';
import BookingPanel from '../components/BookingPanel';
import { nameFromSlug, useRestaurant } from '../lib/restaurants';
import { useDocumentTitle, useRestaurantJsonLd } from '../lib/jsonld';
import { priceSymbols, rupees } from '../lib/format';
import { restaurantLink } from '../lib/links';
import type { RestaurantDetail } from '../lib/types';

const TABS = [
  { id: 'about', label: 'About' },
  { id: 'menu', label: 'Menu' },
  { id: 'policies', label: 'Policies' },
] as const;
type TabId = (typeof TABS)[number]['id'];
const FALLBACK_COVER = 'linear-gradient(135deg,#ff7a3d,#5a0f2e)';

function Facts({ r }: { r: RestaurantDetail }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-white/85">
      <span className="inline-flex items-center gap-1.5">
        <Star className="h-4 w-4 fill-current text-gold" /> {r.rating?.toFixed(1)}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <MapPin className="h-4 w-4" /> {r.area}, Mumbai
      </span>
      <span className="inline-flex items-center gap-1.5">
        <Clock className="h-4 w-4" /> {r.hours_open}–{r.hours_close === '23:59' ? '00:00' : r.hours_close}
      </span>
      <span>
        {rupees(r.avg_cost_for_two)} for two · <span className="font-mono text-gold">{priceSymbols(r.price_level)}</span>
      </span>
    </div>
  );
}

function Docs({ r }: { r: RestaurantDetail }) {
  const [tab, setTab] = useState<TabId>('about');
  const md = r.docs?.[tab]?.trim();
  return (
    <section className="mx-auto max-w-4xl px-4 pt-10 sm:px-6">
      <div role="tablist" aria-label="Restaurant information" className="relative inline-flex rounded-full border border-line bg-glass p-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`relative rounded-full px-4 py-2 text-sm font-medium transition-colors ${tab === t.id ? 'text-on-ember' : 'text-muted hover:text-fg'}`}
          >
            {tab === t.id && <motion.span layoutId="doc-tab" className="ember-fill absolute inset-0 rounded-full shadow-[0_0_20px_-4px_var(--ember)]" transition={{ type: 'spring', stiffness: 400, damping: 32 }} />}
            <span className="relative">{t.label}</span>
          </button>
        ))}
      </div>
      <div className="glass mt-5 rounded-[28px] p-6 sm:p-9">
        <AnimatePresence mode="wait">
          <motion.div key={tab} role="tabpanel" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.25 }} className="prose-doc">
            {md ? (
              <Markdown
                components={{
                  a: ({ href, children }) => (
                    <a href={href} target="_blank" rel="noreferrer">
                      {children}
                    </a>
                  ),
                }}
              >
                {md}
              </Markdown>
            ) : tab === 'about' && r.description ? (
              <p>{r.description}</p>
            ) : (
              <p className="text-faint">Nothing here yet - ask the concierge, it knows the house notes.</p>
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </section>
  );
}

/** /r/:slug (full restaurant page) and /book/:slug (booking-focused "Reserve" entry point). */
export default function RestaurantPage({ variant = 'full' }: { variant?: 'full' | 'book' }) {
  const { slug = '' } = useParams();
  const [params] = useSearchParams();
  const location = useLocation();
  const { restaurant: r, loading, error, reload } = useRestaurant(slug);
  const name = r?.name ?? nameFromSlug(slug);
  const book = variant === 'book';
  useDocumentTitle(`${name} · ${book ? 'Reserve' : 'Tablewise'}`);
  useRestaurantJsonLd(r);

  const date = params.get('date');
  const party = Number(params.get('party')) || null;
  const time = params.get('time');

  // Deep links from slot pills land on the booking panel with that seating chosen.
  useEffect(() => {
    if (location.hash !== '#reserve' && !(book && time)) return;
    const t = window.setTimeout(() => document.getElementById('reserve')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 450);
    return () => window.clearTimeout(t);
  }, [location.hash, book, time]);

  const cover = r?.cover_image || FALLBACK_COVER;

  return (
    <div>
      <header className={`relative overflow-hidden ${book ? 'pt-24' : 'pt-24 sm:pt-28'}`}>
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <motion.div
            className={`relative overflow-hidden rounded-[32px] shadow-[var(--shadow-card)] ${book ? 'min-h-[180px]' : 'min-h-[300px] sm:min-h-[380px]'}`}
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.6 }}
          >
            <div className="absolute inset-0" style={{ background: cover }} />
            <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/25 to-black/10" />
            <div className={`relative flex h-full flex-col justify-end ${book ? 'min-h-[180px] p-5 pt-16 sm:p-7 sm:pt-20' : 'min-h-[300px] p-6 pt-20 sm:min-h-[380px] sm:p-10'}`}>
              <Link to={book ? restaurantLink(slug) : '/'} className="absolute left-5 top-5 inline-flex items-center gap-1.5 rounded-full bg-black/35 px-3 py-1.5 text-xs text-white/90 backdrop-blur hover:bg-black/50 sm:left-7 sm:top-7">
                <ArrowLeft className="h-3.5 w-3.5" /> {book ? 'Restaurant details' : 'All restaurants'}
              </Link>
              {r && (
                <p className="mb-2 text-xs font-semibold uppercase tracking-[0.3em] text-white/75">
                  {r.cuisine.join(' · ')}
                </p>
              )}
              <h1 className={`font-wonk leading-[0.98] text-white drop-shadow ${book ? 'text-4xl sm:text-5xl' : 'text-5xl sm:text-7xl'}`}>{name}</h1>
              {r ? (
                <div className="mt-4">
                  <Facts r={r} />
                </div>
              ) : loading ? (
                <span className="shimmer-bar mt-5 block h-3 w-64 rounded-full" />
              ) : null}
              {r && !book && r.tags.length > 0 && (
                <div className="mt-4 flex flex-wrap gap-1.5">
                  {r.tags.map((t) => (
                    <span key={t} className="rounded-full border border-white/25 bg-black/20 px-2.5 py-0.5 text-[11px] text-white/80 backdrop-blur">
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
          {error && (
            <div className="mt-4 flex items-start gap-3 rounded-2xl border border-danger/30 bg-danger/10 p-4 text-sm">
              <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
              <span className="flex-1">{error}</span>
              <button type="button" onClick={reload} className="inline-flex items-center gap-1 text-xs text-ember hover:underline">
                <RotateCcw className="h-3 w-3" /> Retry
              </button>
            </div>
          )}
          {r && !book && r.description && <p className="mx-auto mt-8 max-w-3xl text-pretty text-center font-display text-xl italic leading-relaxed text-muted sm:text-2xl">{r.description}</p>}
          {book && (
            <p className="mt-4 flex items-center justify-center gap-2 text-center text-xs text-faint">
              <Sparkles className="h-3.5 w-3.5 text-ember" /> Instant confirmation · Reservations by Tablewise
            </p>
          )}
        </div>
      </header>

      {r && !book && <Docs r={r} />}

      <BookingPanel key={slug} slug={slug} restaurantName={name} initialDate={date} initialParty={party} initialTime={time} compact={book} source="web" />

      <footer className="mx-auto max-w-6xl px-6 pb-28 pt-2 text-center text-xs text-faint">
        <p className="font-wonk text-lg text-muted">{name}</p>
        {r && (
          <p className="mt-2">
            {r.area}, Mumbai · Open daily {r.hours_open}–{r.hours_close === '23:59' ? '00:00' : r.hours_close}
          </p>
        )}
        <p className="mt-1 font-mono uppercase tracking-[0.2em]">Reservations by Tablewise</p>
      </footer>
    </div>
  );
}
