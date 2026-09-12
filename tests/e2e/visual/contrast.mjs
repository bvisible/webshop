//// Neoffice — added file (no upstream equivalent).
//
// Contrast audit of the shop's pages, for the chrome they actually sit on.
//
// The shop draws with the chrome's tokens (webshop_tokens.scss): its colours are only
// known once a real site renders them, and a shop that reads perfectly on a light site
// can print its title dark on dark on a reseller's dark site — which is how it shipped
// on 2026-09-11 (neoffice-maintenance #369). This audit walks every visible text, every
// input and select, every button and every icon of the page's content and computes the
// WCAG contrast ratio of its ink against the ground it really sits on (alpha-composited
// through its ancestors). Anything under the threshold is reported with its selector
// path; the exit code says whether the page passed, so a deploy can be gated on it.
//
//   WEBSHOP_E2E_URL=https://shop.example [WEBSHOP_SID=<sid>] \
//     node tests/e2e/visual/contrast.mjs [/path ...]
//
// Without paths it audits the public pages of pages.json (and the `auth` ones when a
// session cookie is given). `WEBSHOP_CONTRAST_MIN` (default 3) is the ratio under which
// an element is a finding; `--json` prints the findings as JSON instead of a table.
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

/**
 * Audit the page currently loaded in `page`. Runs inside the browser: returns
 * {checked, findings: [{text, ratio, fg, bg, path}]}.
 */
export async function auditContrast(page, { minimum = 3, root = "main, .site-page-header" } = {}) {
	return page.evaluate(({ minimum, root }) => {
		const parse = (c) => {
			let m = c.match(/^rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)$/);
			if (m) return { r: +m[1], g: +m[2], b: +m[3], a: m[4] === undefined ? 1 : +m[4] };
			// Chrome serialises a colour-mix() result this way
			m = c.match(/^color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: \/ ([\d.]+))?\)$/);
			if (m) return { r: +m[1] * 255, g: +m[2] * 255, b: +m[3] * 255, a: m[4] === undefined ? 1 : +m[4] };
			if (c === "transparent") return { r: 0, g: 0, b: 0, a: 0 };
			return null;
		};
		const channel = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
		const luminance = (c) => 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b);
		const over = (top, under) => ({
			r: top.r * top.a + under.r * (1 - top.a),
			g: top.g * top.a + under.g * (1 - top.a),
			b: top.b * top.a + under.b * (1 - top.a),
			a: 1,
		});
		const ratio = (fg, bg) => { const l1 = luminance(fg), l2 = luminance(bg); return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05); };
		const hex = (c) => "#" + [c.r, c.g, c.b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");

		// the ground an element sits on: its own background composited over its ancestors'
		const groundOf = (el) => {
			const layers = [];
			let node = el;
			while (node && node !== document.documentElement) {
				const c = parse(getComputedStyle(node).backgroundColor);
				if (c && c.a > 0) layers.push(c);
				if (c && c.a >= 1) break;
				node = node.parentElement;
			}
			let ground = parse(getComputedStyle(document.body).backgroundColor);
			if (!ground || ground.a < 1) ground = over(ground || { r: 255, g: 255, b: 255, a: 0 }, { r: 255, g: 255, b: 255, a: 1 });
			for (const layer of layers.reverse()) ground = over(layer, ground);
			return ground;
		};
		const describe = (el) => {
			const parts = [];
			let node = el;
			for (let i = 0; i < 4 && node && node !== document.body; i++) {
				const cls = typeof node.className === "string" ? node.className.trim().split(/\s+/).filter(Boolean).slice(0, 3) : [];
				parts.unshift(node.tagName.toLowerCase() + (node.id ? "#" + node.id : "") + (cls.length ? "." + cls.join(".") : ""));
				node = node.parentElement;
			}
			return parts.join(" > ");
		};
		const visible = (el) => {
			const cs = getComputedStyle(el);
			if (cs.display === "none" || cs.visibility === "hidden" || +cs.opacity === 0) return false;
			if (el.closest("[hidden], [aria-hidden='true'], .d-none, template")) return false;
			const rect = el.getBoundingClientRect();
			return rect.width > 0 && rect.height > 0;
		};

		const roots = [...document.querySelectorAll(root)];
		const findings = [];
		let checked = 0;
		const seen = new Set();
		const check = (el, text, ink) => {
			if (seen.has(el) || !visible(el)) return;
			seen.add(el);
			const fg = parse(ink);
			if (!fg || fg.a === 0) return;
			const bg = groundOf(el);
			const r = ratio(fg.a < 1 ? over(fg, bg) : fg, bg);
			checked += 1;
			if (r < minimum) findings.push({ text: text.slice(0, 48), ratio: Math.round(r * 100) / 100, fg: hex(fg.a < 1 ? over(fg, bg) : fg), bg: hex(bg), path: describe(el) });
		};

		for (const scope of roots) {
			const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
			let node;
			while ((node = walker.nextNode())) {
				const text = node.textContent.replace(/\s+/g, " ").trim();
				if (!/[\p{L}\p{N}]/u.test(text)) continue;
				const el = node.parentElement;
				if (!el || ["SCRIPT", "STYLE", "NOSCRIPT", "OPTION"].includes(el.tagName)) continue;
				check(el, text, getComputedStyle(el).color);
			}
			// what is typed in a field must read too; the placeholder is a hint, not the value
			for (const el of scope.querySelectorAll("input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=range]), select, textarea")) {
				check(el, "<" + el.tagName.toLowerCase() + (el.id ? "#" + el.id : "") + ">", getComputedStyle(el).color);
			}
			// an icon is drawn in its stroke, or its fill when it has no stroke
			for (const el of scope.querySelectorAll("svg")) {
				if (el.closest("button, a, [role=button]") && !visible(el.closest("button, a, [role=button]"))) continue;
				const cs = getComputedStyle(el);
				const stroke = cs.stroke && cs.stroke !== "none" ? cs.stroke : null;
				const fill = cs.fill && cs.fill !== "none" ? cs.fill : null;
				const ink = stroke && stroke !== "rgb(0, 0, 0)" ? stroke : (fill || stroke || cs.color);
				const owner = el.closest("button, a, [role=button]") || el.parentElement;
				const label = "<svg" + (owner ? " in " + describe(owner).split(" > ").pop() : "") + ">";
				check(el, label, ink === "currentcolor" || ink === "currentColor" ? cs.color : ink);
			}
		}
		return { checked, findings };
	}, { minimum, root });
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
	const args = process.argv.slice(2);
	const asJson = args.includes("--json");
	const paths = args.filter((a) => a.startsWith("/"));
	const base = (process.env.WEBSHOP_E2E_URL || "").replace(/\/$/, "");
	if (!base) {
		console.error("WEBSHOP_E2E_URL is not set");
		process.exit(2);
	}
	const sid = process.env.WEBSHOP_SID || "";
	const minimum = Number(process.env.WEBSHOP_CONTRAST_MIN || 3);
	let targets = paths.map((p) => ({ name: p, path: p }));
	if (!targets.length) {
		const config = JSON.parse(fs.readFileSync(path.join(here, "pages.json"), "utf8"));
		targets = config.pages.filter((p) => !p.auth || sid).map((p) => ({ name: p.name, path: p.path, auth: p.auth }));
	}
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1400, height: 900 }, locale: "fr-CH" });
	if (sid) await context.addCookies([{ name: "sid", value: sid, domain: new URL(base).hostname, path: "/" }]);
	const tab = await context.newPage();
	const report = [];
	let failed = 0;
	for (const target of targets) {
		let status = 0;
		try {
			const response = await tab.goto(base + target.path, { waitUntil: "networkidle", timeout: 60000 });
			status = response ? response.status() : 0;
			await tab.waitForTimeout(1500);
		} catch (e) {
			report.push({ name: target.name, path: target.path, error: String(e.message).split("\n")[0] });
			failed += 1;
			continue;
		}
		if (status >= 400) {
			report.push({ name: target.name, path: target.path, status, error: "HTTP " + status });
			failed += 1;
			continue;
		}
		const result = await auditContrast(tab, { minimum });
		report.push({ name: target.name, path: target.path, status, url: tab.url(), ...result });
		if (result.findings.length) failed += 1;
	}
	await browser.close();
	if (asJson) {
		console.log(JSON.stringify(report, null, 1));
	} else {
		for (const r of report) {
			if (r.error) { console.log(`✗ ${r.name}  ${r.error}`); continue; }
			const verdict = r.findings.length ? "✗" : "✓";
			console.log(`${verdict} ${r.name}  ${r.checked} elements read, ${r.findings.length} under ${minimum}:1${r.url !== base + r.path ? "  (landed on " + r.url.replace(base, "") + ")" : ""}`);
			for (const f of r.findings) console.log(`    ${String(f.ratio).padEnd(5)} ${f.fg} on ${f.bg}  ${JSON.stringify(f.text)}  ${f.path}`);
		}
	}
	process.exit(failed ? 1 : 0);
}
