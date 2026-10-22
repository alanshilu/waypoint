import { useEffect, useRef } from "react";
import { capabilities } from "../api";
import { setPrefs, usePrefs } from "../state/prefs";

interface Props {
  open: boolean;
  onClose: () => void;
}

/** How to use Waypoint: a dialog opened from the ? button, and once on a first visit. */
export default function Guide({ open, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const { developerView } = usePrefs();

  // the native dialog keeps focus inside, closes on Escape and gives focus back to the button that opened it
  useEffect(() => {
    const el = dialog.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={dialog}
      className="guide"
      aria-labelledby="guide-title"
      onClose={onClose}
      // a click on the backdrop (the dialog element itself, outside its content) closes it
      onClick={(event) => event.target === event.currentTarget && onClose()}
    >
      <div className="guide-body">
        <header className="guide-head">
          <h2 id="guide-title">How to use Waypoint</h2>
          <button type="button" className="guide-close" aria-label="Close the guide" onClick={onClose}>
            &times;
          </button>
        </header>

        {capabilities.replies === "mock" && (
          <p className="guide-note">This is the demo with sample data: only San Francisco to Los Angeles works.</p>
        )}

        <section>
          <h3>1. Plan a trip</h3>
          <p>
            Tell the agent where you're driving, in the chat: <q>San Francisco to Los Angeles</q>. Add what matters to
            you, like <q>leave tomorrow at 8am</q>, <q>take the backroads</q> or <q>at most 5 hours of driving a day</q>.
            No trip yet? Click a state on the map and pick a start city, then an end city.
          </p>
        </section>

        <section>
          <h3>2. Compare the routes</h3>
          <p>
            Each trip gets a <strong>fastest</strong> and a <strong>backroads</strong> route. The cards at the top right
            compare drive time, distance, climbing and a scenic score, and say which highways each takes. Click a card,
            or a route on the map, to pick it.
          </p>
        </section>

        <section>
          <h3>3. Explore the map</h3>
          <ul>
            <li>Scroll or pinch to zoom, drag to move, or use the + and &minus; buttons; the corner button resets.</li>
            <li>Hover along a route: a car drives along it, and the elevation chart below follows.</li>
            <li>Hover a highway or a shield for its name. <strong>Full USA</strong> and <strong>Fit route</strong> reframe the map.</li>
          </ul>
        </section>

        <section>
          <h3>4. Directions</h3>
          <p>
            <strong>Directions</strong> lists every turn of the selected route. Pick a step, or use Start and Next, and
            the map zooms to that turn.
          </p>
        </section>

        <section>
          <h3>5. Stops, places to stay and eat, weather</h3>
          <p>
            Ask <q>Where should I stop overnight?</q> to split the drive into days, then <q>Where can we stay and
            eat?</q>. Places to stay range from campgrounds to motels and hotels; ask for <q>a motel</q> or <q>somewhere
            to camp</q> if you prefer one. Forecasts are for the day you'll be there.
          </p>
        </section>

        <section>
          <h3>Good to know</h3>
          <ul>
            <li>Place searches use OpenStreetMap's free services and can take a minute; the chat says what it's doing.</li>
            <li>The agent only states facts its tools returned, and says so when something couldn't be found.</li>
            <li>The <strong>&laquo;</strong> button folds the chat away for a bigger map.</li>
          </ul>
        </section>

        <footer className="guide-foot">
          <label>
            <input type="checkbox" checked={developerView} onChange={(event) => setPrefs({ developerView: event.target.checked })} />
            Developer view: show the tool trace, tool names and timings
          </label>
          <button type="button" className="guide-done" onClick={onClose}>
            Got it
          </button>
        </footer>
      </div>
    </dialog>
  );
}
