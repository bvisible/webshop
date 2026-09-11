//// Neoffice — added file (no upstream equivalent).
//
// Visual regression harness: full-page captures of the shop, desktop and mobile,
// plus a structural summary of each page. Run it before a change to take a
// baseline, again after, then `compare.py` says what moved.
//
//   WEBSHOP_E2E_URL=https://shop.example WEBSHOP_SID=<sid> \
//     node tests/e2e/visual/capture.mjs baseline
//
// `WEBSHOP_SID` is a session cookie for a signed-in customer (mint one with
// `bench --site <site> browse --user <email>`); the pages flagged `auth` in
// pages.json are skipped without it. Captures land in visual/shots/<label>/,
// which is not versioned.
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const label = process.argv[2];
if (!label) {
	console.error("usage: node capture.mjs <label>");
	process.exit(2);
}
const base = (process.env.WEBSHOP_E2E_URL || "").replace(/\/$/, "");
if (!base) {
	console.error("WEBSHOP_E2E_URL is not set");
	process.exit(2);
}
const sid = process.env.WEBSHOP_SID || "";
const only = (process.env.WEBSHOP_ONLY || "").split(",").filter(Boolean);
const config = JSON.parse(fs.readFileSync(path.join(here, "pages.json"), "utf8"));
const out = path.join(here, "shots", label);
fs.mkdirSync(out, { recursive: true });

const host = new URL(base).hostname;
const browser = await chromium.launch({ headless: true });
const summary = {};

for (const page of config.pages) {
	if (only.length && !only.includes(page.name)) continue;
	if (page.auth && !sid) {
		summary[page.name] = { skipped: "no WEBSHOP_SID" };
		continue;
	}
	const viewports = page.mobile ? ["desktop", "mobile"] : ["desktop"];
	for (const vp of viewports) {
		const key = `${page.name}_${vp}`;
		const context = await browser.newContext({ viewport: config.viewports[vp], locale: "fr-CH" });
		if (page.auth) {
			await context.addCookies([{ name: "sid", value: sid, domain: host, path: "/" }]);
		}
		const tab = await context.newPage();
		tab.setDefaultTimeout(20000);
		const budget = new Promise((_, reject) => setTimeout(() => reject(new Error("page budget exceeded (90 s)")), 90000));
		process.stdout.write(`${key} … `);
		try {
			const response = await Promise.race([budget, tab.goto(base + page.path, { waitUntil: "domcontentloaded", timeout: 45000 })]);
			await tab.waitForTimeout(2500);
			// freeze what moves on its own: a sticky header sliding in, a pulsing bubble, a fading
			// button — captured mid-transition they show as differences that mean nothing
			await tab.addStyleTag({ content: "*, *::before, *::after { transition: none !important; animation: none !important; caret-color: transparent !important; }" }).catch(() => {});
			await tab.evaluate(() => document.fonts && document.fonts.ready).catch(() => {});
			// wake lazy images, then settle back at the top so the capture is stable
			for (let y = 0; y < 8000; y += 700) {
				await tab.mouse.wheel(0, 700);
				await tab.waitForTimeout(80);
			}
			await tab.evaluate(() => window.scrollTo(0, 0));
			await tab.waitForTimeout(1500);
			await tab.screenshot({ path: path.join(out, `${key}.png`), fullPage: true });
			summary[key] = {
				status: response ? response.status() : null,
				...(await tab.evaluate(() => {
					const text = (el) => (el?.textContent || "").replace(/\s+/g, " ").trim();
					const visible = (el) => {
						const r = el.getBoundingClientRect();
						return r.width > 0 && r.height > 0;
					};
					return {
						title: document.title.slice(0, 80),
						h1: text(document.querySelector("h1")).slice(0, 80),
						height: document.documentElement.scrollHeight,
						headings: [...document.querySelectorAll("h2,h3")].filter(visible).slice(0, 12).map((h) => text(h).slice(0, 40)),
						inline_styles: document.querySelectorAll("body style").length,
						errors: [...document.querySelectorAll(".alert-danger,.msgprint")].filter(visible).map(text).slice(0, 3),
					};
				})),
			};
			process.stdout.write("ok\n");
		} catch (error) {
			summary[key] = { error: String(error).slice(0, 160) };
			process.stdout.write("FAILED " + String(error).slice(0, 80) + "\n");
		}
		await context.close().catch(() => {});
	}
}
await browser.close();
fs.writeFileSync(path.join(out, "summary.json"), JSON.stringify(summary, null, 1));
const bad = Object.entries(summary).filter(([, v]) => v.error || (v.status && v.status >= 400));
console.log(`captured ${Object.keys(summary).length} pages into ${out}` + (bad.length ? `\nproblems: ${bad.map(([k, v]) => k + " " + (v.error || v.status)).join(", ")}` : ""));
