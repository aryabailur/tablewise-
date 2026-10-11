const ZONE_LABEL: Record<string, string> = { window: 'Window', garden: 'Garden', bar: 'Bar', private: 'Private', rooftop: 'Rooftop', patio: 'Patio' };

export const zoneLabel = (z: string | null | undefined) => (z ? ZONE_LABEL[z] ?? z.charAt(0).toUpperCase() + z.slice(1) : '—');

const ZONE_COLOR: Record<string, string> = {
  window: 'var(--z-window)',
  garden: 'var(--z-garden)',
  bar: 'var(--z-bar)',
  private: 'var(--z-private)',
  rooftop: 'var(--z-rooftop)',
  patio: 'var(--z-patio)',
};
export const zoneColor = (z: string | null | undefined) => (z && ZONE_COLOR[z]) || 'var(--ember)';
/** Preferred display order; unknown zones follow alphabetically. */
export const ZONE_ORDER = ['window', 'rooftop', 'patio', 'garden', 'bar', 'private'];
