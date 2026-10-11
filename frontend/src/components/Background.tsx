import { useEffect } from 'react';
import { motion, useMotionValue, useReducedMotion, useSpring, useTransform, type MotionValue } from 'framer-motion';

const ORBS = [
  { size: 'min(56vw,640px)', left: '-8%', top: '-6%', color: 'var(--mesh-a)', depth: 46, opacity: 0.3, duration: 28 },
  { size: 'min(64vw,760px)', left: '52%', top: '-14%', color: 'var(--mesh-b)', depth: -34, opacity: 0.7, duration: 34 },
  { size: 'min(46vw,520px)', left: '64%', top: '48%', color: 'var(--mesh-d)', depth: 62, opacity: 0.26, duration: 24 },
  { size: 'min(58vw,660px)', left: '-14%', top: '52%', color: 'var(--mesh-b)', depth: -58, opacity: 0.55, duration: 31 },
  { size: 'min(30vw,340px)', left: '38%', top: '30%', color: 'var(--ember)', depth: 96, opacity: 0.14, duration: 20 },
];

function Orb({ o, sx, sy, reduce }: { o: (typeof ORBS)[number]; sx: MotionValue<number>; sy: MotionValue<number>; reduce: boolean }) {
  const x = useTransform(sx, (v) => v * o.depth);
  const y = useTransform(sy, (v) => v * o.depth);
  return (
    <motion.div className="absolute" style={{ left: o.left, top: o.top, width: o.size, height: o.size, x, y }}>
      <motion.div
        className="h-full w-full rounded-full"
        style={{ background: `radial-gradient(circle, ${o.color} 0%, transparent 62%)`, opacity: o.opacity }}
        animate={reduce ? undefined : { x: [0, 50, -30, 0], y: [0, -40, 30, 0], scale: [1, 1.1, 0.95, 1] }}
        transition={{ duration: o.duration, repeat: Infinity, ease: 'easeInOut' }}
      />
    </motion.div>
  );
}

export default function Background() {
  const reduce = !!useReducedMotion();
  const mx = useMotionValue(0);
  const my = useMotionValue(0);
  const sx = useSpring(mx, { stiffness: 40, damping: 18 });
  const sy = useSpring(my, { stiffness: 40, damping: 18 });
  useEffect(() => {
    if (reduce) return;
    const onMove = (e: PointerEvent) => {
      mx.set(e.clientX / window.innerWidth - 0.5);
      my.set(e.clientY / window.innerHeight - 0.5);
    };
    window.addEventListener('pointermove', onMove, { passive: true });
    return () => window.removeEventListener('pointermove', onMove);
  }, [reduce, mx, my]);
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-base">
      <div className="bg-mesh" />
      <div className="bg-mesh-2" />
      {ORBS.map((o, i) => (
        <Orb key={i} o={o} sx={sx} sy={sy} reduce={reduce} />
      ))}
      <div className="bg-vignette" />
      <div className="bg-grain" />
    </div>
  );
}
