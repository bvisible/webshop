//// Neoffice — added file (store hours, no upstream equivalent).
// The public opening-hours block: a `.webshop-opening-hours[data-autoload]`
// container, in a webshop template or in a Builder HTML block, is filled from
// the server and refreshed every minute so "closes in 15 min" stays true.
// All wording comes from the server (website pages have no __() catalogue).
frappe.provide("webshop.opening_hours");

webshop.opening_hours = {
	load(container) {
		frappe.call({
			method: "webshop.webshop.utils.store_hours.get_opening_hours",
			type: "GET",
			callback: (r) => this.render(container, r.message),
		});
	},

	start(container) {
		if (container.dataset.started) return;
		container.dataset.started = "1";
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
		const days = data.week
			.map(
				(d) =>
					`<li class="wsh-hours__day${d.is_today ? " is-today" : ""}${d.closed ? " is-closed" : ""}">` +
					`<span class="wsh-hours__day-name">${e(d.label)}</span>` +
					`<span class="wsh-hours__day-hours">${e(d.text)}</span></li>`
			)
			.join("");
		const closures = data.closures.length
			? `<ul class="wsh-hours__closures">${data.closures
					.map((c) => `<li>${e(c.text)}</li>`)
					.join("")}</ul>`
			: "";
		container.innerHTML =
			`<div class="wsh-hours">` +
			`<div class="wsh-hours__head"><div class="wsh-hours__icon" aria-hidden="true">🕒</div>` +
			`<h3 class="wsh-hours__title">${e(data.title)}</h3>` +
			`<div class="wsh-hours__date">${e(data.today_text)}</div></div>` +
			`<div class="wsh-hours__status ${data.is_open ? "is-open" : "is-closed"}">` +
			`<strong>${data.is_open ? '<span class="wsh-hours__pulse"></span>' : "🔒 "}${e(data.headline)}</strong>` +
			(data.detail ? `<span>${e(data.detail)}</span>` : "") +
			`</div>` +
			`<ul class="wsh-hours__list">${days}</ul>` +
			closures +
			(data.note ? `<p class="wsh-hours__note">${e(data.note)}</p>` : "") +
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

frappe.ready(() => {
	document
		.querySelectorAll(".webshop-opening-hours[data-autoload]")
		.forEach((container) => webshop.opening_hours.start(container));
});
