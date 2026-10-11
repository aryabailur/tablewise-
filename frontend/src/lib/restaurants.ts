import { useEffect, useState } from 'react';
import { errorMessage, getRestaurant, listRestaurants } from './api';
import type { RestaurantDetail, RestaurantListItem } from './types';

/** Shared, de-duplicated fetches: the nav, admin selector and concierge all ask for the same data. */
let allPromise: Promise<RestaurantListItem[]> | null = null;
const detailCache = new Map<string, Promise<RestaurantDetail>>();

export function fetchAllRestaurants(force = false): Promise<RestaurantListItem[]> {
  if (!allPromise || force) {
    allPromise = listRestaurants().then((r) => (Array.isArray(r) ? r : []));
    allPromise.catch(() => {
      allPromise = null; // let the next caller retry
    });
  }
  return allPromise;
}

export function fetchRestaurant(slug: string, force = false): Promise<RestaurantDetail> {
  let p = detailCache.get(slug);
  if (!p || force) {
    p = getRestaurant(slug);
    detailCache.set(slug, p);
    p.catch(() => detailCache.delete(slug));
  }
  return p;
}

interface Loaded<T> { key: string; data: T | null; error: string | null }

export function useAllRestaurants() {
  const [nonce, setNonce] = useState(0);
  const [state, setState] = useState<Loaded<RestaurantListItem[]>>({ key: '', data: null, error: null });
  const key = String(nonce);
  useEffect(() => {
    let live = true;
    fetchAllRestaurants(nonce > 0)
      .then((data) => live && setState({ key, data, error: null }))
      .catch((e) => live && setState({ key, data: null, error: errorMessage(e) }));
    return () => {
      live = false;
    };
  }, [key, nonce]);
  return { restaurants: state.data ?? [], loading: state.key !== key, error: state.key === key ? state.error : null, reload: () => setNonce((n) => n + 1) };
}

export function useRestaurant(slug: string | null | undefined) {
  const [nonce, setNonce] = useState(0);
  const [state, setState] = useState<Loaded<RestaurantDetail>>({ key: '', data: null, error: null });
  const key = `${slug ?? ''}|${nonce}`;
  useEffect(() => {
    if (!slug) return;
    let live = true;
    fetchRestaurant(slug, nonce > 0)
      .then((data) => live && setState({ key, data, error: null }))
      .catch((e) => live && setState({ key, data: null, error: errorMessage(e) }));
    return () => {
      live = false;
    };
  }, [slug, key, nonce]);
  const current = state.key === key;
  return {
    restaurant: slug && current ? state.data : null,
    loading: !!slug && !current,
    error: slug && current ? state.error : null,
    reload: () => setNonce((n) => n + 1),
  };
}

/** Readable fallback while the API is unreachable: "kanji-house" -> "Kanji House". */
export const nameFromSlug = (slug: string) =>
  slug
    .split('-')
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');

