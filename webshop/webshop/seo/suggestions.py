# //// Neoffice — added file (no upstream equivalent). neoffice-maintenance#691, lot 6.
"""Nora proposes a page's title and description for search engines; the merchant decides.

The model gets the page's facts only — the product's name, brand, group, description and
characteristics, a category's or a brand's own text and what it holds, the shop's name — and is
told to invent nothing: no feature, no price, no promise the page does not make. It answers with
JSON. The form shows the proposal and fills the fields only when the merchant asks
(public/js/override/seo_preview.js); the document then records that its words were written with
AI assistance (seo_ai_assisted, seo_ai_assisted_on), which Merchant Center asks about, and which a
catalogue rewritten at scale by a model needs to be able to say."""

import json
import re

import frappe
from frappe import _

from webshop.webshop.seo import page_meta
from webshop.webshop.seo.text import html_to_text, one_line

LANGUAGES = {"fr": "français", "de": "allemand", "it": "italien", "en": "anglais", "es": "espagnol"}
TITLE_LIMIT = 60
DESCRIPTION_LIMIT = 155
FACT_LIMIT = 1200

# The model reads this: French, like every text the shop's models read (assistant/prompt.py).
SYSTEM = (
	"Tu rédiges le titre et la description qu'un moteur de recherche affiche pour une page d'une "
	"boutique en ligne. Tu n'utilises que les faits donnés : tu n'inventes ni caractéristique, ni "
	"prix, ni promesse de livraison, de garantie ou de stock. Pas de superlatif gratuit, pas de "
	"majuscules d'accroche, pas d'emoji, pas le nom de la boutique dans le titre. Le titre fait au "
	"plus {title} caractères et nomme ce que la page présente ; pour une catégorie ou une marque, il "
	"dit ce qu'on y trouve, jamais combien il y en a. La description fait entre 110 et "
	"{description} caractères, en une ou deux phrases naturelles qui disent ce qu'on y trouve. "
	"Rédige en {language}. Réponds uniquement par un objet JSON "
	'{{"title": "…", "description": "…"}}.'
)


def site_language() -> str:
	code = (frappe.get_system_settings("language") or "fr").split("-")[0]
	return LANGUAGES.get(code, "français")


def facts(doctype, doc) -> str:
	"""What the model may use, as lines."""
	from webshop.webshop.seo import site

	lines = []
	if doctype == "Website Item":
		lines.append("Page : fiche d'un produit")
		lines.append(f"Produit : {doc.web_item_name}")
		if doc.get("brand"):
			lines.append(f"Marque : {doc.brand}")
		if doc.get("item_group"):
			lines.append(f"Catégorie : {doc.item_group}")
		text = html_to_text(doc.get("web_long_description") or doc.get("description") or "", FACT_LIMIT)
		if text:
			lines.append(f"Description de la page : {text}")
		for row in (doc.get("website_specifications") or [])[:12]:
			label, value = row.get("label"), html_to_text(row.get("description") or "", 200)
			if label and value:
				lines.append(f"Caractéristique — {label} : {value}")
	elif doctype == "Item Group":
		from webshop.webshop.seo.meta import catalogue_summary, subtree_groups

		heading = doc.get("website_title") or doc.name
		total, brands = catalogue_summary(subtree_groups(doc.name))
		lines.append("Page : catégorie de produits")
		lines.append(f"Catégorie : {heading}")
		if total:
			lines.append(f"Nombre de produits : {total}")
		if brands:
			lines.append("Marques principales : " + ", ".join(brands))
		examples = product_names({"item_group": ["in", subtree_groups(doc.name)]})
		if examples:
			lines.append("Exemples de produits : " + " ; ".join(examples))
		text = html_to_text(doc.get("description") or "", FACT_LIMIT)
		if text:
			lines.append(f"Texte de la page : {text}")
	else:
		from webshop.webshop.seo.meta import catalogue_summary

		total, _brands = catalogue_summary(extra_filters={"brand": [doc.name]})
		lines.append("Page : marque")
		lines.append(f"Marque : {doc.name}")
		if total:
			lines.append(f"Nombre de produits : {total}")
		examples = product_names({"brand": doc.name})
		if examples:
			lines.append("Exemples de produits : " + " ; ".join(examples))
		text = html_to_text(doc.get("description") or "", FACT_LIMIT)
		if text:
			lines.append(f"Texte de la page : {text}")
	name = site.shop_name()
	if name:
		lines.append(f"Boutique : {name}")
	return "\n".join(lines)


def product_names(filters, limit=8) -> list[str]:
	"""A few products a category or a brand shows, the best ranked first: without them the model
	guessed what a group named "Salles" sells, and got it wrong (rooms to rent, osiris)."""
	from webshop.webshop.product_data_engine.catalogue_scope import visible_item_filters

	scope = visible_item_filters()
	scope.update(filters)
	return frappe.get_all("Website Item", filters=scope, pluck="web_item_name", order_by="ranking desc", limit=limit)


def parse(content: str):
	"""The model's JSON object, or None: it may wrap it in a code fence or a sentence."""
	found = re.search(r"\{.*\}", content or "", re.S)
	if not found:
		return None
	try:
		data = json.loads(found.group(0))
	except ValueError:
		return None
	title, description = (data.get("title") or "").strip(), (data.get("description") or "").strip()
	if not title or not description:
		return None
	return frappe._dict(title=title, description=description)


@frappe.whitelist()
def suggest(doctype: str, name: str):
	"""Nora's proposal for a page's title and description; nothing is written."""
	if doctype not in page_meta.PREVIEWED:
		frappe.throw(_("No preview for {0}").format(doctype))
	frappe.has_permission(doctype, "write", name, throw=True)
	from webshop.webshop.assistant import llm

	doc = frappe.get_doc(doctype, name)
	system = SYSTEM.format(title=TITLE_LIMIT, description=DESCRIPTION_LIMIT, language=site_language())
	answer = llm.complete(
		[{"role": "system", "content": system}, {"role": "user", "content": facts(doctype, doc)}],
		temperature=0.3,
		max_tokens=400,
	)
	proposal = parse(answer.content)
	if not proposal:
		frappe.throw(_("Nora gave no usable proposal. Try again."))
	return {
		# a model that overshoots is cut at a word, a little beyond the limit: the counters say it
		"title": one_line(proposal.title, TITLE_LIMIT + 10),
		"description": one_line(proposal.description, DESCRIPTION_LIMIT + 45),
		"model": answer.model,
	}
