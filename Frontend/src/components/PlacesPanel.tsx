import { useState } from "react";
import { placeGlyph } from "../placeGlyph";
import type { PlaceGroup, PlaceOption } from "../types";

interface Props {
  groups: PlaceGroup[];
  hovered: string | null;
  onHover: (id: string | null) => void;
}

// Alternatives shown under each pick before "+N more"
const ALTERNATIVES = 2;

const KIND_HEADING = { stay: "Stay", food: "Eat" } as const;
const KIND_NONE = { stay: "places to stay", food: "places to eat" } as const;

/** The agent's picks of where to stay and eat per stop, with the other options found, as a list beside the map. */
export default function PlacesPanel({ groups, hovered, onHover }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  // One section per stop, in the order the agent searched them
  const sections: { label: string; groups: PlaceGroup[] }[] = [];
  for (const group of groups) {
    const section = sections.find((s) => s.label === group.label);
    if (section) section.groups.push(group);
    else sections.push({ label: group.label, groups: [group] });
  }

  const row = (place: PlaceOption) => (
    <li
      key={place.id}
      className={[place.recommended ? "picked" : "", hovered === place.id ? "active" : ""].join(" ").trim() || undefined}
      onMouseEnter={() => onHover(place.id)}
      onMouseLeave={() => onHover(null)}
    >
      <span className={`place-glyph ${placeGlyph(place)}`} aria-hidden="true" />
      <span className="place-name">
        {place.recommended && <span className="sr-only">Recommended: </span>}
        {place.name}
        {place.recommended && place.reason && <span className="place-reason">{place.reason}</span>}
        {!place.recommended && place.facts.length > 0 && (
          <span className="place-facts">{place.facts.slice(0, 3).join(" · ")}</span>
        )}
      </span>
      <span className="place-distance">{place.distance_mi.toFixed(1)} mi</span>
    </li>
  );

  return (
    <section className="places-panel" aria-label="Where to stay and eat">
      <h2>Where to stay and eat</h2>
      <div className="places-scroll">
        {sections.map((section) => (
          <div key={section.label} className="places-section">
            <h3>{section.label}</h3>
            {section.groups.map((group) => {
              const key = `${group.near}:${group.kind}`;
              const picks = group.places.filter((p) => p.recommended);
              const others = group.places.filter((p) => !p.recommended);
              const open = expanded.has(key);
              const shown = open ? others : others.slice(0, ALTERNATIVES);
              return (
                <div key={key} className="places-group">
                  <h4>{KIND_HEADING[group.kind]}</h4>
                  {/* e.g. "Nothing within 3.1 mi, so searched out to 12.4 mi": it explains the distances below */}
                  {group.places.length > 0 && group.note && <p className="places-note">{group.note}</p>}
                  {group.places.length === 0 ? (
                    <p className="places-empty">
                      {group.note ?? `No ${KIND_NONE[group.kind]} found within ${group.radius_mi} mi.`}
                    </p>
                  ) : (
                    <ul>
                      {picks.map(row)}
                      {shown.map(row)}
                    </ul>
                  )}
                  {others.length > ALTERNATIVES && (
                    <button
                      type="button"
                      className="places-more"
                      aria-expanded={open}
                      onClick={() =>
                        setExpanded((current) => {
                          const next = new Set(current);
                          if (open) next.delete(key);
                          else next.add(key);
                          return next;
                        })
                      }
                    >
                      {open ? "Fewer" : `+${others.length - ALTERNATIVES} more`}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
      <p className="places-attribution">
        {groups.some((g) => g.source === "mock") ? "Mock data" : "Place data © OpenStreetMap contributors"}
      </p>
    </section>
  );
}
