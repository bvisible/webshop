//// Neoffice — added file (shop assistant, no upstream equivalent).
// The chat bubble. Everything it says comes from the server (`get_config`
// carries the labels: website pages have no __() catalogue), everything it
// knows about the visitor comes from the session behind the requests. The
// bubble only draws, sends and shows.
frappe.provide("webshop.assistant");

webshop.assistant = {
	config: null,
	busy: false,
	el: {},

	async init() {
		if (document.getElementById("wsh-assistant")) return;
		let config;
		try {
			config = await this.api("webshop.webshop.assistant.api.get_config", { page_route: this.route() }, "GET");
		} catch (e) {
			return;
		}
		if (!config || !config.enabled) return;
		this.config = config;
		this.build();
		this.renderHistory();
		if (sessionStorage.getItem("wsh-assistant-open") === "1") this.open(false);
	},

	route() {
		return location.pathname.replace(/^\//, "");
	},

	api(method, args, type) {
		return new Promise((resolve, reject) => {
			frappe.call({
				method,
				type: type || "POST",
				args: args || {},
				callback: (r) => resolve(r.message),
				error: (e) => reject(e),
			});
		});
	},

	build() {
		const c = this.config;
		const L = c.labels;
		const root = document.createElement("div");
		root.id = "wsh-assistant";
		root.className = "wsh-assistant" + (c.position === "Bottom left" ? " wsh-assistant--left" : "");
		if (c.color) root.style.setProperty("--wsh-assistant-color", c.color);
		root.innerHTML =
			`<button type="button" class="wsh-assistant__bubble" aria-label="${this.escape(L.open)}" aria-expanded="false">` +
			`<span class="wsh-assistant__bubble-icon" aria-hidden="true">${this.icon()}</span></button>` +
			`<section class="wsh-assistant__panel" role="dialog" aria-label="${this.escape(c.name)}" hidden>` +
			`<header class="wsh-assistant__head"><span class="wsh-assistant__avatar" aria-hidden="true">${this.icon()}</span>` +
			`<span class="wsh-assistant__name">${this.escape(c.name)}</span>` +
			`<button type="button" class="wsh-assistant__reset" title="${this.escape(L.new_conversation)}">↺</button>` +
			`<button type="button" class="wsh-assistant__close" aria-label="${this.escape(L.close)}">×</button></header>` +
			`<div class="wsh-assistant__messages" aria-live="polite"></div>` +
			`<div class="wsh-assistant__suggestions"></div>` +
			`<form class="wsh-assistant__form"><input class="wsh-assistant__input" type="text" maxlength="1000" autocomplete="off" placeholder="${this.escape(L.placeholder)}">` +
			`<button type="submit" class="wsh-assistant__send">${this.escape(L.send)}</button></form>` +
			`<div class="wsh-assistant__foot"><button type="button" class="wsh-assistant__team">${this.escape(L.talk_to_team)}</button></div>` +
			`</section>`;
		document.body.appendChild(root);
		this.el = {
			root,
			bubble: root.querySelector(".wsh-assistant__bubble"),
			panel: root.querySelector(".wsh-assistant__panel"),
			messages: root.querySelector(".wsh-assistant__messages"),
			suggestions: root.querySelector(".wsh-assistant__suggestions"),
			form: root.querySelector(".wsh-assistant__form"),
			input: root.querySelector(".wsh-assistant__input"),
			team: root.querySelector(".wsh-assistant__team"),
			reset: root.querySelector(".wsh-assistant__reset"),
			close: root.querySelector(".wsh-assistant__close"),
		};
		this.el.bubble.addEventListener("click", () => (this.el.panel.hidden ? this.open() : this.closePanel()));
		this.el.close.addEventListener("click", () => this.closePanel());
		this.el.form.addEventListener("submit", (e) => {
			e.preventDefault();
			this.send(this.el.input.value);
		});
		this.el.team.addEventListener("click", () => this.send(L.suggestions[L.suggestions.length - 1]));
		this.el.reset.addEventListener("click", () => this.reset());
	},

	icon() {
		return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-8 8H8l-5 3 1.5-4.5A8 8 0 1 1 21 12z"/></svg>';
	},

	open(remember = true) {
		this.el.panel.hidden = false;
		this.el.bubble.setAttribute("aria-expanded", "true");
		this.el.root.classList.add("is-open");
		if (remember) sessionStorage.setItem("wsh-assistant-open", "1");
		this.scroll();
		setTimeout(() => this.el.input.focus(), 50);
	},

	closePanel() {
		this.el.panel.hidden = true;
		this.el.bubble.setAttribute("aria-expanded", "false");
		this.el.root.classList.remove("is-open");
		sessionStorage.setItem("wsh-assistant-open", "0");
	},

	renderHistory() {
		const c = this.config;
		this.el.messages.innerHTML = "";
		this.addMessage("assistant", c.greeting);
		if (c.history && c.history.length) {
			this.addNote(c.labels.resume);
			c.history.forEach((m) => this.addMessage(m.role, m.content));
			this.el.suggestions.innerHTML = "";
		} else {
			this.renderSuggestions();
		}
	},

	renderSuggestions() {
		const L = this.config.labels;
		this.el.suggestions.innerHTML = L.suggestions
			.map((s) => `<button type="button" class="wsh-assistant__chip">${this.escape(s)}</button>`)
			.join("");
		this.el.suggestions.querySelectorAll(".wsh-assistant__chip").forEach((chip) =>
			chip.addEventListener("click", () => this.send(chip.textContent))
		);
	},

	addMessage(role, text) {
		const div = document.createElement("div");
		div.className = `wsh-assistant__msg wsh-assistant__msg--${role === "user" ? "user" : "assistant"}`;
		div.innerHTML = role === "user" ? this.escape(text) : this.markdown(text);
		this.el.messages.appendChild(div);
		this.scroll();
		return div;
	},

	addNote(text) {
		const div = document.createElement("div");
		div.className = "wsh-assistant__note";
		div.textContent = text;
		this.el.messages.appendChild(div);
	},

	typing(on) {
		let t = this.el.messages.querySelector(".wsh-assistant__typing");
		if (on && !t) {
			t = document.createElement("div");
			t.className = "wsh-assistant__typing";
			t.innerHTML = `<span></span><span></span><span></span> <em>${this.escape(this.config.name)} ${this.escape(this.config.labels.typing)}</em>`;
			this.el.messages.appendChild(t);
			this.scroll();
		} else if (!on && t) {
			t.remove();
		}
	},

	async send(text) {
		text = (text || "").trim();
		if (!text || this.busy) return;
		this.busy = true;
		this.el.input.value = "";
		this.el.suggestions.innerHTML = "";
		this.addMessage("user", text);
		this.typing(true);
		try {
			const out = await this.api("webshop.webshop.assistant.api.send", { message: text, page_route: this.route() });
			this.typing(false);
			this.addMessage("assistant", (out && out.reply) || this.config.labels.error);
		} catch (e) {
			this.typing(false);
			this.addMessage("assistant", this.config.labels.error);
		} finally {
			this.busy = false;
			this.el.input.focus();
		}
	},

	async reset() {
		try {
			await this.api("webshop.webshop.assistant.api.reset", {});
		} catch (e) {
			// a failed reset only means the old thread stays
		}
		this.config.history = [];
		this.renderHistory();
	},

	scroll() {
		this.el.messages.scrollTop = this.el.messages.scrollHeight;
	},

	escape(text) {
		return String(text == null ? "" : text).replace(
			/[&<>"']/g,
			(c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
		);
	},

	// Bold, links, bullet lists and line breaks: what an answer needs, nothing a
	// model could turn into markup. Everything is escaped first.
	markdown(text) {
		let html = this.escape(text);
		html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
		html = html.replace(/\[([^\]]+)\]\(((?:https?:\/\/|\/)[^\s)]+)\)/g, (m, label, url) => `<a href="${url}">${label}</a>`);
		html = html.replace(/(^|[\s(])((?:https?:\/\/[^\s<]+)|(?:\/[a-z0-9][^\s<),.]*))/gi, (m, before, url) =>
			/href="/.test(m) ? m : `${before}<a href="${url}">${url}</a>`
		);
		const lines = html.split(/\n/);
		let out = "", inList = false;
		lines.forEach((line) => {
			const item = line.match(/^\s*[-•]\s+(.*)$/);
			if (item) {
				if (!inList) { out += "<ul>"; inList = true; }
				out += `<li>${item[1]}</li>`;
			} else {
				if (inList) { out += "</ul>"; inList = false; }
				out += line.trim() ? `<p>${line}</p>` : "";
			}
		});
		if (inList) out += "</ul>";
		return out;
	},
};

frappe.ready(() => webshop.assistant.init());
