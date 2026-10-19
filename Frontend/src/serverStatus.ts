/**
 * Whether the backend may be asleep. Free hosting (Render) stops an idle backend after about 15 minutes;
 * the next request then waits, or fails with a proxy 502/503, while it boots for up to a minute.
 * api.ts reports what it sees here, and the app shows "Waking up the server" instead of an error.
 */

export type ServerStatus = "unknown" | "waking" | "awake";

// A free Render service sleeps after 15 minutes without traffic; assume it may have by 14
const IDLE_SLEEP_MS = 14 * 60_000;

let status: ServerStatus = "unknown";
let lastContact = 0;
const listeners = new Set<() => void>();

function set(next: ServerStatus) {
  if (next === status) return;
  status = next;
  listeners.forEach((listener) => listener());
}

export function getServerStatus(): ServerStatus {
  return status;
}

export function subscribeServerStatus(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** True until the server has answered, and again once it has been idle long enough to have gone to sleep. */
export function mayBeAsleep(): boolean {
  return status !== "awake" || Date.now() - lastContact > IDLE_SLEEP_MS;
}

export function markWaking(): void {
  set("waking");
}

export function markAwake(): void {
  lastContact = Date.now();
  set("awake");
}

/** The wait is over without an answer: drop the banner and let the caller's error show. */
export function markGaveUp(): void {
  set("unknown");
}
