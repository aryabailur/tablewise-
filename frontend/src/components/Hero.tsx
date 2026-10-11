import { Fragment, useLayoutEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { ArrowRight, Clock, MapPin, Sparkles } from 'lucide-react';
import MagneticButton from './MagneticButton';

const WORDS = ['Ember', '&', 'Vine'];
const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

/** Letter-by-letter reveal; each letter carries a slice of one continuous, slowly shimmering gradient. */
function ShimmerTitle() {
  const ref = useRef<HTMLHeadingElement>(null);
  const [m, setM] = useState<{ w: number; offsets: number[] } | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const spans = Array.from(el.querySelectorAll<HTMLElement>('[data-ch]'));
      setM({ w: Math.max(1, el.offsetWidth), offsets: spans.map((s) => s.offsetLeft) });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    document.fonts?.ready.then(measure).catch(() => undefined);
    return () => ro.disconnect();
  }, []);
  let idx = 0;
  return (
    <h1
      ref={ref}
      aria-label="Ember & Vine"
      className="title-shimmer relative font-wonk text-[clamp(3.6rem,13vw,10.5rem)] font-medium leading-[0.95] tracking-[-0.03em]"
    >
      {WORDS.map((word, wi) => (
        <Fragment key={wi}>
          <span aria-hidden className="inline-block whitespace-nowrap">
            {Array.from(word).map((ch) => {
              const i = idx++;
              const off = m?.offsets[i] ?? 0;
              return (
                <motion.span
                  key={i}
                  data-ch
                  className={`inline-block ${word === '&' ? 'italic font-light' : ''}`}
                  initial={{ y: '0.5em', opacity: 0, rotate: 6, filter: 'blur(14px)' }}
                  animate={{ y: '0em', opacity: 1, rotate: 0, filter: 'blur(0px)' }}
                  transition={{ delay: 0.25 + i * 0.065, duration: 1.15, ease: EASE }}
                  style={{
                    padding: '0.08em 0.06em',
                    margin: '-0.08em -0.06em',
                    backgroundImage: 'var(--title-gradient)',
                    backgroundSize: m ? `${m.w}px 100%` : '100% 100%',
                    backgroundRepeat: 'repeat-x',
                    backgroundPosition: m ? `calc(var(--shimmer-x) * ${m.w}px - ${off}px) 0` : '0 0',
                    WebkitBackgroundClip: 'text',
                    backgroundClip: 'text',
                    color: 'transparent',
                    WebkitTextFillColor: 'transparent',
                  }}
                >
                  {ch}
                </motion.span>
              );
            })}
          </span>
          {wi < WORDS.length - 1 && ' '}
        </Fragment>
      ))}
    </h1>
  );
}

export default function Hero({ onReserve, onConcierge }: { onReserve: () => void; onConcierge: () => void }) {
  const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.userAgent);
  return (
    <section id="top" className="relative flex min-h-[100svh] flex-col items-center justify-center px-4 pb-20 pt-28 text-center">
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1, duration: 0.8 }}
        className="glass-soft mb-8 inline-flex items-center gap-2.5 rounded-full px-4 py-1.5 text-xs font-medium uppercase tracking-[0.22em] text-muted"
      >
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-ember opacity-60" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-ember" />
        </span>
        Now taking reservations
      </motion.div>
      <div className="relative">
        <div aria-hidden className="title-glow pointer-events-none absolute inset-0 select-none font-wonk text-[clamp(3.6rem,13vw,10.5rem)] leading-[0.95]">
          Ember &amp; Vine
        </div>
        <ShimmerTitle />
      </div>
      <motion.p
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 1.15, duration: 0.9, ease: EASE }}
        className="mt-7 flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-xs uppercase tracking-[0.32em] text-muted sm:text-sm"
      >
        {['Wood-fire cooking', 'Natural wines', 'Late nights'].map((t, i) => (
          <Fragment key={t}>
            {i > 0 && <span aria-hidden className="h-1.5 w-1.5 rotate-45 bg-ember shadow-[0_0_10px_var(--ember)]" />}
            <span>{t}</span>
          </Fragment>
        ))}
      </motion.p>
      <motion.div
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 1.4, duration: 0.9, ease: EASE }}
        className="mt-11 flex flex-col items-center gap-4 sm:flex-row"
      >
        <MagneticButton onClick={onReserve}>
          Reserve a table <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
        </MagneticButton>
        <MagneticButton onClick={onConcierge} variant="ghost">
          <Sparkles className="h-4 w-4 text-ember" /> Ask the concierge
          <kbd className="ml-1 rounded-md border border-line px-1.5 py-0.5 font-mono text-[10px] text-faint">{isMac ? '⌘K' : 'Ctrl K'}</kbd>
        </MagneticButton>
      </motion.div>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.8, duration: 1 }}
        className="mt-12 flex flex-col items-center gap-2 text-sm text-muted sm:flex-row sm:gap-5"
      >
        <span className="inline-flex items-center gap-2">
          <Clock className="h-4 w-4 text-gold" /> Open nightly 5–11 pm
        </span>
        <span aria-hidden className="hidden h-1 w-1 rounded-full bg-faint sm:block" />
        <span className="inline-flex items-center gap-2">
          <MapPin className="h-4 w-4 text-gold" /> 214 Larkspur Lane, Hudson Quarter
        </span>
      </motion.div>
      <div aria-hidden className="absolute bottom-7 left-1/2 flex -translate-x-1/2 flex-col items-center gap-2 text-[10px] uppercase tracking-[0.3em] text-faint">
        Scroll
        <span className="scroll-cue block h-10 w-px bg-gradient-to-b from-ember to-transparent" />
      </div>
    </section>
  );
}
