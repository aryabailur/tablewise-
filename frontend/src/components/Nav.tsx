import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Link, useLocation } from 'react-router-dom';
import { Compass, LayoutDashboard, Sparkles, Ticket } from 'lucide-react';
import ThemeToggle from './ThemeToggle';
import { lastBooking } from '../lib/api';

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

const TABS = [
  { id: 'discover', label: 'Discover', icon: Compass },
  { id: 'booking', label: 'My booking', icon: Ticket },
  { id: 'admin', label: 'Admin', icon: LayoutDashboard },
] as const;

function activeTab(path: string): string {
  if (path.startsWith('/admin')) return 'admin';
  if (path.startsWith('/bookings')) return 'booking';
  return 'discover';
}

export default function Nav({ onConcierge }: { onConcierge: () => void }) {
  const { pathname } = useLocation();
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 24);
    on();
    window.addEventListener('scroll', on, { passive: true });
    return () => window.removeEventListener('scroll', on);
  }, []);
  const active = activeTab(pathname);
  const hrefFor = (id: string) => {
    if (id === 'admin') return '/admin';
    if (id === 'booking') {
      const last = lastBooking();
      return last?.code ? `/bookings/${encodeURIComponent(last.code)}` : '/bookings';
    }
    return '/';
  };
  return (
    <motion.header initial={{ y: -40, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ duration: 0.7 }} className="fixed inset-x-0 top-0 z-40 px-3 pt-3 sm:px-6 sm:pt-4">
      <nav aria-label="Main" className={`mx-auto flex max-w-6xl items-center justify-between gap-2 rounded-full px-3 py-2 transition-all duration-500 sm:px-4 ${scrolled ? 'glass-strong' : 'border border-transparent'}`}>
        <Link to="/" className="flex shrink-0 items-center gap-2.5" aria-label="Tablewise home">
          <Logo />
          <span className="hidden font-wonk text-lg leading-none sm:inline">Tablewise</span>
          <span className="hidden font-mono text-[10px] uppercase tracking-[0.2em] text-faint lg:inline">Mumbai</span>
        </Link>
        <div className="flex items-center gap-1 sm:gap-2">
          <button type="button" onClick={onConcierge} className="hidden items-center gap-1.5 rounded-full px-3 py-1.5 text-sm text-muted transition hover:text-fg md:inline-flex">
            <Sparkles className="h-4 w-4" /> Concierge
          </button>
          <div className="relative flex rounded-full border border-line bg-glass p-1">
            {TABS.map(({ id, label, icon: Icon }) => (
              <Link
                key={id}
                to={hrefFor(id)}
                aria-current={active === id ? 'page' : undefined}
                aria-label={label}
                className={`relative rounded-full px-2.5 py-1.5 text-xs font-medium transition-colors sm:px-3 ${active === id ? 'text-on-ember' : 'text-muted hover:text-fg'}`}
              >
                {active === id && <motion.span layoutId="view-pill" className="ember-fill absolute inset-0 rounded-full shadow-[0_0_20px_-4px_var(--ember)]" transition={{ type: 'spring', stiffness: 400, damping: 32 }} />}
                <span className="relative flex items-center gap-1.5">
                  <Icon className="h-3.5 w-3.5" />
                  <span className={active === id ? 'inline' : 'hidden sm:inline'}>{label}</span>
                </span>
              </Link>
            ))}
          </div>
          <ThemeToggle />
        </div>
      </nav>
    </motion.header>
  );
}
