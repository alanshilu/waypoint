import { useState } from "react";
import type { ReactNode } from "react";
import { useStackedLayout } from "./map/layout";

/**
 * A list under the map in the stacked (phone and tablet) layout folds away behind its heading. On a desktop the
 * lists sit beside the map and always show, so open is always true there.
 */
export function useCollapsible(): { collapsible: boolean; open: boolean; toggle: () => void } {
  const collapsible = useStackedLayout();
  const [open, setOpen] = useState(true);
  return { collapsible, open: !collapsible || open, toggle: () => setOpen((v) => !v) };
}

/** The list's heading: a toggle when it can fold away, plain text otherwise. */
export function ListHeading({ collapsible, open, toggle, children }: { collapsible: boolean; open: boolean; toggle: () => void; children: ReactNode }) {
  if (!collapsible) return <h2>{children}</h2>;
  return (
    <h2>
      <button type="button" className="list-toggle" aria-expanded={open} onClick={toggle}>
        <span>{children}</span>
        <span className="list-toggle-mark" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
      </button>
    </h2>
  );
}
