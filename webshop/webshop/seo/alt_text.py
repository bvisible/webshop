# //// Neoffice — added file (no upstream equivalent): what a product's pictures show, for those who
# //// cannot see them, proposed by a model that sees them. neoffice-maintenance#691, decision D-11
# //// of the SEO plan, 2026-09-25.
"""The pictures' descriptions (alternative text), proposed by a model that sees them (decision D-11).

A product's pictures carried its name as their alternative text: a screen reader said "Trail shoe"
four times, and an image search read the same. A model that sees each picture proposes one
sentence: builder's describe_image, which tries Nora Vision first, then the site's other vision
models. The merchant reads it, corrects it and decides, the same rule as Nora's descriptions
(seo/suggestions.py). The item remembers that its descriptions were written with AI assistance,
never which model.

- The pictures are read from the item on the server, never from an address the browser sends:
  describe_image reads private files and fetches any URL it is given.
- The proposals are made in a background job, one picture after the other, and sent to the form
  as they come (realtime). The first call wakes Nora up (about 20 s), the next take 1 to 3 s each.
- A site without builder, or without a model that sees images, says so once and stops.
"""

import frappe
from frappe import _

EVENT = "webshop_picture_descriptions"
MAX_PICTURES = 12
# Website Item.website_image_alt is a Data field: 140 characters
DATA_LENGTH = 140


def pictures(doc) -> list[frappe._dict]:
	"""The item's pictures, each once, with its current description and the places it sits in: the
	website image (the tiles, and the gallery without a slideshow) and the slides of the gallery.
	The same picture in both places gets one description."""
	found = {}

	def add(image, alt, place):
		picture = found.setdefault(image, frappe._dict(image=image, alt="", places=[]))
		picture.alt = picture.alt or (alt or "").strip()
		picture.places.append(place)

	if doc.website_image:
		add(doc.website_image, doc.get("website_image_alt"), "website_image")
	if doc.slideshow:
		fields = ["name", "image"]
		if frappe.get_meta("Website Slideshow Item").has_field("image_alt"):
			fields.append("image_alt")
		for row in frappe.get_all(
			"Website Slideshow Item",
			filters={"parent": doc.slideshow, "parenttype": "Website Slideshow", "image": ("is", "set")},
			fields=fields,
			order_by="idx asc",
		):
			add(row.image, row.get("image_alt"), row.name)
	return list(found.values())[:MAX_PICTURES]


def context_of(doc) -> str:
	"""What the model is told the picture shows: the product, named as its page names it. A variant's
	pictures usually serve every size of its colour: the model's name, not the variant's."""
	name = doc.web_item_name
	if doc.get("variant_of"):
		name = frappe.db.get_value("Website Item", {"item_code": doc.variant_of}, "web_item_name") or name
	return ", ".join(part for part in (name, doc.brand) if part)


@frappe.whitelist()
def propose(name: str):
	"""Start the proposals for an item's pictures; they reach the form through EVENT."""
	frappe.has_permission("Website Item", "write", name, throw=True)
	doc = frappe.get_doc("Website Item", name)
	found = pictures(doc)
	if not found:
		frappe.throw(_("This product has no picture to describe."))
	frappe.enqueue(
		"webshop.webshop.seo.alt_text.propose_in_background",
		queue="short",
		timeout=900,
		name=name,
		user=frappe.session.user,
	)
	return {"event": EVENT, "pictures": [{"image": p.image, "alt": p.alt} for p in found]}


def propose_in_background(name: str, user: str):
	"""One proposal per picture, sent as it comes; a site without a model that sees stops at once."""
	doc = frappe.get_doc("Website Item", name)
	describe = vision()
	if not describe:
		return _publish(user, name, done=True, reason="no_vision_model")
	context = context_of(doc)
	for picture in pictures(doc):
		try:
			_publish(user, name, image=picture.image, alt=describe(picture.image, context=context))
		except Exception as error:
			reason = getattr(error, "reason", None) or "model_failed"
			if reason == "no_vision_model":
				return _publish(user, name, done=True, reason=reason)
			if reason == "model_failed" and not getattr(error, "reason", None):
				frappe.log_error("Picture description failed", frappe.get_traceback())
			_publish(user, name, image=picture.image, reason=reason)
	_publish(user, name, done=True)


def vision():
	"""builder's describe_image, or None where builder is absent or older than it."""
	if "builder" not in frappe.get_installed_apps():
		return None
	try:
		from builder.site_ai.vision import describe_image
	except ImportError:
		return None
	return describe_image


def _publish(user, name, **message):
	frappe.publish_realtime(EVENT, {"name": name, **message}, user=user, after_commit=False)


@frappe.whitelist()
def save(name: str, descriptions: str | dict):
	"""The descriptions the merchant kept, {picture address: text}. Only the item's own pictures are
	written: an address that is not one of them is ignored."""
	frappe.has_permission("Website Item", "write", name, throw=True)
	descriptions = frappe.parse_json(descriptions) or {}
	doc = frappe.get_doc("Website Item", name)
	values, kept = {}, 0
	for picture in pictures(doc):
		text = " ".join(str(descriptions.get(picture.image) or "").split())
		if not text:
			continue
		for place in picture.places:
			if place == "website_image":
				values["website_image_alt"] = cut(text, DATA_LENGTH)
			else:
				frappe.has_permission("Website Slideshow", "write", doc.slideshow, throw=True)
				frappe.db.set_value("Website Slideshow Item", place, "image_alt", text)
		kept += 1
	if kept:
		# two fields written as they are: a full save re-reads the pictures and would rebuild
		# thumbnails and copies nobody asked for
		values["alt_ai_assisted"] = 1
		doc.db_set(values)
	return {"kept": kept}


def cut(text: str, limit: int) -> str:
	"""At a word, within the limit."""
	if len(text) <= limit:
		return text
	cut_at = text.rfind(" ", 0, limit)
	return text[: cut_at if cut_at > limit // 2 else limit].rstrip(" ,;:")


@frappe.whitelist()
def available() -> bool:
	"""Whether this site can propose descriptions at all: the form hides its button otherwise. A site
	whose builder has no model that sees images says so on the first proposal."""
	frappe.has_permission("Website Item", "write", throw=True)
	return bool(vision())
