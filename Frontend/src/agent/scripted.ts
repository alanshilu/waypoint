import type { BackendApi, PlacePoint } from "../api/contract";
import { routeLabel } from "../format";
import { buildMileIndex, pointAtMile } from "../geo";
import type { AgentTurnResult, CacheStatus, StepView, Trip } from "../types";
import type { AgentRunner } from "./runner";
import { compare, describe, followUps, shortName } from "./text";

const NO_TRIP = "There is no trip yet. Tell me where you are driving from and to.";

/**
 * A scripted stand-in for the agent: reads the intent from the message and calls the same backend functions
 * the agent's tools call, in the order the agent's system prompt prescribes. With the mock backend, that's
 * the fixtures in src/fixtures. cacheStatus reports whether the last call was a (simulated) cache hit;
 * unknownPlaceHint says what this backend can find when a place isn't found.
 */
export function createScriptedAgent(
  backend: BackendApi,
  { cacheStatus = () => null, unknownPlaceHint = "" }: { cacheStatus?: () => CacheStatus; unknownPlaceHint?: string } = {},
): AgentRunner {
  return {
    async run(message, context, onSteps) {
      const steps: StepView[] = [];
      const emit = () => onSteps(steps.map((s) => ({ ...s })));

      async function step<T>(tool: string, call: () => Promise<T>): Promise<T> {
        const view: StepView = { tool, status: "running", ms: null, cache: null };
        steps.push(view);
        emit();
        const started = performance.now();
        try {
          const value = await call();
          view.status = "done";
          view.cache = cacheStatus();
          return value;
        } catch (error) {
          view.status = "error";
          view.error = error instanceof Error ? error.message : String(error);
          throw error;
        } finally {
          view.ms = Math.round(performance.now() - started);
          emit();
        }
      }

      const finish = (
        reply: string,
        extra: Partial<Pick<AgentTurnResult, "state_changed" | "trip" | "selectedRouteId" | "pois" | "places" | "chips">> = {},
      ): AgentTurnResult => ({
        reply,
        steps: steps.map((s) => ({ tool: s.tool, ms: s.ms ?? 0, cache: s.cache })),
        state_changed: extra.state_changed ?? [],
        source: "mock",
        trip: extra.trip,
        selectedRouteId: extra.selectedRouteId,
        pois: extra.pois,
        places: extra.places,
        chips: extra.chips ?? [],
      });

      const { trip, selectedRouteId } = context;
      const text = message.trim();
      const lower = text.toLowerCase();

      try {
        // 1. Route selection
        const wanted = /backroad|scenic/.test(lower) ? "backroads" : /fast|quick/.test(lower) ? "fastest" : null;
        const isSelection = wanted && (/select|choose|pick|go with|take|switch|use/.test(lower) || lower === wanted);
        if (isSelection) {
          const route = trip?.routes.find((r) => r.route_type === wanted);
          if (!trip || !route) return finish(NO_TRIP);
          if (route.id === selectedRouteId) {
            return finish(`${routeLabel(route.route_type)} (route ${route.id}) is already selected.`, {
              chips: followUps(trip, route.id),
            });
          }
          await step("select_route", () => backend.selectRoute(route.id));
          return finish(`${routeLabel(route.route_type)} selected: ${describe(route)}.`, {
            state_changed: ["selected_route"],
            selectedRouteId: route.id,
            chips: followUps(trip, route.id),
          });
        }

        // 2. New trip: "<origin> to <destination>"
        // An explicit "from X to Y" always plans; a bare "X to Y" only does when
        // the message is not a follow-up question about the current trip.
        const explicit = text.match(/\bfrom\s+(.+?)\s+to\s+(.+?)[.?!]*$/i);
        const isFollowUp = !!trip && /weather|forecast|rain|temperature|stop|poi|food|eat|fuel|gas|coffee|near/.test(lower);
        const match = explicit ?? (isFollowUp ? null : text.match(/^(?:plan\s+)?(.+?)\s+to\s+(.+?)[.?!]*$/i));
        if (match) {
          const [origin] = await step("geocode_location", () => backend.searchLocation(match[1]));
          const [destination] = await step("geocode_location", () => backend.searchLocation(match[2]));
          if (!origin || !destination) {
            const missing = !origin ? match[1] : match[2];
            return finish(`I could not find a location for "${missing}".${unknownPlaceHint ? ` ${unknownPlaceHint}` : ""}`);
          }
          const tripId = await step("create_trip", () =>
            backend.createTrip(origin, destination, `${shortName(origin)} to ${shortName(destination)}`),
          );
          const routes = await step("generate_routes", () => backend.generateRoutes(tripId));
          const newTrip: Trip = { id: tripId, origin, destination, selected_route_id: null, routes, weather: [] };

          // Weather is a nice-to-have: a failure here must not lose the routes.
          let weatherNote = "";
          try {
            const forecast = await step("get_weather_forecast", () => backend.getForecast(destination.lat, destination.lon));
            newTrip.weather = [{ ...destination, forecast }];
            const today = forecast[0];
            if (today) {
              weatherNote = ` ${shortName(destination)} forecast: ${today.condition.toLowerCase()}, ${Math.round(today.temp_max)}°/${Math.round(today.temp_min)}°F.`;
            }
          } catch {
            weatherNote = " The weather lookup failed, so no forecast is shown.";
          }

          return finish(compare(newTrip) + weatherNote + " Which route do you want?", {
            state_changed: ["trip"],
            trip: newTrip,
            chips: followUps(newTrip, null),
          });
        }

        // 3. Follow-ups on the current trip
        if (/weather|forecast|rain|temperature/.test(lower)) {
          if (!trip) return finish(NO_TRIP);
          const forecast = await step("get_weather_forecast", () =>
            backend.getForecast(trip.destination.lat, trip.destination.lon),
          );
          const days = forecast
            .slice(0, 3)
            .map((d) => `${d.date}: ${d.condition.toLowerCase()}, ${Math.round(d.temp_max)}°/${Math.round(d.temp_min)}°F, ${d.precip_probability}% rain`)
            .join("; ");
          const updated: Trip = { ...trip, weather: [{ ...trip.destination, forecast }] };
          return finish(days ? `${shortName(trip.destination)}: ${days}.` : "No forecast came back.", {
            state_changed: ["trip"],
            trip: updated,
            selectedRouteId: selectedRouteId ?? undefined,
            chips: followUps(trip, selectedRouteId),
          });
        }

        // Campsites and food: like the agent, around a night's stop (here: halfway along the route) and a
        // lunch point (a quarter of the way), with one pick per group
        if (/\bcamp|campsite|campground|\blunch\b|\bdinner\b/.test(lower)) {
          if (!trip) return finish(NO_TRIP);
          const route = trip.routes.find((r) => r.id === selectedRouteId) ?? trip.routes[0];
          const index = buildMileIndex(route.geometry, route.distance_miles);
          const at = (share: number) => pointAtMile(index, index.totalMiles * share) ?? route.geometry.coordinates[0];
          const [nightLon, nightLat] = at(0.5);
          const [lunchLon, lunchLat] = at(0.25);
          const points: PlacePoint[] = [
            { near: "night-1", label: `Night 1 · halfway along the ${route.route_type} route`, lat: nightLat, lon: nightLon, kinds: ["camping", "food"] },
            { near: "lunch-1", label: `Lunch, day 1 · a quarter of the way`, lat: lunchLat, lon: lunchLon, kinds: ["food"] },
          ];
          const found = await step("find_places", () => backend.findPlaces(points));
          const places = found.map((group) => ({
            ...group,
            places: group.places.map((place, i) => ({
              ...place,
              recommended: i === 0,
              reason: i === 0 ? `${place.distance_mi} mi from the stop, ${place.facts.slice(0, 2).join(", ")}` : null,
            })),
          }));
          const pick = (near: string, kind: string) =>
            places.find((g) => g.near === near && g.kind === kind)?.places[0]?.name ?? "nothing found";
          return finish(
            `For night 1, camp at ${pick("night-1", "camping")} and eat at ${pick("night-1", "food")}; ` +
              `for lunch, ${pick("lunch-1", "food")}. Every option is on the map and in the list.`,
            { state_changed: ["places"], places, chips: followUps(trip, selectedRouteId) },
          );
        }

        if (/stop|poi|food|eat|fuel|gas|coffee|near/.test(lower)) {
          if (!trip) return finish(NO_TRIP);
          // "along the route" searches around the midpoint of the selected route
          // (fastest if none is selected); anything else searches the destination.
          // The backend only searches around one point per call.
          let label = shortName(trip.destination);
          let center = { lat: trip.destination.lat, lon: trip.destination.lon };
          const route = trip.routes.find((r) => r.id === selectedRouteId) ?? trip.routes[0];
          if (route && /along|midpoint|halfway|half way|on the way|en route/.test(lower)) {
            const index = buildMileIndex(route.geometry, route.distance_miles);
            const mid = pointAtMile(index, index.totalMiles / 2);
            if (mid) {
              center = { lat: mid[1], lon: mid[0] };
              label = `the midpoint of the ${route.route_type} route`;
            }
          }
          const items = await step("search_pois", () => backend.searchPois(center.lat, center.lon));
          const list = items
            .slice(0, 5)
            .map((p) => `${p.name} (${p.category.replace(/_/g, " ")})`)
            .join(", ");
          const more = items.length > 5 ? ` and ${items.length - 5} more` : "";
          return finish(
            list
              ? `${items.length} stops near ${label}: ${list}${more}. They are numbered on the map.`
              : `No stops found near ${label}.`,
            {
              state_changed: ["pois"],
              pois: { label, center, items },
              chips: followUps(trip, selectedRouteId),
            },
          );
        }

        const selected = trip?.routes.find((r) => r.id === selectedRouteId);
        const status = selected
          ? ` Route ${selected.id} (${selected.route_type}) is currently selected.`
          : trip
            ? " No route is selected yet."
            : "";
        return finish(
          `I can plan a trip ("San Francisco to Los Angeles"), select a route, check the weather or find stops.${status}`,
          { chips: trip ? followUps(trip, selectedRouteId) : ["San Francisco to Los Angeles"] },
        );
      } catch (error) {
        const reason = error instanceof Error ? error.message : String(error);
        const failed = steps[steps.length - 1]?.tool ?? "request";
        return finish(`${failed} failed: ${reason}`, { chips: trip ? followUps(trip, selectedRouteId) : [] });
      }
    },
  };
}
