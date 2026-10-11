/** Zones are free text per restaurant (window | garden | bar | private | rooftop | patio …). */
export type Zone = string;
export interface Table { id: number; name: string; capacity: number; zone: Zone; is_active: boolean }
export interface TableRef { id: number; name: string; capacity: number; zone: Zone }
export interface Slot { time: string; start: string; available: boolean; available_tables: TableRef[]; best_table: TableRef | null }
export interface Availability { date: string; party_size: number; restaurant_slug?: string; slots: Slot[] }
export interface Restaurant {
  slug: string; name: string; code_prefix: string; cuisine: string[]; area: string; price_level: number; rating: number;
  avg_cost_for_two: number; tags: string[]; hours_open: string; hours_close: string; slot_minutes: number; cover_image: string; description: string;
}
export interface RestaurantListItem extends Restaurant { next_slots: string[] }
export interface RestaurantDetail extends Restaurant { docs?: { about?: string; menu?: string; policies?: string } }
export interface Booking {
  id: number; code: string; restaurant_slug?: string; restaurant_name?: string; guest_name: string; phone: string | null; email: string | null;
  party_size: number; start_time: string; end_time: string; duration_min: number;
  table_id: number | null; table_name: string | null; zone: Zone | null;
  status: 'confirmed' | 'cancelled'; source?: string | null; notes: string | null; created_at: string;
}
export type BookingSource = 'web' | 'chat' | 'mcp' | 'google' | 'phone';
export interface BookingCreate { guest_name: string; party_size: number; start_time: string; phone?: string; email?: string; notes?: string; zone?: Zone; table_id?: number; source?: BookingSource }
export interface Health { status: string; llm: boolean; model?: string | null; provider?: string | null; documents?: number | null; restaurants?: number | null }
export type GraphNode = 'router' | 'retrieve' | 'booking_agent' | 'tools' | 'respond';
export interface Source { index: number; source: string; section?: string | null; text: string; score?: number | null; restaurant_slug?: string | null }
export type ChatEvent =
  | { type: 'node'; node: GraphNode; status: 'start' | 'end'; intent?: string }
  | { type: 'token'; content: string }
  | { type: 'tool'; id: string; name: string; status: 'start' | 'end'; args?: Record<string, unknown>; result?: unknown }
  | { type: 'sources'; sources: Source[] }
  | { type: 'restaurants'; restaurants: RestaurantListItem[] }
  | { type: 'booking'; action: 'created' | 'modified' | 'cancelled'; booking: Booking }
  | { type: 'error'; message: string }
  | { type: 'done' };
