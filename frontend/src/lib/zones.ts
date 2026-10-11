const ZONE_LABEL: Record<string, string> = { window: 'Window', garden: 'Garden', bar: 'Bar', private: 'Private' };

export const zoneLabel = (z: string | null | undefined) => (z ? ZONE_LABEL[z] ?? z : '—');
