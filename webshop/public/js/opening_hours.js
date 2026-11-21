//// Neoffice — added file (store hours, no upstream equivalent).
// The public opening-hours block: a `.webshop-opening-hours[data-autoload]`
// container, in a webshop template, a Builder HTML block or the site footer, is
// filled from the server and refreshed every minute so "closes in 15 min" stays
// true. All wording comes from the server (website pages have no __() catalogue).
//
//// Reworked 2026-09-08: the 🕒 and 🔒 emojis are gone. They carried meaning, and
//// an emoji renders differently on every platform and reads as clip-art next to a
//// typeset page. The clock is an inline SVG and the state is a dot, both in
//// currentColor so they follow the theme. The block also learned a compact form
//// (`data-display="compact"`), which is what a footer column has room for: the
//// state, today's hours, and a link through to the full week.
//
//// Neoffice — 2026-11-21: the file no longer needs frappe. Frappe keeps a rendered
//// page in its cache with no expiry, and a page Builder renders loads no script of
//// this app: a shop that opens at 10:00 said « Opens today at 10:00 » on its home
//// page at 10:14, the state written on the server before the opening. The include
//// now prints this file inline (store_hours.opening_hours_js), so a block anywhere
//// asks the server for the live state; one drawn more than STALE_SECONDS ago hides
//// its state line and today's mark until that answer has come. The shop's bundle
//// still imports it (web.bundle.js): the first copy to run is kept, and each block
//// starts once (`data-started`).
(function () {
	const root = (window.webshop = window.webshop || {});
	if (root.opening_hours) return;

	root.opening_hours = {
		//// A 24px stroked clock. Inline rather than a font or an emoji: it inherits
		//// currentColor, needs no network round trip and cannot be swapped by a
		//// platform's own glyph.
		ICON:
			'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" ' +
			'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
			'<circle cx="12" cy="12" r="9"></circle><path d="M12 7v5l3 2"></path></svg>',

		//// Neoffice — a block drawn longer ago than this was served from the page cache (or the
		//// visitor's clock is off): its state is hidden until the live one has come.
		STALE_SECONDS: 90,

		//// Neoffice — fetch, not frappe's call helper: a page Builder renders has no frappe object. `_lang`
		//// asks for the answer in the language the page was drawn in (frappe.translate.get_language).
		load(container) {
			const lang = container.dataset.lang;
			const url =
				"/api/method/webshop.webshop.utils.store_hours.get_opening_hours" +
				(lang ? "?_lang=" + encodeURIComponent(lang) : "");
			return fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
				.then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
				.then((r) => this.render(container, r.message))
				.catch(() => undefined);
		},

		stale(container) {
			const drawn = Number(container.dataset.drawnAt);
			return drawn > 0 && Date.now() / 1000 - drawn > this.STALE_SECONDS;
		},

		//// Neoffice — what a cached page may have wrong: the state, the date, the day marked as
		//// today. Hidden without moving anything (visibility), until render() redraws the block.
		hide_stale(container) {
			container
				.querySelectorAll(".wsh-hours__status, .wsh-hours__date")
				.forEach((el) => (el.style.visibility = "hidden"));
			container.querySelectorAll(".wsh-hours__day.is-today").forEach((el) => el.classList.remove("is-today"));
		},

		start(container) {
			if (container.dataset.started) return;
			container.dataset.started = "1";
			if (this.stale(container)) this.hide_stale(container);
			this.load(container);
			setInterval(() => this.load(container), 60000);
		},

		render(container, data) {
			if (!data || !data.configured) {
				container.innerHTML = "";
				container.classList.remove("has-hours");
				return;
			}
			const e = this.escape;
			const compact = (container.dataset.display || "").toLowerCase() === "compact";

			//// In the compact form only today is listed: a footer column cannot hold a
			//// week, and the link right below leads to the one that can.
			const rows = compact ? data.week.filter((d) => d.is_today) : data.week;
			const days = rows
				.map(
					(d) =>
						//// Neoffice — see the block marker above: today's row keeps its "is-today" accent only outside compact mode (66e82a4d40 "le bloc se modernise, et la ligne du jour ne déborde plus")
						`<li class="wsh-hours__day${d.is_today && !compact ? " is-today" : ""}${d.closed ? " is-closed" : ""}">` +
						`<span class="wsh-hours__day-name">${e(d.label)}</span>` +
						`<span class="wsh-hours__day-hours">${e(d.text)}</span></li>`
				)
				.join("");

			//// A closure is worth naming on the full block; in a footer it would push the
			//// one useful line out of sight.
			const closures =
				!compact && data.closures && data.closures.length
					? `<ul class="wsh-hours__closures">${data.closures
							.map((c) => `<li>${e(c.text)}</li>`)
							.join("")}</ul>`
					: "";

			const more =
				compact && data.more_url
					? `<a class="wsh-hours__more" href="${e(data.more_url)}">${e(data.more_label || data.more_url)}</a>`
					: "";

			const head = compact
				? `<div class="wsh-hours__head"><h3 class="wsh-hours__title">${e(data.title)}</h3></div>`
				: `<div class="wsh-hours__head"><div class="wsh-hours__icon">${this.ICON}</div>` +
				  `<h3 class="wsh-hours__title">${e(data.title)}</h3>` +
				  `<div class="wsh-hours__date">${e(data.today_text)}</div></div>`;

			container.innerHTML =
				//// Neoffice — see the block marker above: added the "wsh-hours--compact" wrapper class for the footer-column form (66e82a4d40 "le bloc se modernise, et la ligne du jour ne déborde plus")
				`<div class="wsh-hours${compact ? " wsh-hours--compact" : ""}">` +
				head +
				`<div class="wsh-hours__status ${data.is_open ? "is-open" : "is-closed"}">` +
				//// Neoffice — see the block marker above: replaced the 🔒 emoji with a themed dot span (66e82a4d40 "le bloc se modernise, et la ligne du jour ne déborde plus")
				`<strong><span class="wsh-hours__dot"></span>${e(data.headline)}</strong>` +
				(data.detail ? `<span>${e(data.detail)}</span>` : "") +
				`</div>` +
				`<ul class="wsh-hours__list">${days}</ul>` +
				closures +
				//// Neoffice — see the block marker above: note hidden and the "more" link shown only in compact mode (66e82a4d40 "le bloc se modernise, et la ligne du jour ne déborde plus")
				(data.note && !compact ? `<p class="wsh-hours__note">${e(data.note)}</p>` : "") +
				more +
				`</div>`;
			container.classList.add("has-hours");
		},

		escape(text) {
			return String(text == null ? "" : text).replace(
				/[&<>"']/g,
				(c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
			);
		},
	};

	//// Neoffice — frappe's ready hook replaced: the blocks already in the page start now (the include
	//// prints this script right after its block, so a stale state is hidden before it is seen),
	//// the others once the page is read; a tab that comes back to the front asks again.
	const start_all = () =>
		document
			.querySelectorAll(".webshop-opening-hours[data-autoload]")
			.forEach((container) => root.opening_hours.start(container));
	start_all();
	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start_all);
	document.addEventListener("visibilitychange", () => {
		if (document.hidden) return;
		document
			.querySelectorAll(".webshop-opening-hours[data-started]")
			.forEach((container) => root.opening_hours.load(container));
	});
})();
