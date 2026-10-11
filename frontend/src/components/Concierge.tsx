import { Fragment, memo, useCallback, useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import Markdown from 'react-markdown';
import { ArrowUp, BookOpen, Check, CircleAlert, LoaderCircle, Sparkles, Square, SquarePen, X } from 'lucide-react';
import type { Booking, ChatEvent, GraphNode, Health, Source } from '../lib/types';
import { errorMessage, getHealth, notifyBookingsChanged, streamChat, uuid } from '../lib/api';
import { formatDay, hhmm } from '../lib/time';
import Ticket from './Ticket';

type Block =
  | { kind: 'text'; id: string; text: string }
  | { kind: 'tool'; id: string; name: string; args: Record<string, unknown>; status: 'running' | 'done' | 'error'; result?: unknown }
  | { kind: 'booking'; id: string; action: string; booking: Booking };

interface Turn {
  id: string;
  user: string;
  blocks: Block[];
  sources: Source[];
  intent?: string;
  status: 'streaming' | 'done' | 'error';
  error?: string;
  stopped?: boolean;
  visited: string[];
  current: string | null;
}

const THREAD_KEY = 'tablewise:thread';
const TURNS_KEY = 'tablewise:turns';
const SUGGESTIONS = ['Do you have vegan options?', 'Book a table for 4 tomorrow at 8pm in the garden', "What's your corkage policy?", 'Cancel booking EV-XXXX'];
const NODES: { id: GraphNode; label: string }[] = [
  { id: 'router', label: 'router' },
  { id: 'retrieve', label: 'retrieve' },
  { id: 'booking_agent', label: 'agent' },
  { id: 'tools', label: 'tools' },
  { id: 'respond', label: 'respond' },
];
const NODE_COPY: Record<string, string> = {
  router: 'Reading your request…',
  retrieve: 'Consulting the house notes…',
  booking_agent: 'Checking the reservation book…',
  tools: 'Working the book…',
  respond: 'Composing a reply…',
};

function loadThread(): string {
  try {
    const t = localStorage.getItem(THREAD_KEY);
    if (t) return t;
  } catch {
    /* storage unavailable */
  }
  const id = uuid();
  try {
    localStorage.setItem(THREAD_KEY, id);
  } catch {
    /* ignore */
  }
  return id;
}
function loadTurns(thread: string): Turn[] {
  try {
    const raw = localStorage.getItem(TURNS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as { thread: string; turns: Turn[] };
    if (parsed.thread !== thread || !Array.isArray(parsed.turns)) return [];
    return parsed.turns.map((t) => (t.status === 'streaming' ? { ...t, status: 'done', current: null } : t));
  } catch {
    return [];
  }
}

const str = (v: unknown) => (typeof v === 'string' && v ? v : null);
const num = (v: unknown) => (typeof v === 'number' ? v : typeof v === 'string' && v && !isNaN(+v) ? +v : null);

export function toolLabel(name: string, args: Record<string, unknown>): string {
  const party = num(args.party_size);
  const date = str(args.date);
  const time = str(args.time);
  const zone = str(args.zone);
  const code = str(args.code);
  const guest = str(args.guest_name);
  switch (name) {
    case 'check_availability':
      return `Checking availability${party ? ` for ${party}` : ''}${date ? ` on ${formatDay(date)}` : ''}${time ? ` at ${time}` : ''}${zone ? ` in the ${zone}` : ''}…`;
    case 'create_booking':
      return `Creating booking${guest ? ` for ${guest}` : ''}${party ? ` (${party} ${party === 1 ? 'guest' : 'guests'})` : ''}…`;
    case 'modify_booking': {
      const ch = [party ? `${party} guests` : null, date ? formatDay(date) : null, time, zone].filter(Boolean);
      return `Updating ${code ?? 'booking'}${ch.length ? ` → ${ch.join(', ')}` : ''}…`;
    }
    case 'cancel_booking':
      return `Cancelling ${code ?? 'booking'}…`;
    case 'lookup_booking':
      return `Looking up ${code ?? 'booking'}…`;
    default:
      return `Running ${name.replace(/_/g, ' ')}…`;
  }
}

function asBooking(v: unknown): Booking | null {
  if (!v || typeof v !== 'object') return null;
  const o = v as Record<string, unknown>;
  if (typeof o.code === 'string' && typeof o.start_time === 'string') return o as unknown as Booking;
  if (o.booking) return asBooking(o.booking);
  return null;
}

export function toolSummary(name: string, result: unknown): string {
  if (result == null) return 'Done';
  if (typeof result === 'string') return result.length > 140 ? `${result.slice(0, 140)}…` : result;
  if (typeof result !== 'object') return String(result);
  const r = result as Record<string, unknown>;
  if (typeof r.error === 'string') return r.error;
  const b = asBooking(r);
  if (b) {
    if (name === 'create_booking') return `Booked ${b.code} · table ${b.table_name ?? '—'} at ${hhmm(b.start_time)}`;
    if (name === 'modify_booking') return `Updated ${b.code} · ${b.party_size} guests at ${hhmm(b.start_time)}`;
    if (name === 'cancel_booking') return `Cancelled ${b.code}`;
    return `Found ${b.code} · ${b.guest_name}, ${b.party_size} guests, ${formatDay(b.start_time.slice(0, 10))} ${hhmm(b.start_time)}`;
  }
  if (Array.isArray(r.slots)) {
    const open = (r.slots as Array<Record<string, unknown>>).filter((s) => s && s.available);
    if (!open.length) return 'No open tables';
    return `${open.length} open: ${open.slice(0, 4).map((s) => String(s.time)).join(', ')}${open.length > 4 ? '…' : ''}`;
  }
  if (typeof r.available === 'boolean') {
    const t = (r.best_table ?? r.table) as Record<string, unknown> | undefined;
    return r.available ? `Available${t && t.name ? ` · table ${String(t.name)}` : ''}` : 'Fully booked at that time';
  }
  if (typeof r.message === 'string') return r.message;
  return 'Done';
}

function reduce(t: Turn, e: ChatEvent): Turn {
  switch (e.type) {
    case 'node':
      if (e.status === 'start') return { ...t, current: e.node, visited: t.visited.includes(e.node) ? t.visited : [...t.visited, e.node] };
      return e.intent ? { ...t, intent: e.intent } : t;
    case 'token': {
      const last = t.blocks[t.blocks.length - 1];
      if (last && last.kind === 'text') return { ...t, blocks: [...t.blocks.slice(0, -1), { ...last, text: last.text + e.content }] };
      return { ...t, blocks: [...t.blocks, { kind: 'text', id: uuid(), text: e.content }] };
    }
    case 'tool': {
      if (e.status === 'start') {
        if (t.blocks.some((b) => b.kind === 'tool' && b.id === e.id)) return t;
        return { ...t, blocks: [...t.blocks, { kind: 'tool', id: e.id || uuid(), name: e.name, args: e.args ?? {}, status: 'running' }] };
      }
      const err = !!(e.result && typeof e.result === 'object' && (e.result as Record<string, unknown>).error);
      const status: 'done' | 'error' = err ? 'error' : 'done';
      if (!t.blocks.some((b) => b.kind === 'tool' && b.id === e.id))
        return { ...t, blocks: [...t.blocks, { kind: 'tool', id: e.id || uuid(), name: e.name, args: e.args ?? {}, status, result: e.result }] };
      return { ...t, blocks: t.blocks.map((b) => (b.kind === 'tool' && b.id === e.id ? { ...b, status, result: e.result } : b)) };
    }
    case 'sources':
      return { ...t, sources: Array.isArray(e.sources) ? e.sources : [] };
    case 'booking':
      return { ...t, blocks: [...t.blocks, { kind: 'booking', id: uuid(), action: e.action, booking: e.booking }] };
    case 'error':
      return { ...t, error: e.message };
    case 'done':
      return { ...t, status: t.error ? 'error' : 'done', current: null };
    default:
      return t;
  }
}

function GraphTrace({ visited, current, intent, active }: { visited: string[]; current: string | null; intent?: string; active: boolean }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-line bg-glass px-3 py-2">
      <div className="flex flex-1 items-center">
        {NODES.map((n, i) => {
          const isCur = active && current === n.id;
          const lit = visited.includes(n.id);
          const prevLit = i > 0 && lit && visited.includes(NODES[i - 1].id);
          return (
            <Fragment key={n.id}>
              {i > 0 && (
                <div className="relative mx-1 h-px flex-1 bg-line">
                  <motion.div className="absolute inset-0 origin-left bg-ember" initial={false} animate={{ scaleX: prevLit ? 1 : 0 }} transition={{ duration: 0.4 }} />
                </div>
              )}
              <div className="flex flex-col items-center gap-1">
                <span className="relative flex h-2.5 w-2.5">
                  {isCur && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-ember opacity-75" />}
                  <span
                    className={`relative h-2.5 w-2.5 rounded-full transition-all duration-300 ${
                      isCur ? 'bg-ember shadow-[0_0_12px_var(--ember)]' : lit ? 'bg-ember/70' : 'border border-line-strong bg-transparent'
                    }`}
                  />
                </span>
                <span className={`font-mono text-[9px] ${isCur ? 'text-ember' : lit ? 'text-muted' : 'text-faint'}`}>{n.label}</span>
              </div>
            </Fragment>
          );
        })}
      </div>
      <AnimatePresence>
        {intent && (
          <motion.span
            key={intent}
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0 }}
            className="rounded-full border border-gold/40 bg-gold/10 px-2 py-0.5 font-mono text-[10px] text-gold"
          >
            {intent}
          </motion.span>
        )}
      </AnimatePresence>
    </div>
  );
}

function ToolCard({ name, args, status, result }: { name: string; args: Record<string, unknown>; status: 'running' | 'done' | 'error'; result?: unknown }) {
  const label = toolLabel(name, args);
  return (
    <motion.div layout initial={{ opacity: 0, y: 8, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} className="ml-9 flex items-start gap-3 rounded-2xl border border-line border-l-2 border-l-ember/70 bg-glass px-3.5 py-2.5 text-xs">
      <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center">
        {status === 'running' ? (
          <LoaderCircle className="h-4 w-4 animate-spin text-ember" />
        ) : status === 'error' ? (
          <CircleAlert className="h-4 w-4 text-danger" />
        ) : (
          <motion.span initial={{ scale: 0 }} animate={{ scale: 1 }} className="grid h-4 w-4 place-items-center rounded-full bg-sage/20">
            <Check className="h-3 w-3 text-sage" />
          </motion.span>
        )}
      </span>
      <div className="min-w-0">
        <p className="text-fg/90">{status === 'running' ? label : label.replace(/…$/, '')}</p>
        {status !== 'running' && <p className={`mt-0.5 ${status === 'error' ? 'text-danger' : 'text-muted'}`}>{toolSummary(name, result)}</p>}
      </div>
    </motion.div>
  );
}

function SourceChips({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState<number | null>(null);
  const sorted = [...sources].sort((a, b) => a.index - b.index);
  const cur = sorted.find((s) => s.index === open);
  return (
    <div className="ml-9">
      <div className="mb-1.5 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.2em] text-faint">
        <BookOpen className="h-3 w-3" /> Sources
      </div>
      <div className="flex flex-wrap gap-1.5">
        {sorted.map((s, i) => (
          <motion.button
            key={s.index}
            type="button"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
            onClick={() => setOpen(open === s.index ? null : s.index)}
            className={`rounded-full border px-2.5 py-1 text-[11px] transition ${open === s.index ? 'border-ember/60 bg-ember/10 text-fg' : 'border-line bg-glass text-muted hover:text-fg'}`}
          >
            <span className="font-mono text-ember">[{s.index}]</span> {s.source}
            {s.section ? <span className="text-faint"> · {s.section}</span> : null}
          </motion.button>
        ))}
      </div>
      <AnimatePresence initial={false}>
        {cur && (
          <motion.div key={cur.index} initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="mt-2 rounded-xl border border-line bg-glass p-3 text-xs leading-relaxed text-muted">
              <div className="mb-1 flex justify-between gap-2 text-[10px] uppercase tracking-wider text-faint">
                <span>
                  {cur.source}
                  {cur.section ? ` · ${cur.section}` : ''}
                </span>
                {typeof cur.score === 'number' && <span>relevance {Math.round(cur.score * 100)}%</span>}
              </div>
              <p className="whitespace-pre-wrap">{cur.text}</p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Avatar() {
  return (
    <span className="relative mt-0.5 h-7 w-7 shrink-0">
      <span className="orb-core absolute inset-0 rounded-full" />
      <Sparkles className="absolute inset-0 m-auto h-3.5 w-3.5 text-white" />
    </span>
  );
}

const TurnView = memo(function TurnView({ turn, onRetry }: { turn: Turn; onRetry: (text: string) => void }) {
  const lastIdx = turn.blocks.length - 1;
  const lastIsText = turn.blocks[lastIdx]?.kind === 'text';
  return (
    <div className="space-y-3">
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex justify-end">
        <div className="ember-fill max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tr-md px-4 py-2.5 text-[14.5px] text-on-ember shadow-[0_8px_30px_-12px_var(--ember)]">{turn.user}</div>
      </motion.div>
      {turn.blocks.map((b, i) =>
        b.kind === 'text' ? (
          <motion.div key={b.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex gap-2">
            <Avatar />
            <div className={`prose-chat min-w-0 max-w-[88%] rounded-2xl rounded-tl-md border border-line bg-glass-hi px-4 py-3 text-[14.5px] leading-relaxed ${turn.status === 'streaming' && i === lastIdx ? 'stream-caret' : ''}`}>
              <Markdown
                components={{
                  a: ({ href, children }) => (
                    <a href={href} target="_blank" rel="noreferrer">
                      {children}
                    </a>
                  ),
                }}
              >
                {b.text}
              </Markdown>
            </div>
          </motion.div>
        ) : b.kind === 'tool' ? (
          <ToolCard key={b.id} name={b.name} args={b.args} status={b.status} result={b.result} />
        ) : (
          <div key={b.id} className="ml-9">
            <Ticket booking={b.booking} compact action={b.action} />
          </div>
        ),
      )}
      {turn.status === 'streaming' && !lastIsText && (
        <div className="flex items-center gap-2.5 pl-1 text-sm text-muted">
          <span className="flex gap-1">
            {[0, 1, 2].map((i) => (
              <motion.span key={i} className="h-1.5 w-1.5 rounded-full bg-ember" animate={{ opacity: [0.25, 1, 0.25], y: [0, -3, 0] }} transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.15 }} />
            ))}
          </span>
          {turn.current ? NODE_COPY[turn.current] ?? 'Thinking…' : 'Connecting…'}
        </div>
      )}
      {turn.sources.length > 0 && <SourceChips sources={turn.sources} />}
      {turn.stopped && <p className="ml-9 text-xs text-faint">Stopped.</p>}
      {turn.error && (
        <div className="ml-9 flex items-start gap-2 rounded-2xl border border-danger/30 bg-danger/10 p-3 text-xs">
          <CircleAlert className="h-4 w-4 shrink-0 text-danger" />
          <span className="flex-1">{turn.error}</span>
          <button type="button" onClick={() => onRetry(turn.user)} className="text-ember hover:underline">
            Retry
          </button>
        </div>
      )}
    </div>
  );
});

function useIsDesktop() {
  const [m, setM] = useState(() => window.matchMedia('(min-width: 768px)').matches);
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 768px)');
    const on = () => setM(mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return m;
}

export default function Concierge({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const isDesktop = useIsDesktop();
  const [threadId, setThreadId] = useState(loadThread);
  const [turns, setTurns] = useState<Turn[]>(() => loadTurns(loadThread()));
  const [input, setInput] = useState('');
  const [health, setHealth] = useState<Health | null>(null);
  const [healthState, setHealthState] = useState<'loading' | 'ok' | 'down'>('loading');
  const abortRef = useRef<AbortController | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const stick = useRef(true);
  const streaming = turns.some((t) => t.status === 'streaming');
  const last = turns[turns.length - 1];

  const checkHealth = useCallback(async () => {
    setHealthState('loading');
    try {
      setHealth(await getHealth());
      setHealthState('ok');
    } catch {
      setHealth(null);
      setHealthState('down');
    }
  }, []);
  useEffect(() => {
    checkHealth();
  }, [checkHealth]);
  useEffect(() => {
    if (open && healthState === 'down') checkHealth();
    if (open) {
      const t = window.setTimeout(() => inputRef.current?.focus(), 250);
      return () => window.clearTimeout(t);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (streaming) return;
    try {
      localStorage.setItem(TURNS_KEY, JSON.stringify({ thread: threadId, turns: turns.slice(-30) }));
    } catch {
      /* ignore */
    }
  }, [turns, streaming, threadId]);

  useEffect(() => {
    const el = listRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [turns, open]);

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 144)}px`;
  }, [input, open]);

  useEffect(() => {
    if (!open || isDesktop) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open, isDesktop]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const send = useCallback(
    async (raw: string) => {
      const msg = raw.trim();
      if (!msg || abortRef.current) return;
      const turnId = uuid();
      stick.current = true;
      setTurns((ts) => [...ts, { id: turnId, user: msg, blocks: [], sources: [], status: 'streaming', visited: [], current: null }]);
      setInput('');
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      const update = (fn: (t: Turn) => Turn) => setTurns((ts) => ts.map((t) => (t.id === turnId ? fn(t) : t)));
      try {
        await streamChat(
          msg,
          threadId,
          (evt) => {
            if (evt.type === 'booking') notifyBookingsChanged(evt.booking);
            update((t) => reduce(t, evt));
          },
          ctrl.signal,
        );
        update((t) => (t.status === 'streaming' ? { ...t, status: t.error ? 'error' : 'done', current: null } : t));
      } catch (e) {
        if (ctrl.signal.aborted) update((t) => ({ ...t, status: 'done', current: null, stopped: true }));
        else update((t) => ({ ...t, status: 'error', current: null, error: errorMessage(e) }));
      } finally {
        abortRef.current = null;
      }
    },
    [threadId],
  );
  const sendRef = useRef(send);
  sendRef.current = send;
  const retry = useCallback((text: string) => sendRef.current(text), []);

  const newConversation = () => {
    abortRef.current?.abort();
    const id = uuid();
    try {
      localStorage.setItem(THREAD_KEY, id);
    } catch {
      /* ignore */
    }
    setThreadId(id);
    setTurns([]);
    setInput('');
    inputRef.current?.focus();
  };

  const pick = (s: string) => {
    if (s.includes('XXXX')) {
      setInput(s);
      window.setTimeout(() => {
        const el = inputRef.current;
        if (!el) return;
        el.focus();
        const at = s.indexOf('XXXX');
        el.setSelectionRange(at, at + 4);
      }, 30);
    } else send(s);
  };

  const badge =
    healthState === 'loading'
      ? { text: '…', cls: 'border-line text-faint', title: 'Checking…' }
      : healthState === 'down'
        ? { text: 'Offline', cls: 'border-danger/40 text-danger', title: 'Server unreachable' }
        : health?.llm
          ? { text: 'Live', cls: 'border-sage/40 text-sage', title: [health.provider, health.model, health.documents != null ? `${health.documents} docs` : null].filter(Boolean).join(' · ') }
          : { text: 'Demo mode', cls: 'border-gold/40 text-gold', title: 'Offline demo mode — no language model configured' };

  return (
    <>
      <AnimatePresence>
        {!open && (
          <motion.button
            key="orb"
            type="button"
            onClick={() => onOpenChange(true)}
            aria-label="Open the concierge (Ctrl+K)"
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            whileHover={{ scale: 1.08 }}
            whileTap={{ scale: 0.94 }}
            className="group fixed bottom-5 right-5 z-50 grid h-16 w-16 place-items-center rounded-full sm:bottom-7 sm:right-7"
          >
            <span className="orb-halo absolute -inset-4 rounded-full" />
            <span className="orb-ring absolute -inset-[3px] rounded-full" />
            <span className="orb-core absolute inset-0 rounded-full" />
            <span className="orb-swirl absolute inset-1 rounded-full" />
            <Sparkles className="relative h-6 w-6 text-white drop-shadow" />
            <span className="glass-strong pointer-events-none absolute right-full mr-3 hidden whitespace-nowrap rounded-full px-3 py-1.5 text-xs text-fg opacity-0 transition group-hover:opacity-100 md:block">
              Concierge · Ctrl K
            </span>
          </motion.button>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {open && !isDesktop && (
          <motion.div key="scrim" className="fixed inset-0 z-[60] bg-black/50 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => onOpenChange(false)} />
        )}
      </AnimatePresence>
      <AnimatePresence>
        {open && (
          <motion.aside
            key="drawer"
            role="dialog"
            aria-label="Concierge chat"
            initial={isDesktop ? { x: '110%', opacity: 0.5 } : { y: '100%' }}
            animate={isDesktop ? { x: 0, opacity: 1 } : { y: 0 }}
            exit={isDesktop ? { x: '110%', opacity: 0.5 } : { y: '100%' }}
            transition={{ type: 'spring', stiffness: 260, damping: 30 }}
            className={`glass-strong fixed z-[70] flex flex-col overflow-hidden ${
              isDesktop ? 'bottom-4 right-4 top-4 w-[min(440px,calc(100vw-2rem))] rounded-[28px]' : 'inset-x-0 bottom-0 h-[88dvh] rounded-t-[28px]'
            }`}
          >
            {!isDesktop && (
              <div className="flex justify-center pb-1 pt-2.5">
                <span className="h-1.5 w-11 rounded-full bg-fg/20" />
              </div>
            )}
            <div className="flex items-center gap-3 border-b border-line px-4 py-3.5">
              <span className="relative h-10 w-10 shrink-0">
                <span className="orb-core absolute inset-0 rounded-full" />
                <Sparkles className="absolute inset-0 m-auto h-4 w-4 text-white" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <h2 className="font-display text-lg leading-none">The Concierge</h2>
                  <span title={badge.title} className={`rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider ${badge.cls}`}>
                    {badge.text}
                  </span>
                </div>
                <p className="mt-1 truncate text-xs text-muted">Menu, wine &amp; reservations — ask anything.</p>
              </div>
              <button type="button" onClick={newConversation} title="New conversation" aria-label="New conversation" className="grid h-9 w-9 place-items-center rounded-full text-muted transition hover:bg-glass-hi hover:text-fg">
                <SquarePen className="h-4 w-4" />
              </button>
              <button type="button" onClick={() => onOpenChange(false)} aria-label="Close" className="grid h-9 w-9 place-items-center rounded-full text-muted transition hover:bg-glass-hi hover:text-fg">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div
              ref={listRef}
              onScroll={() => {
                const el = listRef.current;
                if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
              }}
              className="scroll-thin flex-1 space-y-6 overflow-y-auto px-4 py-5"
            >
              {turns.length === 0 ? (
                <div className="flex h-full flex-col items-center justify-center px-2 text-center">
                  <motion.p initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="font-wonk text-3xl">
                    Good evening.
                  </motion.p>
                  <p className="mt-2 max-w-[19rem] text-sm text-muted">I'm the house concierge. Ask about the menu, our wines, house policies — or let me find you a table.</p>
                  <div className="mt-6 flex flex-wrap justify-center gap-2">
                    {SUGGESTIONS.map((s, i) => (
                      <motion.button
                        key={s}
                        type="button"
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.15 + i * 0.07 }}
                        onClick={() => pick(s)}
                        className="rounded-full border border-line bg-glass px-3.5 py-2 text-xs text-fg/90 transition hover:border-ember/60 hover:text-ember"
                      >
                        {s}
                      </motion.button>
                    ))}
                  </div>
                </div>
              ) : (
                turns.map((t) => <TurnView key={t.id} turn={t} onRetry={retry} />)
              )}
            </div>

            <div className="space-y-2.5 border-t border-line p-3">
              <GraphTrace visited={last?.visited ?? []} current={last?.current ?? null} intent={last?.intent} active={streaming} />
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  send(input);
                }}
                className="relative"
              >
                <textarea
                  ref={inputRef}
                  rows={1}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                      e.preventDefault();
                      send(input);
                    }
                  }}
                  placeholder="Ask about the menu, wine, or a table…"
                  className="field max-h-36 min-h-[50px] resize-none pr-14"
                />
                {streaming ? (
                  <button type="button" onClick={() => abortRef.current?.abort()} aria-label="Stop" className="absolute bottom-2 right-2 grid h-9 w-9 place-items-center rounded-full border border-line bg-glass-hi text-fg">
                    <Square className="h-3.5 w-3.5" />
                  </button>
                ) : (
                  <button type="submit" disabled={!input.trim()} aria-label="Send" className="ember-fill absolute bottom-2 right-2 grid h-9 w-9 place-items-center rounded-full text-on-ember shadow-[0_0_20px_-4px_var(--ember)] transition disabled:opacity-30">
                    <ArrowUp className="h-4 w-4" />
                  </button>
                )}
              </form>
              <p className="hidden text-center text-[10px] text-faint md:block">Enter to send · Shift+Enter for a new line · Esc to close</p>
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    </>
  );
}
