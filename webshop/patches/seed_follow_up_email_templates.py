# //// Neoffice — added file (purchase follow-ups, no upstream equivalent).
# //// The email templates a shop starts from, and two follow-ups switched
# //// OFF: a client instance must never start mailing its customers because
# //// it migrated. The shop owner reads, edits, and enables.

import frappe

STYLE = "font-family: -apple-system, Segoe UI, Roboto, sans-serif; font-size: 15px; line-height: 1.5; color: #1f2937;"
BUTTON = "display:inline-block;padding:10px 18px;border-radius:8px;background:#111827;color:#ffffff;text-decoration:none;font-weight:600;"

TEMPLATES = {
	"Webshop - How is it going": {
		"subject": "Comment se passe votre {{ item_name }} ?",
		"response_html": f"""<div style="{STYLE}">
<p>Bonjour {{{{ customer_name }}}},</p>
<p>Voilà une semaine que vous avez reçu votre <strong>{{{{ item_name }}}}</strong>. Est-ce que tout se passe bien ?</p>
<p>Si quelque chose vous freine, répondez simplement à ce message : nous lisons chaque réponse.</p>
{{% if is_second_hand %}}<p>Pour rappel, cette unité d'occasion est garantie {{{{ warranty_months }}}} mois. Un défaut constaté se signale sans attendre.</p>{{% endif %}}
<p><a href="{{{{ product_url }}}}" style="{BUTTON}">Revoir la fiche produit</a></p>
<p>Merci de votre confiance,<br>{{{{ shop_name }}}}</p>
</div>""",
	},
	"Webshop - Your opinion": {
		"subject": "Votre avis sur {{ item_name }}",
		"response_html": f"""<div style="{STYLE}">
<p>Bonjour {{{{ customer_name }}}},</p>
<p>Deux semaines avec votre <strong>{{{{ item_name }}}}</strong> : qu'en pensez-vous ? Votre avis aide les prochains clients à choisir, et il nous aide à mieux faire.</p>
<p><a href="{{{{ review_url }}}}" style="{BUTTON}">Donner mon avis</a></p>
<p>Une note et deux lignes suffisent. Merci !<br>{{{{ shop_name }}}}</p>
</div>""",
	},
	"Webshop - Recommended with your purchase": {
		"subject": "Pour aller avec votre {{ item_name }}",
		"response_html": f"""<div style="{STYLE}">
<p>Bonjour {{{{ customer_name }}}},</p>
<p>Vous avez choisi <strong>{{{{ item_name }}}}</strong>. Voici ce que nos clients prennent avec :</p>
{{% for o in offers %}}
<table style="margin:12px 0;border:1px solid #e5e7eb;border-radius:10px;border-collapse:separate;width:100%;max-width:520px;"><tr>
<td style="padding:12px;width:72px;">{{% if o.image %}}<img src="{{{{ o.image }}}}" width="64" height="64" style="border-radius:8px;object-fit:cover;">{{% endif %}}</td>
<td style="padding:12px;"><div style="font-size:12px;color:#6b7280;text-transform:uppercase;">{{{{ o.headline }}}}</div>
<div style="font-weight:600;">{{{{ o.web_item_name }}}}</div>
<div><strong>{{{{ o.formatted_offer_price }}}}</strong>{{% if o.has_advantage %}} <s style="color:#9ca3af;">{{{{ o.formatted_price }}}}</s> <span style="color:#166534;">{{{{ o.advantage }}}}</span>{{% endif %}}</div>
<div style="margin-top:6px;"><a href="{{{{ o.url }}}}">Voir l'article</a></div></td></tr></table>
{{% else %}}
<p><a href="{{{{ shop_url }}}}">Découvrir la boutique</a></p>
{{% endfor %}}
<p>{{{{ shop_name }}}}</p>
</div>""",
	},
	"Webshop - Time to restock": {
		"subject": "Il est temps de renouveler votre {{ item_name }}",
		"response_html": f"""<div style="{STYLE}">
<p>Bonjour {{{{ customer_name }}}},</p>
<p>D'après votre dernier achat du {{{{ purchase_date }}}}, votre <strong>{{{{ item_name }}}}</strong> touche à sa fin.</p>
<p><a href="{{{{ reorder_url }}}}" style="{BUTTON}">Recommander en un clic</a></p>
<p>Le lien met l'article dans votre panier ; vous validez quand vous voulez.<br>{{{{ shop_name }}}}</p>
</div>""",
	},
	"Webshop - Your cart is waiting": {
		"subject": "Votre panier vous attend",
		"response_html": f"""<div style="{STYLE}">
<p>Bonjour {{{{ customer_name }}}},</p>
<p>Vous avez laissé ces articles dans votre panier :</p>
<table style="border-collapse:collapse;width:100%;max-width:520px;">
{{% for line in cart_items %}}<tr><td style="padding:6px 0;border-bottom:1px solid #eef0f3;">{{{{ line.item_name }}}} × {{{{ line.qty | int }}}}</td><td style="padding:6px 0;border-bottom:1px solid #eef0f3;text-align:right;">{{{{ line.amount }}}}</td></tr>{{% endfor %}}
<tr><td style="padding:8px 0;font-weight:600;">Total</td><td style="padding:8px 0;text-align:right;font-weight:600;">{{{{ cart_total }}}}</td></tr>
</table>
{{% if coupon_code %}}<p>Pour vous décider : <strong>{{{{ discount_percentage | int }}}} %</strong> avec le code <strong>{{{{ coupon_code }}}}</strong>, valable jusqu'au {{{{ coupon_valid_until }}}}. Le lien ci-dessous l'applique pour vous.</p>{{% endif %}}
<p><a href="{{{{ cart_url }}}}" style="{BUTTON}">Retrouver mon panier</a></p>
<p>{{{{ shop_name }}}}</p>
</div>""",
	},
}

FLOWS = [
	{
		"title": "Suivi après achat",
		"enabled": 0,
		"trigger_type": "All Purchases",
		"nature": "Transactional",
		"steps": [
			{"label": "Prise de nouvelles", "days_after": 7, "email_template": "Webshop - How is it going"},
			{"label": "Demande d'avis", "days_after": 14, "email_template": "Webshop - Your opinion"},
			{"label": "Vente croisée", "days_after": 21, "email_template": "Webshop - Recommended with your purchase", "stop_if_reordered": 1},
		],
	},
	{
		"title": "Réassort des consommables",
		"enabled": 0,
		"trigger_type": "All Purchases",
		"nature": "Marketing",
		"steps": [
			{"label": "Réassort", "days_after": 0, "use_item_cycle": 1, "email_template": "Webshop - Time to restock", "stop_if_reordered": 1},
		],
	},
]


def execute():
	for name, data in TEMPLATES.items():
		if frappe.db.exists("Email Template", name):
			continue
		frappe.get_doc(
			{"doctype": "Email Template", "name": name, "subject": data["subject"], "use_html": 1, "response_html": data["response_html"], "response": ""}
		).insert(ignore_permissions=True)

	if frappe.db.exists("DocType", "Purchase Follow-up"):
		for flow in FLOWS:
			if frappe.db.exists("Purchase Follow-up", {"title": flow["title"]}):
				continue
			frappe.get_doc({"doctype": "Purchase Follow-up", **flow}).insert(ignore_permissions=True)

	if frappe.db.exists("DocType", "Webshop Settings") and frappe.get_meta("Webshop Settings").has_field("abandoned_cart_template"):
		if not frappe.db.get_single_value("Webshop Settings", "abandoned_cart_template"):
			frappe.db.set_single_value("Webshop Settings", "abandoned_cart_template", "Webshop - Your cart is waiting")
	frappe.db.commit()
