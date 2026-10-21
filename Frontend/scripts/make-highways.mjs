// Builds public/data/highways.json: the lower 48's Interstates and US routes as TopoJSON, for the map's
// faded highway network. Source: Natural Earth 10m roads (public domain), generalised for national-scale
// maps. Run with `npm run highways`; it downloads about 9 MB and needs network access.
//
// Kept: mainline numbers only ("I-5", "US-101", "I-35W"); business, alternate and bypass spurs are dropped.
// US 66 was decommissioned in 1985, so its few leftover fragments are dropped too; the map draws the
// historic alignment from src/data/route66.ts instead.

import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SOURCE = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_roads.zip";
const MAPSHAPER = "mapshaper@0.6.102";
// Points closer than this to the simplified line are dropped: below a pixel at the "Fit route" zoom
// of a state-sized trip, and it keeps the file near 160 KB gzipped
const SIMPLIFY_INTERVAL_M = 1200;
const QUANTIZATION = 20000;
const LOWER_48 = "-125,24,-66,50";
const KEEP = [
  "sov_a3 == 'USA'",
  "(level == 'Interstate' || level == 'Federal')",
  "/^[0-9]+[NSEW]?$/.test(name)",
  "!(level == 'Federal' && name == '66')",
].join(" && ");

const out = resolve(dirname(fileURLToPath(import.meta.url)), "../public/data/highways.json");
const work = mkdtempSync(join(tmpdir(), "waypoint-highways-"));
try {
  const zip = join(work, "ne_10m_roads.zip");
  const response = await fetch(SOURCE);
  if (!response.ok) throw new Error(`${SOURCE}: HTTP ${response.status}`);
  writeFileSync(zip, Buffer.from(await response.arrayBuffer()));

  // npx is a .cmd on Windows, so it runs through cmd.exe, which splits on spaces: quote those arguments
  // (inside double quotes cmd leaves the expressions' &&, ^ and ! alone)
  const windows = process.platform === "win32";
  const arg = (a) => (windows && a.includes(" ") ? `"${a}"` : a);
  execFileSync(
    "npx",
    [
      "-y", MAPSHAPER,
      "-i", zip,
      "-target", "ne_10m_roads",
      "-clip", `bbox=${LOWER_48}`,
      "-filter", KEEP,
      "-each", "id = (level == 'Interstate' ? 'I-' : 'US-') + name",
      "-dissolve", "id",
      "-simplify", `interval=${SIMPLIFY_INTERVAL_M}`, "keep-shapes",
      "-rename-layers", "highways", "target=ne_10m_roads",
      "-o", out, "format=topojson", `quantization=${QUANTIZATION}`, "force",
    ].map(arg),
    { stdio: "inherit", shell: windows },
  );
  console.log(`Wrote ${out} (${Math.round(statSync(out).size / 1024)} KB)`);
} finally {
  rmSync(work, { recursive: true, force: true });
}
