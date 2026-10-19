import { useSyncExternalStore } from "react";
import { getServerStatus, subscribeServerStatus } from "../serverStatus";

/** Shown while a sleeping backend boots (free hosting stops it when idle), instead of an error. */
export default function ServerWaking() {
  const status = useSyncExternalStore(subscribeServerStatus, getServerStatus);
  if (status !== "waking") return null;
  return (
    <p className="server-waking" role="status">
      Waking up the server, this can take about a minute&hellip;
    </p>
  );
}
