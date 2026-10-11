import type { Allergy, Booking, BookingStatus, Dietary, Occasion } from './types';

export const STATUSES: BookingStatus[] = ['confirmed', 'seated', 'completed', 'no_show', 'cancelled'];
export const STATUS_LABEL: Record<BookingStatus, string> = {
  confirmed: 'Confirmed',
  seated: 'Seated',
  completed: 'Completed',
  no_show: 'No-show',
  cancelled: 'Cancelled',
};
export const statusOf = (b: Pick<Booking, 'status'>): BookingStatus => (STATUSES.includes(b.status) ? b.status : 'confirmed');
export const statusColor = (s: BookingStatus) => `var(--st-${s})`;

export const ALLERGIES: Allergy[] = ['nuts', 'peanuts', 'gluten', 'dairy', 'shellfish', 'fish', 'eggs', 'soy', 'sesame'];
export const DIETARY: { value: Dietary; label: string }[] = [
  { value: 'none', label: 'No preference' },
  { value: 'veg', label: 'Vegetarian' },
  { value: 'vegan', label: 'Vegan' },
  { value: 'jain', label: 'Jain' },
  { value: 'halal', label: 'Halal' },
];
export const OCCASIONS: { value: Occasion; label: string }[] = [
  { value: 'none', label: 'Just dinner' },
  { value: 'birthday', label: 'Birthday' },
  { value: 'anniversary', label: 'Anniversary' },
  { value: 'business', label: 'Business' },
  { value: 'date', label: 'Date night' },
];
export const dietaryLabel = (d: Dietary | undefined) => DIETARY.find((x) => x.value === d)?.label ?? 'No preference';
export const occasionLabel = (o: Occasion | undefined) => OCCASIONS.find((x) => x.value === o)?.label ?? 'Just dinner';
export const allergyLabel = (a: string) => a.charAt(0).toUpperCase() + a.slice(1);

export const hasAllergies = (b: Booking) => (b.allergies?.length ?? 0) > 0;
export const isCelebration = (b: Booking) => b.occasion === 'birthday' || b.occasion === 'anniversary';
export const hasExtras = (b: Booking) =>
  hasAllergies(b) || (!!b.dietary && b.dietary !== 'none') || (!!b.occasion && b.occasion !== 'none') || !!b.special_requests?.trim();
