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
		//// Neoffice — was: the link sent the last suggestion through the model, so a model
		//// outage also cut the customer off from the team. It now opens the direct form.
		this.el.team.addEventListener("click", () => {
			this.showLeaveForm("", !this.config.signed_in);
			this.scroll();
		});
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
		// the answering machine: the server already knows it cannot answer right now
		if (c.notice && c.notice.reply) {
			this.el.suggestions.innerHTML = "";
			this.addMessage("assistant", c.notice.reply);
			if (c.notice.leave_message) this.showLeaveForm("", c.notice.email_required);
		}
	},

	// The form that reaches the team without the model: shown when the assistant
	// cannot answer, and behind the "talk to the team" link. One at a time.
	showLeaveForm(prefill, emailRequired) {
		const L = this.config.labels;
		const old = this.el.messages.querySelector(".wsh-assistant__leave");
		if (old) old.remove();
		const card = document.createElement("div");
		card.className = "wsh-assistant__leave";
		card.innerHTML =
			`<div class="wsh-assistant__leave-title">${this.escape(L.leave_title)}</div>` +
			`<form class="wsh-assistant__leave-form">` +
			(emailRequired
				? `<input type="email" class="wsh-assistant__leave-email" required maxlength="140" autocomplete="email" placeholder="${this.escape(L.leave_email)}">`
				: "") +
			`<textarea class="wsh-assistant__leave-text" rows="3" required maxlength="1000" placeholder="${this.escape(L.leave_placeholder)}">${this.escape(prefill || "")}</textarea>` +
			`<div class="wsh-assistant__leave-error" hidden></div>` +
			`<div class="wsh-assistant__leave-actions">` +
			`<button type="button" class="wsh-assistant__leave-cancel">${this.escape(L.leave_cancel)}</button>` +
			`<button type="submit" class="wsh-assistant__leave-send">${this.escape(L.leave_send)}</button></div></form>`;
		this.el.messages.appendChild(card);
		const form = card.querySelector("form");
		const text = card.querySelector(".wsh-assistant__leave-text");
		const email = card.querySelector(".wsh-assistant__leave-email");
		const error = card.querySelector(".wsh-assistant__leave-error");
		const button = card.querySelector(".wsh-assistant__leave-send");
		card.querySelector(".wsh-assistant__leave-cancel").addEventListener("click", () => card.remove());
		form.addEventListener("submit", async (e) => {
			e.preventDefault();
			const message = text.value.trim();
			if (!message || (email && !email.value.trim())) return;
			button.disabled = true;
			error.hidden = true;
			try {
				const out = await this.api("webshop.webshop.assistant.api.leave_message", {
					message,
					email: email ? email.value.trim() : undefined,
					page_route: this.route(),
				});
				card.remove();
				this.addMessage("user", message);
				this.addMessage("assistant", (out && out.reply) || L.leave_error);
			} catch (err) {
				error.textContent = this.serverMessage(err) || L.leave_error;
				error.hidden = false;
				button.disabled = false;
			}
		});
		this.scroll();
		setTimeout(() => (email && !email.value ? email : text).focus(), 50);
		return card;
	},

	// What frappe.throw said, if the response carries it; else nothing.
	serverMessage(err) {
		try {
			const raw = err && err.responseJSON && err.responseJSON._server_messages;
			if (!raw) return "";
			const first = JSON.parse(raw)[0];
			const parsed = typeof first === "string" ? JSON.parse(first) : first;
			const tmp = document.createElement("div");
			tmp.innerHTML = (parsed && parsed.message) || "";
			return tmp.textContent.trim();
		} catch (e) {
			return "";
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
			// the answering machine: the notice was just shown, now the form, with the words it could not answer
			if (out && out.unavailable && out.leave_message) this.showLeaveForm(text, out.email_required);
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
