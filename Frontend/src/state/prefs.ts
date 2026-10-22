import { useSyncExternalStore } from "react";

/** How this browser likes the app laid out. Kept in localStorage; the app works without it. */
export interface Prefs {
  /** The chat folded into a narrow rail, leaving the map more room */
  chatCollapsed: boolean;
  /** Developer view: the tool trace, raw tool names and timings */
  developerView: boolean;
  /** The guide was shown once, so it doesn't open by itself again */
  guideSeen: boolean;
}

const KEY = "waypoint.prefs";
const DEFAULTS: Prefs = { chatCollapsed: false, developerView: false, guideSeen: false };

function load(): Prefs {
  let saved: Partial<Prefs> = {};
  try {
    saved = JSON.parse(localStorage.getItem(KEY) ?? "{}");
  } catch {
    // no storage (private window) or a bad value: defaults
  }
  const prefs = { ...DEFAULTS, ...saved };
  // ?trace in the address turns the developer view on (and it stays on)
  if (typeof location !== "undefined" && new URLSearchParams(location.search).has("trace")) prefs.developerView = true;
  return prefs;
}

let current = load();
const listeners = new Set<() => void>();

export function setPrefs(patch: Partial<Prefs>): void {
  current = { ...current, ...patch };
  try {
    localStorage.setItem(KEY, JSON.stringify(current));
  } catch {
    // not kept past this page, which is fine
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The preferences, re-rendering on change wherever they're used. */
export function usePrefs(): Prefs {
  return useSyncExternalStore(subscribe, () => current);
}
