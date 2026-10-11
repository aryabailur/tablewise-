import { useEffect, useRef, type ReactNode } from 'react';
import { motion, useMotionValue, useReducedMotion, useSpring, useTransform } from 'framer-motion';

interface Props {
  children: ReactNode;
  onClick?: () => void;
  variant?: 'primary' | 'ghost';
  radius?: number;
  strength?: number;
}

/** Drifts toward the cursor when it comes within `radius` px, then springs back. */
export default function MagneticButton({ children, onClick, variant = 'primary', radius = 110, strength = 0.35 }: Props) {
  const ref = useRef<HTMLButtonElement>(null);
  const reduce = useReducedMotion();
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const sx = useSpring(x, { stiffness: 220, damping: 15, mass: 0.5 });
  const sy = useSpring(y, { stiffness: 220, damping: 15, mass: 0.5 });
  const ix = useTransform(sx, (v) => v * 0.35);
  const iy = useTransform(sy, (v) => v * 0.35);

  useEffect(() => {
    if (reduce) return;
    const onMove = (e: PointerEvent) => {
      const el = ref.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const cx = r.left + r.width / 2 - sx.get();
      const cy = r.top + r.height / 2 - sy.get();
      const dx = e.clientX - cx;
      const dy = e.clientY - cy;
      if (Math.hypot(dx, dy) < Math.max(r.width, r.height) / 2 + radius) {
        x.set(dx * strength);
        y.set(dy * strength);
      } else {
        x.set(0);
        y.set(0);
      }
    };
    window.addEventListener('pointermove', onMove, { passive: true });
    return () => window.removeEventListener('pointermove', onMove);
  }, [reduce, radius, strength, x, y, sx, sy]);

  const cls =
    variant === 'primary'
      ? 'ember-fill text-on-ember shadow-[0_0_50px_-8px_var(--ember)] hover:shadow-[0_0_70px_-6px_var(--ember)]'
      : 'glass text-fg hover:border-[var(--line-strong)]';
  return (
    <motion.button
      ref={ref}
      type="button"
      onClick={onClick}
      style={{ x: sx, y: sy }}
      whileTap={{ scale: 0.96 }}
      className={`group relative inline-flex items-center justify-center rounded-full px-7 py-4 text-[15px] font-semibold tracking-wide transition-shadow duration-500 ${cls}`}
    >
      <span className="sheen" />
      <motion.span style={{ x: ix, y: iy }} className="relative flex items-center gap-2.5">
        {children}
      </motion.span>
    </motion.button>
  );
}
