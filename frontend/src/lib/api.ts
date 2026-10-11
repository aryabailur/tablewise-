import type { Availability, Booking, BookingCreate, ChatEvent, Health, RestaurantDetail, RestaurantListItem, Table } from './types';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}
const OFFLINE = 'We cannot reach the restaurant right now. Please try again in a moment.';
const UNAVAILABLE = 'This part of Tablewise is not available right now. Please try again shortly.';
const CHAT_OFFLINE = 'The concierge is offline right now. Please try again shortly.';

function detailOf(body: unknown): string | null {
  if (!body || typeof body !== 'object') return null;
  const d = (body as { detail?: unknown }).detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map((x) => (x && typeof x === 'object' && 'msg' in x ? String((x as { msg: unknown }).msg) : String(x))).join('; ');
  return null;
}

async function request<T>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: opts.method ?? 'GET',
      headers: opts.body !== undefined ? { 'Content-Type': 'application/json', Accept: 'application/json' } : { Accept: 'application/json' },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(OFFLINE, 0);
  }
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!res.ok) {
    const d = detailOf(body);
    // FastAPI's bare "Not Found" means the route itself is missing (an older or restarting server).
    if (res.status === 404 && (!d || d === 'Not Found')) throw new ApiError(UNAVAILABLE, 404);
    throw new ApiError(d ?? (res.status >= 500 ? OFFLINE : `Request failed (${res.status})`), res.status);
  }
  if (body === null && text) throw new ApiError(OFFLINE, res.status);
  return body as T;
}

export const errorMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));
export const getHealth = () => request<Health>('/api/health');
const enc = encodeURIComponent;
const qs = (params: Record<string, string | number | null | undefined>) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : '';
};

export interface RestaurantQuery { q?: string; area?: string; cuisine?: string; price_level?: number | null; tags?: string[]; party_size?: number; date?: string; time?: string }
export const listRestaurants = (f: RestaurantQuery = {}) =>
  request<RestaurantListItem[]>(`/api/restaurants${qs({ ...f, tags: f.tags?.length ? f.tags.join(',') : undefined })}`);
export const getRestaurant = (slug: string) => request<RestaurantDetail>(`/api/restaurants/${enc(slug)}`);
export const getTables = (slug: string) => request<Table[]>(`/api/restaurants/${enc(slug)}/tables`);
export const getAvailability = (slug: string, date: string, party: number) =>
  request<Availability>(`/api/restaurants/${enc(slug)}/availability${qs({ date, party_size: party })}`);
export const createBooking = (slug: string, b: BookingCreate) => request<Booking>(`/api/restaurants/${enc(slug)}/bookings`, { method: 'POST', body: b });
export const getBooking = (code: string) => request<Booking>(`/api/bookings/${enc(code)}`);
export const cancelBooking = (code: string) => request<Booking>(`/api/bookings/${enc(code)}`, { method: 'DELETE' });
export const listBookings = (date?: string, restaurant?: string) => request<Booking[]>(`/api/bookings${qs({ date, restaurant })}`);

export const BOOKING_CHANGED = 'tablewise:booking-changed';
const LAST_BOOKING_KEY = 'tablewise:last-booking';
export type LastBooking = { code: string; start_time: string; restaurant_slug?: string };

/** Tell open views a booking changed, and remember it so views mounted later (the admin tab) can jump to it. */
export const notifyBookingsChanged = (booking?: Booking) => {
  if (booking) {
    try {
      localStorage.setItem(LAST_BOOKING_KEY, JSON.stringify({ code: booking.code, start_time: booking.start_time, restaurant_slug: booking.restaurant_slug }));
    } catch {
      /* storage unavailable: live views still get the event */
    }
  }
  window.dispatchEvent(new CustomEvent<Booking | undefined>(BOOKING_CHANGED, { detail: booking }));
};

export function lastBooking(): LastBooking | null {
  try {
    const raw = localStorage.getItem(LAST_BOOKING_KEY);
    return raw ? (JSON.parse(raw) as LastBooking) : null;
  } catch {
    return null;
  }
}

export function uuid(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  const b = new Uint8Array(16);
  for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

/** POST /api/chat and parse the SSE stream (`data: {json}` + blank line) event by event. */
export async function streamChat(
  message: string,
  threadId: string,
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
  restaurantSlug?: string | null,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ message, thread_id: threadId, restaurant_slug: restaurantSlug ?? null }),
      signal,
    });
  } catch (e) {
    if (signal?.aborted) throw e;
    throw new ApiError(CHAT_OFFLINE, 0);
  }
  if (!res.ok || !res.body) {
    let d: string | null = null;
    try {
      d = detailOf(JSON.parse(await res.text()));
    } catch {
      d = null;
    }
    throw new ApiError(d ?? CHAT_OFFLINE, res.status);
  }
  const flush = (block: string) => {
    const data = block
      .split('\n')
      .filter((l) => l.startsWith('data:'))
      .map((l) => l.slice(5).replace(/^ /, ''));
    if (!data.length) return;
    const payload = data.join('\n').trim();
    if (!payload || payload === '[DONE]') return;
    try {
      onEvent(JSON.parse(payload) as ChatEvent);
    } catch {
      /* ignore malformed event */
    }
  };
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, '\n');
    let idx = buffer.indexOf('\n\n');
    while (idx >= 0) {
      flush(buffer.slice(0, idx));
      buffer = buffer.slice(idx + 2);
      idx = buffer.indexOf('\n\n');
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) flush(buffer.replace(/\r\n/g, '\n'));
}
