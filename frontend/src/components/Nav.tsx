import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { CalendarDays, LayoutDashboard, Sparkles, UtensilsCrossed } from 'lucide-react';
import ThemeToggle from './ThemeToggle';

export type View = 'guest' | 'admin';

function Logo() {
  return (
    <svg viewBox="0 0 64 64" className="h-8 w-8" aria-hidden>
      <defs>
        <linearGradient id="logo-flame" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="#b8361a" />
          <stop offset=".55" stopColor="#ff7a3d" />
          <stop offset="1" stopColor="#ffd8b0" />
        </linearGradient>
      </defs>
      <circle cx="32" cy="32" r="30" fill="none" stroke="url(#logo-flame)" strokeOpacity=".45" strokeWidth="1.5" />
      <path d="M32 11c3.8 6.6 11.5 11.4 11.5 21.1A11.5 11.5 0 0 1 32 43.6a11.5 11.5 0 0 1-11.5-11.5c0-4.8 2.3-8.2 4.8-10.9.4 3.4 2.1 5.7 4.6 6.7-.8-6.2.3-11.7 2.1-16.9z" fill="url(#logo-flame)" />
      <path d="M32 43.6V54M32 50c-3.4-.4-6.2-2.4-7.4-5.4M32 47.5c2.9-.2 5.6-1.9 6.6-4.6" fill="none" stroke="#8fbf94" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}

export default function Nav({ view, onViewChange, onReserve, onConcierge }: { view: View; onViewChange: (v: View) => void; onReserve: () => void; onConcierge: () => void }) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 24);
    on();
    window.addEventListener('scroll', on, { passive: true });
    return () => window.removeEventListener('scroll', on);
  }, []);
  const link = 'hidden items-center gap-1.5 rounded-full px-3 py-1.5 text-sm text-muted transition hover:text-fg md:inline-flex';
  return (
    <motion.header initial={{ y: -40, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ duration: 0.7 }} className="fixed inset-x-0 top-0 z-40 px-3 pt-3 sm:px-6 sm:pt-4">
      <nav className={`mx-auto flex max-w-6xl items-center justify-between gap-2 rounded-full px-3 py-2 transition-all duration-500 sm:px-4 ${scrolled ? 'glass-strong' : 'border border-transparent'}`}>
        <a
          href="#top"
          onClick={(e) => {
            e.preventDefault();
            onViewChange('guest');
            window.scrollTo({ top: 0, behavior: 'smooth' });
          }}
          className="flex items-center gap-2.5"
        >
          <Logo />
          <span className="font-wonk text-lg leading-none">Ember &amp; Vine</span>
          <span className="hidden font-mono text-[10px] uppercase tracking-[0.2em] text-faint lg:inline">Tablewise</span>
        </a>
        <div className="flex items-center gap-1 sm:gap-2">
          <button type="button" onClick={onReserve} className={link}>
            <CalendarDays className="h-4 w-4" /> Reserve
          </button>
          <button type="button" onClick={onConcierge} className={link}>
            <Sparkles className="h-4 w-4" /> Concierge
          </button>
          <div role="tablist" aria-label="View" className="relative flex rounded-full border border-line bg-glass p-1">
            {(['guest', 'admin'] as const).map((v) => (
              <button
                key={v}
                type="button"
                role="tab"
                aria-selected={view === v}
                onClick={() => onViewChange(v)}
                className={`relative rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${view === v ? 'text-on-ember' : 'text-muted hover:text-fg'}`}
              >
                {view === v && <motion.span layoutId="view-pill" className="ember-fill absolute inset-0 rounded-full shadow-[0_0_20px_-4px_var(--ember)]" transition={{ type: 'spring', stiffness: 400, damping: 32 }} />}
                <span className="relative flex items-center gap-1.5">
                  {v === 'guest' ? <UtensilsCrossed className="h-3.5 w-3.5" /> : <LayoutDashboard className="h-3.5 w-3.5" />}
                  {v === 'guest' ? 'Guest' : 'Admin'}
                </span>
              </button>
            ))}
          </div>
          <ThemeToggle />
        </div>
      </nav>
    </motion.header>
  );
}
