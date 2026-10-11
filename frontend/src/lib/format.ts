export const rupees = (n: number) => `₹${Math.round(n).toLocaleString('en-IN')}`;
export const priceSymbols = (level: number) => '₹'.repeat(Math.max(1, Math.min(4, Math.round(level) || 1)));
