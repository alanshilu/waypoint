/**
 * Bring your own Anthropic key. The key is kept in sessionStorage, so it is gone when the tab closes,
 * and is sent only in the X-Anthropic-Key header of agent messages. The backend uses it for that one
 * turn and never stores or logs it.
 */

const STORAGE_KEY = "waypoint.anthropic_key";
const KEY_PATTERN = /^sk-ant-[A-Za-z0-9_-]{20,250}$/;

export function isPlausibleKey(key: string): boolean {
  return KEY_PATTERN.test(key.trim());
}

export function getOwnKey(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setOwnKey(key: string | null): void {
  try {
    if (key) sessionStorage.setItem(STORAGE_KEY, key.trim());
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // storage unavailable (some private windows); the key can't be kept
  }
}

/** The last four characters, so the user can tell which key is in use without showing it. */
export function maskKey(key: string): string {
  return `sk-ant-…${key.slice(-4)}`;
}
