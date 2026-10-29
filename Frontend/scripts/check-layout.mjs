/**
 * Phone and tablet check, in a real browser (Playwright's Chromium), against the app in mock mode.
 *
 *   npm run dev                                     # mock mode (the default)
 *   node scripts/check-layout.mjs [base] [outDir]   # default http://localhost:5173, ../docs/screenshots
 *
 * Phone (390x844): the Chat / Map tabs. Tablet (768x1024): one stacked column. On each it plans the mock San
 * Francisco to Los Angeles trip by tapping the city picker, asks for places to stay and eat, and checks:
 * - no horizontal overflow, nothing cut off at the sides
 * - the tab bar switches views; a new trip or result moves the phone to the map, with "Back to chat"
 * - the map is visible after a trip loads, with the route cards, elevation chart and share/export buttons
 * - visible controls are at least 44x44 px (map states are exempt: drawn to scale, the chat is the alternative)
 * - colour contrast of the text (WCAG AA), and a visible focus ring on the first Tab stops
 * Screenshots go to outDir as mobile-<device>-<step>.png. Exits 1 when anything fails.
 */
import { mkdirSync } from "node:fs";
import { chromium } from "playwright";

const BASE = process.argv[2] ?? "http://localhost:5173";
const OUT = process.argv[3] ?? "../docs/screenshots";
const DEVICES = [
  { name: "phone", width: 390, height: 844, tabs: true },
  { name: "tablet", width: 768, height: 1024, tabs: false },
];
const MIN_TARGET = 44;
mkdirSync(OUT, { recursive: true });

const problems = [];
const fail = (where, text) => problems.push(`${where}: ${text}`);

/** Runs in the page: overflow, small targets, contrast. */
function audit() {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none" && r.bottom > 0 && r.right > 0 &&
      r.top < innerHeight && r.left < innerWidth;
  };
  const label = (el) => (el.getAttribute("aria-label") || el.textContent || el.getAttribute("placeholder") || el.tagName).trim().replace(/\s+/g, " ").slice(0, 40);

  const small = [];
  for (const el of document.querySelectorAll("button, a[href], input, select, textarea, [role=button], [role=tab], summary")) {
    if (!visible(el) || el.closest("[aria-hidden=true]") || el.closest(".map-area svg, .route-map-canvas svg")) continue;
    if (el.tagName === "A" && getComputedStyle(el).display === "inline" && el.closest("p, li")) continue;
    if (el.type === "checkbox") continue; // its label is the target
    const r = el.getBoundingClientRect();
    // 44 = MIN_TARGET (this runs in the page, which can't see the script's constants)
    if (r.width < 44 - 0.5 || r.height < 44 - 0.5) small.push(`${label(el)} ${Math.round(r.width)}x${Math.round(r.height)}`);
  }

  const parse = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const [r, g, b, a = 1] = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    return { r, g, b, a };
  };
  const lum = ({ r, g, b }) => {
    const f = (v) => ((v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const blend = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
  const background = (el) => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const c = parse(getComputedStyle(e).backgroundColor);
      if (c && c.a > 0) {
        layers.push(c);
        if (c.a >= 1) break;
      }
    }
    return layers.reverse().reduce((acc, c) => blend(c, acc), { r: 255, g: 255, b: 255, a: 1 });
  };
  const lowContrast = [];
  const seen = new Set();
  for (const el of document.querySelectorAll("p, li, h1, h2, h3, label, button, a, span, td, th, dd, dt, q, strong")) {
    if (!visible(el) || el.closest("svg") || el.closest("button:disabled")) continue;
    if (![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim().length > 1)) continue;
    const s = getComputedStyle(el);
    const fg = parse(s.color);
    if (!fg) continue;
    const bg = background(el);
    const L1 = lum(blend(fg, bg));
    const L2 = lum(bg);
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const size = parseFloat(s.fontSize);
    const need = size >= 24 || (size >= 18.66 && Number(s.fontWeight) >= 700) ? 3 : 4.5;
    const key = `${s.color}|${label(el)}`;
    if (ratio < need && !seen.has(key)) {
      seen.add(key);
      lowContrast.push(`"${label(el)}" ${ratio.toFixed(2)}:1 (needs ${need})`);
    }
  }

  const doc = document.scrollingElement;
  const overflow = doc.scrollWidth > innerWidth + 1 ? `page is ${doc.scrollWidth}px wide in a ${innerWidth}px window` : null;
  const clipped = [];
  for (const el of document.querySelectorAll(".chat, .mobile-bar, .tab-bar, .map-header, .route-comparison, .elevation, .places-panel, .directions-panel, .shared-panel, .route-map-canvas")) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.right > innerWidth + 1 || r.left < -1) clipped.push(`${el.className.split(" ")[0]} spans ${Math.round(r.left)}..${Math.round(r.right)}`);
  }
  return { small, lowContrast, overflow, clipped };
}

async function check(page, where) {
  const a = await page.evaluate(audit);
  if (a.overflow) fail(where, a.overflow);
  for (const c of a.clipped) fail(where, `cut off: ${c}`);
  if (a.small.length) fail(where, `targets under ${MIN_TARGET}px: ${a.small.join("; ")}`);
  if (a.lowContrast.length) fail(where, `low contrast: ${a.lowContrast.join("; ")}`);
}

async function mapVisible(page, where) {
  const box = await page.evaluate(() => {
    const el = document.querySelector(".route-map-canvas");
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const svg = el.querySelector("svg");
    return { top: r.top, height: r.height, width: r.width, svg: Boolean(svg), inView: r.top < innerHeight && r.bottom > 0 };
  });
  if (!box || !box.svg || !box.inView || box.height < 300) fail(where, `the map isn't visible (${JSON.stringify(box)})`);
}

async function focusRings(page, where) {
  await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur());
  let invisible = 0;
  let stops = 0;
  for (let i = 0; i < 15; i++) {
    await page.keyboard.press("Tab");
    const ring = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return null;
      const s = getComputedStyle(el);
      return (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== "none" ||
        (el instanceof SVGElement && s.stroke !== "none" && parseFloat(s.strokeWidth) >= 2);
    });
    if (ring === null) break;
    stops++;
    if (!ring) invisible++;
  }
  if (invisible) fail(where, `${invisible} of ${stops} focus stops show no focus ring`);
}

const tab = (page, name) => page.getByRole("tab", { name });
const shot = (page, device, step) => page.screenshot({ path: `${OUT}/mobile-${device}-${step}.png` });
/** Scrolls the map view (the phone's scrolling panel, or the page) to an element. */
const scrollTo = (page, selector) => page.locator(selector).first().scrollIntoViewIfNeeded().catch(() => undefined);

/** Taps a state on the map and a city in its list. */
async function pickCity(page, where, state, city) {
  const shape = page.getByRole("button", { name: `${state}: pick a city` });
  await shape.first().tap();
  const button = page.locator(".city-popover:not(.preview) button", { hasText: city });
  try {
    await button.first().waitFor({ timeout: 3000 });
  } catch {
    fail(where, `tapping ${state} opened no city list with ${city}`);
    return false;
  }
  const box = await page.locator(".city-popover:not(.preview)").boundingBox();
  if (box && (box.x < 0 || box.x + box.width > page.viewportSize().width)) fail(where, "the city list is cut off");
  await button.first().tap();
  return true;
}

const browser = await chromium.launch();
for (const device of DEVICES) {
  const where = `${device.name} ${device.width}x${device.height}`;
  const context = await browser.newContext({ viewport: { width: device.width, height: device.height }, deviceScaleFactor: 2, hasTouch: true, isMobile: device.name === "phone" });
  const page = await context.newPage();
  page.on("pageerror", (e) => fail(where, `page error: ${e.message}`));
  await page.addInitScript(() => localStorage.setItem("waypoint.prefs", JSON.stringify({ guideSeen: true })));
  await page.goto(BASE);
  await page.waitForTimeout(1200);
  await shot(page, device.name, "01-start");
  await check(page, `${where} start`);
  await focusRings(page, `${where} start`);

  if (device.tabs) {
    // the tabs: one view at a time
    if (!(await tab(page, "Chat").isVisible())) fail(where, "no tab bar");
    if (!(await page.getByLabel("Message the agent").isVisible())) fail(where, "the chat isn't shown first");
    await tab(page, "Map").tap();
    await page.waitForTimeout(500);
    if (await page.getByLabel("Message the agent").isVisible()) fail(where, "the chat still shows on the Map tab");
    await mapVisible(page, `${where} map tab`);
    await shot(page, device.name, "02-map-tab");
    // the 16 px message box (iOS zooms in on anything smaller)
    const size = await page.evaluate(() => parseFloat(getComputedStyle(document.querySelector(".chat-form input")).fontSize));
    if (size < 16) fail(where, `the message box text is ${size}px`);
  }

  // the city picker, by tap
  await scrollTo(page, ".route-map-canvas");
  if (await pickCity(page, where, "California", "San Francisco")) {
    await page.waitForTimeout(300);
    await shot(page, device.name, "03-city-picker");
    await pickCity(page, where, "California", "Los Angeles");
  }
  try {
    await page.waitForSelector(".route-card", { state: "attached", timeout: 20000 });
  } catch {
    fail(where, "no trip after picking two cities");
  }
  await page.waitForTimeout(2500);
  if (device.tabs && !(await tab(page, "Map").getAttribute("aria-selected")).includes("true")) fail(where, "not on the Map tab after the trip loaded");
  await mapVisible(page, `${where} trip`);
  await shot(page, device.name, "04-trip-map");
  await check(page, `${where} trip`);
  for (const [name, selector] of [["Google Maps", ".trip-actions a"], ["GPX", ".trip-actions button"]]) {
    if (!(await page.locator(selector).first().isVisible())) fail(`${where} trip`, `${name} not on screen`);
  }

  // the route cards and the elevation chart, a scroll away
  await scrollTo(page, ".route-comparison");
  await page.waitForTimeout(300);
  await shot(page, device.name, "05-route-cards");
  await check(page, `${where} cards`);
  const cards = page.locator(".route-card-head");
  if ((await cards.count()) < 2) fail(where, "route cards missing");
  else await cards.nth(1).tap({ timeout: 3000 }).catch((e) => fail(where, `can't tap the second route card: ${e.message.split("\n")[0]}`));
  await scrollTo(page, ".elevation");
  if (!(await page.locator(".elevation").isVisible())) fail(where, "no elevation chart");

  // ask for places from the chat: the phone switches to the map by itself, with a way back
  if (device.tabs) await tab(page, "Chat").tap();
  const chip = page.getByRole("button", { name: "Where to stay and eat" });
  await scrollTo(page, ".chips");
  await chip.tap();
  try {
    await page.waitForSelector(".places-panel", { state: "attached", timeout: 20000 });
  } catch {
    fail(where, "no places list");
  }
  await page.waitForTimeout(1500);
  if (device.tabs) {
    if (!(await tab(page, "Map").getAttribute("aria-selected")).includes("true")) fail(where, "didn't switch to the map when places arrived");
    if (!(await page.getByRole("button", { name: /Back to chat/ }).isVisible())) fail(where, 'no "Back to chat"');
    await mapVisible(page, `${where} switched to the map`);
    await shot(page, device.name, "06-switched-to-map");
  }
  await scrollTo(page, ".places-panel");
  await page.waitForTimeout(300);
  await shot(page, device.name, "07-places");
  await check(page, `${where} places`);
  // the list folds away behind its heading
  const toggle = page.locator(".places-panel .list-toggle");
  if (await toggle.count()) {
    await toggle.tap();
    if (await page.locator(".places-scroll").isVisible()) fail(where, "the places list didn't fold away");
    await toggle.tap();
  } else fail(where, "the places list can't fold away");

  if (device.tabs) {
    await page.getByRole("button", { name: /Back to chat/ }).tap();
    if (!(await page.getByLabel("Message the agent").isVisible())) fail(where, '"Back to chat" didn\'t show the chat');
    // the menu: "Use your key" (live mode only), the developer view and the trace
    await page.getByRole("button", { name: "Menu" }).tap();
    await page.waitForTimeout(300);
    if (!(await page.locator(".mobile-menu").getByLabel(/Developer view/).isVisible())) fail(where, "no developer view in the menu");
    await page.locator(".mobile-menu").getByLabel(/Developer view/).check();
    await page.waitForTimeout(300);
    if (!(await page.locator(".mobile-menu .trace").isVisible())) fail(where, "no trace in the menu");
    await shot(page, device.name, "08-menu");
    await check(page, `${where} menu`);
  }
  await context.close();
}
await browser.close();

if (problems.length) {
  console.log(`${problems.length} problem(s):`);
  for (const p of problems) console.log(`- ${p}`);
  process.exit(1);
}
console.log("no problems found");
