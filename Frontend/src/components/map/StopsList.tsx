import type { PoiResult } from "../../types";

interface Props {
  stops: PoiResult;
  hovered: number | null;
  onHover: (id: number | null) => void;
}

/** The stops beside the map, numbered like their markers. */
export default function StopsList({ stops, hovered, onHover }: Props) {
  return (
    <section className="poi-list" aria-label="Stops">
      <h2>
        Stops near {stops.label} <span className="data">({stops.items.length})</span>
      </h2>
      <ol>
        {stops.items.map((poi) => (
          <li
            key={poi.id}
            className={hovered === poi.id ? "active" : undefined}
            onMouseEnter={() => onHover(poi.id)}
            onMouseLeave={() => onHover(null)}
          >
            <span className="poi-name">{poi.name}</span>
            <span className="poi-category">{poi.category.replace(/_/g, " ")}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
