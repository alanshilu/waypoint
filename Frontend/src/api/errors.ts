import type { CacheStatus } from "../types";

/** A backend call that failed: the HTTP status (null when unreachable) and the agent endpoints' error code. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
    /** Machine-readable code from the agent endpoints' {"error": {"code", "message"}} */
    readonly code: string | null = null,
  ) {
    super(message);
  }
}

/**
 * Cache status of the most recent call. The backend does not report cache hits, so this is always null
 * in real mode; mock mode simulates it.
 */
export const callMeta: { cache: CacheStatus } = { cache: null };
