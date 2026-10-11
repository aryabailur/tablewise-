import { useEffect, useState } from 'react';
import { AnimatePresence, MotionConfig, motion } from 'framer-motion';
import Background from './components/Background';
import Nav, { type View } from './components/Nav';
import Hero from './components/Hero';
import BookingPanel from './components/BookingPanel';
import AdminTimeline from './components/AdminTimeline';
import Concierge from './components/Concierge';

export default function App() {
  const [view, setView] = useState<View>(() => (window.location.hash === '#admin' ? 'admin' : 'guest'));
  const [chatOpen, setChatOpen] = useState(false);

  useEffect(() => {
    const url = window.location.pathname + window.location.search + (view === 'admin' ? '#admin' : '');
    window.history.replaceState(null, '', url);
  }, [view]);

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

  const scrollToReserve = () => document.getElementById('reserve')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  const goReserve = () => {
    if (view !== 'guest') {
      setView('guest');
      window.setTimeout(scrollToReserve, 450);
    } else scrollToReserve();
  };

  return (
    <MotionConfig reducedMotion="user">
      <div className="relative min-h-dvh overflow-x-clip">
        <Background />
        <Nav view={view} onViewChange={setView} onReserve={goReserve} onConcierge={() => setChatOpen(true)} />
        <AnimatePresence mode="wait">
          {view === 'guest' ? (
            <motion.main key="guest" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.35 }}>
              <Hero onReserve={goReserve} onConcierge={() => setChatOpen(true)} />
              <BookingPanel />
              <footer className="mx-auto max-w-6xl px-6 pb-28 pt-6 text-center text-xs text-faint">
                <p className="font-wonk text-lg text-muted">Ember &amp; Vine</p>
                <p className="mt-2">214 Larkspur Lane, Hudson Quarter · Open nightly 5–11 pm</p>
                <p className="mt-1 font-mono uppercase tracking-[0.2em]">Reservations by Tablewise</p>
              </footer>
            </motion.main>
          ) : (
            <motion.main key="admin" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.35 }}>
              <AdminTimeline />
            </motion.main>
          )}
        </AnimatePresence>
        <Concierge open={chatOpen} onOpenChange={setChatOpen} />
      </div>
    </MotionConfig>
  );
}
