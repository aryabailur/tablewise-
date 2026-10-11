import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useSearchParams } from 'react-router-dom';
import { CalendarDays, CircleAlert, Clock, Minus, Plus, RotateCcw, Search, SlidersHorizontal, Sparkles, Users, X } from 'lucide-react';
import type { RestaurantListItem } from '../lib/types';
import { errorMessage, listRestaurants, type RestaurantQuery } from '../lib/api';
import { useAllRestaurants } from '../lib/restaurants';
import { formatDay, nextDays, toISODate } from '../lib/time';
import { useDocumentTitle } from '../lib/jsonld';
import RestaurantCard from '../components/RestaurantCard';

const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];
// Fallbacks from the shared contract so filters still render while the API is unreachable.
const FALLBACK_AREAS = ['Andheri', 'Bandra', 'Colaba', 'Juhu', 'Lower Parel', 'Powai'];
const FALLBACK_CUISINES = ['Coastal', 'Gujarati', 'Italian', 'Japanese', 'Modern European', 'North Indian', 'Pan-Asian', 'Seafood', 'Thali'];
const FALLBACK_TAGS = ['bar', 'live-music', 'pet-friendly', 'pure-veg', 'rooftop'];
const TIMES: { value: string; label: string }[] = [
  { value: '', label: 'From now' },
  { value: 'any', label: 'Any time' },
  { value: '12:00', label: 'Lunch · 12:00' },
  { value: '19:00', label: 'Evening · 19:00' },
  { value: '20:00', label: '20:00' },
  { value: '21:00', label: 'Late · 21:00' },
];

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`relative shrink-0 rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors ${active ? 'border-transparent text-on-ember' : 'border-line bg-glass text-muted hover:border-ember/50 hover:text-fg'}`}
    >
      {active && <motion.span className="ember-fill absolute inset-0 rounded-full shadow-[0_0_18px_-6px_var(--ember)]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} />}
      <span className="relative">{children}</span>
    </button>
  );
}

function ChipRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <span className="w-16 shrink-0 text-[10px] font-semibold uppercase tracking-[0.24em] text-faint">{label}</span>
      <div className="no-scrollbar -my-1 flex min-w-0 flex-1 gap-2 overflow-x-auto px-0.5 py-1">{children}</div>
    </div>
  );
}

function CardSkeleton({ i }: { i: number }) {
  const style = { '--shimmer-delay': `${i * 90}ms` } as CSSProperties;
  return (
    <div className="glass overflow-hidden rounded-[26px]" aria-hidden>
      <div className="shimmer h-40 rounded-none" style={style} />
      <div className="space-y-3 p-5">
        <span className="shimmer-bar block h-3 w-2/3 rounded-full" />
        <span className="shimmer-bar block h-3 w-1/3 rounded-full" />
        <div className="flex gap-2 pt-2">
          {[0, 1, 2].map((k) => (
            <span key={k} className="shimmer block h-8 w-16 rounded-full" style={style} />
          ))}
        </div>
      </div>
    </div>
  );
}

const uniqSorted = (xs: string[]) => [...new Set(xs)].sort((a, b) => a.localeCompare(b));

export default function Discover() {
  useDocumentTitle('Tablewise · Discover Mumbai restaurants');
  const [params, setParams] = useSearchParams();
  const days = useMemo(() => nextDays(14), []);
  const today = toISODate(days[0]);

  const q = params.get('q') ?? '';
  const area = params.get('area') ?? '';
  const cuisine = params.get('cuisine') ?? '';
  const price = Number(params.get('price')) || 0;
  const tags = (params.get('tags') ?? '').split(',').filter(Boolean);
  const date = params.get('date') || today;
  const party = Math.min(12, Math.max(1, Number(params.get('party')) || 2));
  const time = params.get('time') ?? '';

  const set = (patch: Record<string, string | number | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === '' || v === 0) next.delete(k);
      else next.set(k, String(v));
    }
    setParams(next, { replace: true });
  };

  // The search box is local so typing stays snappy; it syncs to the URL after a pause.
  const [draft, setDraft] = useState(q);
  const [draftFor, setDraftFor] = useState(q);
  if (q !== draftFor) {
    setDraftFor(q);
    setDraft(q);
  }
  useEffect(() => {
    if (draft === q) return;
    const t = window.setTimeout(() => {
      const next = new URLSearchParams(window.location.search);
      if (draft.trim()) next.set('q', draft.trim());
      else next.delete('q');
      setParams(next, { replace: true });
    }, 300);
    return () => window.clearTimeout(t);
  }, [draft, q, setParams]);

  const { restaurants: all } = useAllRestaurants();
  const areas = all.length ? uniqSorted(all.map((r) => r.area)) : FALLBACK_AREAS;
  const cuisines = all.length ? uniqSorted(all.flatMap((r) => r.cuisine ?? [])) : FALLBACK_CUISINES;
  const allTags = all.length ? uniqSorted(all.flatMap((r) => r.tags ?? [])) : FALLBACK_TAGS;

  const query: RestaurantQuery = {
    q: q || undefined,
    area: area || undefined,
    cuisine: cuisine || undefined,
    price_level: price || undefined,
    tags,
    party_size: party,
    date,
    time: time === 'any' ? '00:00' : time || (date === today ? undefined : '00:00'),
  };
  const key = JSON.stringify(query);
  const [nonce, setNonce] = useState(0);
  const [result, setResult] = useState<{ key: string; data: RestaurantListItem[]; error: string | null }>({ key: '', data: [], error: null });
  useEffect(() => {
    let live = true;
    const t = window.setTimeout(() => {
      listRestaurants(JSON.parse(key) as RestaurantQuery)
        .then((data) => live && setResult({ key, data: Array.isArray(data) ? data : [], error: null }))
        .catch((e) => live && setResult((prev) => ({ key, data: prev.data, error: errorMessage(e) })));
    }, 120);
    return () => {
      live = false;
      window.clearTimeout(t);
    };
  }, [key, nonce]);
  const pending = result.key !== key;
  const firstLoad = pending && !result.key;
  const error = !pending ? result.error : null;
  const list = result.data;

  const filtersOn = !!(q || area || cuisine || price || tags.length);
  const clear = () => {
    setDraft('');
    set({ q: null, area: null, cuisine: null, price: null, tags: null });
  };
  const toggleTag = (t: string) => set({ tags: (tags.includes(t) ? tags.filter((x) => x !== t) : [...tags, t]).join(',') || null });

  return (
    <div>
      <section id="top" className="relative px-4 pb-10 pt-32 text-center sm:px-6 sm:pt-40">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05, duration: 0.7 }}
          className="glass-soft mb-7 inline-flex items-center gap-2.5 rounded-full px-4 py-1.5 text-xs font-medium uppercase tracking-[0.22em] text-muted"
        >
          <Sparkles className="h-3.5 w-3.5 text-ember" /> Mumbai · six tables worth crossing town for
        </motion.div>
        <motion.h1
          initial={{ opacity: 0, y: 24, filter: 'blur(12px)' }}
          animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
          transition={{ duration: 1, ease: EASE }}
          className="mx-auto max-w-4xl text-balance font-wonk text-[clamp(2.8rem,8vw,6rem)] leading-[0.98] tracking-[-0.02em]"
        >
          Find your table <em className="text-ember-gradient pr-2">tonight</em>
        </motion.h1>
        <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.35, duration: 0.8 }} className="mx-auto mt-5 max-w-xl text-pretty text-muted">
          Wood-fire in Lower Parel, coastal Malvani in Juhu, a thali that never ends in Andheri. Search, pick a seating, done.
        </motion.p>

        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25, duration: 0.8, ease: EASE }} className="glass-strong mx-auto mt-9 max-w-3xl rounded-[28px] p-2 text-left">
          <label className="relative flex items-center">
            <Search className="pointer-events-none absolute left-4 h-5 w-5 text-faint" />
            <span className="sr-only">Search restaurants</span>
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Search a dish, cuisine, area or vibe…"
              className="h-14 w-full rounded-[22px] bg-transparent pl-12 pr-12 text-base text-fg outline-none placeholder:text-faint"
              type="search"
              enterKeyHint="search"
            />
            {draft && (
              <button type="button" onClick={() => setDraft('')} aria-label="Clear search" className="absolute right-3 grid h-8 w-8 place-items-center rounded-full text-muted hover:bg-glass-hi hover:text-fg">
                <X className="h-4 w-4" />
              </button>
            )}
          </label>
          <div className="grid grid-cols-1 gap-2 border-t border-line p-2 pt-3 sm:grid-cols-3">
            <label className="flex items-center gap-2 rounded-2xl border border-line bg-glass px-3 py-2">
              <CalendarDays className="h-4 w-4 shrink-0 text-ember" />
              <span className="sr-only">Date</span>
              <select value={date} onChange={(e) => set({ date: e.target.value === today ? null : e.target.value })} className="min-w-0 flex-1 cursor-pointer bg-transparent text-sm text-fg outline-none [&>option]:bg-[var(--bg-elev)]">
                {days.map((d, i) => {
                  const iso = toISODate(d);
                  return (
                    <option key={iso} value={iso}>
                      {i === 0 ? `Today · ${formatDay(iso)}` : i === 1 ? `Tomorrow · ${formatDay(iso)}` : formatDay(iso)}
                    </option>
                  );
                })}
                {!days.some((d) => toISODate(d) === date) && <option value={date}>{formatDay(date)}</option>}
              </select>
            </label>
            <div className="flex items-center gap-2 rounded-2xl border border-line bg-glass px-3 py-1.5">
              <Users className="h-4 w-4 shrink-0 text-ember" />
              <span className="flex-1 text-sm">
                {party} {party === 1 ? 'guest' : 'guests'}
              </span>
              <button type="button" onClick={() => set({ party: party - 1 === 2 ? null : party - 1 })} disabled={party <= 1} aria-label="Fewer guests" className="grid h-8 w-8 place-items-center rounded-full border border-line hover:text-ember disabled:opacity-30">
                <Minus className="h-3.5 w-3.5" />
              </button>
              <button type="button" onClick={() => set({ party: party + 1 === 2 ? null : party + 1 })} disabled={party >= 12} aria-label="More guests" className="grid h-8 w-8 place-items-center rounded-full border border-line hover:text-ember disabled:opacity-30">
                <Plus className="h-3.5 w-3.5" />
              </button>
            </div>
            <label className="flex items-center gap-2 rounded-2xl border border-line bg-glass px-3 py-2">
              <Clock className="h-4 w-4 shrink-0 text-ember" />
              <span className="sr-only">Time</span>
              <select value={time} onChange={(e) => set({ time: e.target.value || null })} className="min-w-0 flex-1 cursor-pointer bg-transparent text-sm text-fg outline-none [&>option]:bg-[var(--bg-elev)]">
                {TIMES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.value === '' && date !== today ? 'Any time' : t.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </motion.div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-28 sm:px-6">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.45 }} className="glass-soft space-y-3 rounded-3xl p-4">
          <ChipRow label="Area">
            {areas.map((a) => (
              <Chip key={a} active={area === a} onClick={() => set({ area: area === a ? null : a })}>
                {a}
              </Chip>
            ))}
          </ChipRow>
          <ChipRow label="Cuisine">
            {cuisines.map((c) => (
              <Chip key={c} active={cuisine === c} onClick={() => set({ cuisine: cuisine === c ? null : c })}>
                {c}
              </Chip>
            ))}
          </ChipRow>
          <ChipRow label="Price">
            {[1, 2, 3, 4].map((p) => (
              <Chip key={p} active={price === p} onClick={() => set({ price: price === p ? null : p })}>
                <span className="font-mono tracking-wider">{'₹'.repeat(p)}</span>
              </Chip>
            ))}
          </ChipRow>
          <ChipRow label="Vibe">
            {allTags.map((t) => (
              <Chip key={t} active={tags.includes(t)} onClick={() => toggleTag(t)}>
                {t}
              </Chip>
            ))}
          </ChipRow>
        </motion.div>

        <div className="mb-5 mt-8 flex items-center justify-between gap-3 text-sm">
          <p className="flex items-center gap-2 text-muted">
            <SlidersHorizontal className="h-4 w-4 text-faint" />
            {firstLoad ? 'Finding tables…' : `${list.length} ${list.length === 1 ? 'restaurant' : 'restaurants'} · ${formatDay(date)} · ${party} ${party === 1 ? 'guest' : 'guests'}`}
            {pending && !firstLoad && <span className="text-faint">· updating…</span>}
          </p>
          {filtersOn && (
            <button type="button" onClick={clear} className="inline-flex items-center gap-1 text-xs text-ember hover:underline">
              <X className="h-3 w-3" /> Clear filters
            </button>
          )}
        </div>

        {error && (
          <div className="mb-6 flex items-start gap-3 rounded-2xl border border-danger/30 bg-danger/10 p-4 text-sm">
            <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
            <span className="flex-1">{error}</span>
            <button type="button" onClick={() => setNonce((n) => n + 1)} className="inline-flex items-center gap-1 text-xs text-ember hover:underline">
              <RotateCcw className="h-3 w-3" /> Retry
            </button>
          </div>
        )}

        {firstLoad ? (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }, (_, i) => (
              <CardSkeleton key={i} i={i} />
            ))}
          </div>
        ) : list.length ? (
          <motion.div layout className={`grid gap-5 transition-opacity sm:grid-cols-2 lg:grid-cols-3 ${pending ? 'opacity-70' : ''}`}>
            <AnimatePresence mode="popLayout">
              {list.map((r, i) => (
                <RestaurantCard key={r.slug} r={r} date={date} party={party} index={i} />
              ))}
            </AnimatePresence>
          </motion.div>
        ) : (
          !error && (
            <div className="glass rounded-3xl p-10 text-center">
              <p className="font-wonk text-2xl">Nothing matches that, yet.</p>
              <p className="mt-2 text-sm text-muted">Try another area or loosen a filter - or ask the concierge for ideas.</p>
              {filtersOn && (
                <button type="button" onClick={clear} className="glass-soft mt-5 rounded-full px-5 py-2 text-sm hover:text-ember">
                  Clear filters
                </button>
              )}
            </div>
          )
        )}
      </section>
    </div>
  );
}
