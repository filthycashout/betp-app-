const BOARD_CACHE_MAX_AGE_MS = 5 * 60 * 1000;
const GENERIC_CACHE_MAX_AGE_MS = 60 * 1000;
const QUOTE_MAX_AGE_MS = 15 * 60 * 1000;
const FUTURE_SKEW_MS = 60 * 1000;

type CacheEnvelope<T> = {
  savedAt: number;
  data: T;
};

function storageKey(kind: string, date: string, scope?: string) {
  return `philthy-fast-cache:v1:${kind}:${date}:${scope || 'all'}`;
}

function isBoardKind(kind: string) {
  return kind.startsWith('best') || kind.startsWith('parlay') || kind === 'multiParlays';
}

export function pricedEvidenceStillFresh(value: unknown, now = Date.now()): boolean {
  if (Array.isArray(value)) return value.every(item => pricedEvidenceStillFresh(item, now));
  if (!value || typeof value !== 'object') return true;

  const row = value as Record<string, unknown>;
  const hasPricedEvidence =
    row.available !== false &&
    typeof row.best_available_book === 'string' &&
    row.best_available_book.length > 0 &&
    typeof row.best_available_price === 'number' &&
    Number.isFinite(row.best_available_price);

  if (hasPricedEvidence) {
    const quoteAt = Date.parse(String(row.as_of || ''));
    if (!Number.isFinite(quoteAt)) return false;
    const age = now - quoteAt;
    if (age < -FUTURE_SKEW_MS || age > QUOTE_MAX_AGE_MS) return false;

    if (row.event_time) {
      const eventTime = Date.parse(String(row.event_time));
      if (!Number.isFinite(eventTime) || eventTime <= now) return false;
    }
  }

  return Object.values(row).every(item => pricedEvidenceStillFresh(item, now));
}

export function readFastCache<T>(kind: string, date: string, scope?: string): T | null {
  if (typeof window === 'undefined' || !date) return null;
  try {
    const raw = window.localStorage.getItem(storageKey(kind, date, scope));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CacheEnvelope<T>;
    if (!parsed || typeof parsed.savedAt !== 'number') return null;
    const maxAge = isBoardKind(kind) ? BOARD_CACHE_MAX_AGE_MS : GENERIC_CACHE_MAX_AGE_MS;
    if (Date.now() - parsed.savedAt > maxAge) return null;
    if (isBoardKind(kind) && !pricedEvidenceStillFresh(parsed.data)) return null;
    return parsed.data;
  } catch {
    return null;
  }
}

export function writeFastCache<T>(kind: string, date: string, data: T, scope?: string) {
  if (typeof window === 'undefined' || !date) return;
  try {
    const envelope: CacheEnvelope<T> = { savedAt: Date.now(), data };
    window.localStorage.setItem(storageKey(kind, date, scope), JSON.stringify(envelope));
  } catch {
    // Cache failure must never block live data.
  }
}
