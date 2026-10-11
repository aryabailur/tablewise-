import { useEffect } from 'react';
import type { Restaurant } from './types';
import { priceSymbols } from './format';

const DAYS = 'Mo,Tu,We,Th,Fr,Sa,Su';

export function restaurantJsonLd(r: Restaurant, origin = window.location.origin) {
  const reserveUrl = `${origin}/book/${r.slug}`;
  return {
    '@context': 'https://schema.org',
    '@type': 'Restaurant',
    '@id': `${origin}/r/${r.slug}`,
    name: r.name,
    description: r.description || undefined,
    url: `${origin}/r/${r.slug}`,
    servesCuisine: r.cuisine,
    priceRange: priceSymbols(r.price_level),
    address: { '@type': 'PostalAddress', addressLocality: `${r.area}, Mumbai`, addressRegion: 'Maharashtra', addressCountry: 'IN' },
    openingHours: r.hours_open && r.hours_close ? `${DAYS} ${r.hours_open}-${r.hours_close}` : undefined,
    acceptsReservations: true,
    potentialAction: {
      '@type': 'ReserveAction',
      target: {
        '@type': 'EntryPoint',
        urlTemplate: reserveUrl,
        inLanguage: 'en-IN',
        actionPlatform: ['http://schema.org/DesktopWebPlatform', 'http://schema.org/MobileWebPlatform'],
      },
      result: { '@type': 'FoodEstablishmentReservation', name: `Table at ${r.name}` },
    },
  };
}

/** Injects one schema.org JSON-LD block into <head> while the page is mounted. */
export function useRestaurantJsonLd(r: Restaurant | null | undefined) {
  useEffect(() => {
    if (!r) return;
    const el = document.createElement('script');
    el.type = 'application/ld+json';
    el.dataset.tablewise = 'restaurant';
    el.textContent = JSON.stringify(restaurantJsonLd(r));
    document.head.appendChild(el);
    return () => el.remove();
  }, [r]);
}

export function useDocumentTitle(title: string) {
  useEffect(() => {
    const prev = document.title;
    document.title = title;
    return () => {
      document.title = prev;
    };
  }, [title]);
}
