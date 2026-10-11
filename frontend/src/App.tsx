import { useEffect, useState, type ReactNode } from 'react';
import { AnimatePresence, MotionConfig, motion } from 'framer-motion';
import { Link, Route, Routes, matchPath, useLocation } from 'react-router-dom';
import Background from './components/Background';
import Nav from './components/Nav';
import AdminTimeline from './components/AdminTimeline';
import Concierge from './components/Concierge';
import Discover from './pages/Discover';
import RestaurantPage from './pages/Restaurant';
import BookingLookup from './pages/BookingLookup';
import { nameFromSlug, useRestaurant } from './lib/restaurants';

const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

function Page({ children }: { children: ReactNode }) {
  return (
    <motion.main
      initial={{ opacity: 0, y: 18, filter: 'blur(6px)' }}
      animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
      exit={{ opacity: 0, y: -12, filter: 'blur(4px)' }}
      transition={{ duration: 0.38, ease: EASE }}
      onAnimationStart={(def) => {
        // Start each new page at the top, unless it deep-links to a section.
        if (typeof def === 'object' && def && 'opacity' in def && def.opacity === 1 && !window.location.hash) window.scrollTo({ top: 0 });
      }}
    >
      {children}
    </motion.main>
  );
}

function NotFound() {
  return (
    <section className="mx-auto max-w-xl px-6 pb-28 pt-40 text-center">
      <p className="text-xs font-semibold uppercase tracking-[0.35em] text-ember">404</p>
      <h1 className="mt-3 font-wonk text-5xl">No table here</h1>
      <p className="mt-3 text-muted">That page doesn't exist. Let's find you somewhere to eat instead.</p>
      <Link to="/" className="ember-fill mt-7 inline-flex rounded-full px-6 py-3 text-sm font-semibold text-on-ember">
        Discover restaurants
      </Link>
    </section>
  );
}

/** The restaurant the visitor is looking at, so the concierge can scope its answers. */
function useRouteRestaurant(pathname: string) {
  const m = matchPath('/r/:slug', pathname) ?? matchPath('/book/:slug', pathname);
  const slug = m?.params.slug ?? null;
  const { restaurant } = useRestaurant(slug);
  return slug ? { slug, name: restaurant?.name ?? nameFromSlug(slug) } : null;
}

export default function App() {
  const location = useLocation();
  const [chatOpen, setChatOpen] = useState(false);
  const restaurant = useRouteRestaurant(location.pathname);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setChatOpen((o) => !o);
      } else if (e.key === 'Escape') setChatOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <MotionConfig reducedMotion="user">
      <div className="relative min-h-dvh overflow-x-clip">
        <Background />
        <Nav onConcierge={() => setChatOpen(true)} />
        <AnimatePresence mode="wait" initial={false}>
          <Routes location={location} key={location.pathname}>
            <Route path="/" element={<Page><Discover /></Page>} />
            <Route path="/r/:slug" element={<Page><RestaurantPage variant="full" /></Page>} />
            <Route path="/book/:slug" element={<Page><RestaurantPage variant="book" /></Page>} />
            <Route path="/bookings" element={<Page><BookingLookup /></Page>} />
            <Route path="/bookings/:code" element={<Page><BookingLookup /></Page>} />
            <Route path="/admin" element={<Page><AdminTimeline /></Page>} />
            <Route path="*" element={<Page><NotFound /></Page>} />
          </Routes>
        </AnimatePresence>
        <Concierge open={chatOpen} onOpenChange={setChatOpen} restaurant={restaurant} />
      </div>
    </MotionConfig>
  );
}
