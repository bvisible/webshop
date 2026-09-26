# //// Neoffice — added file (no upstream equivalent): a product's SEO score, stored on the item, and
# //// the shop's, day by day. neoffice-maintenance#691, plan note 20 (part 1), 2026-09-26.
"""A product's SEO score: out of 100, how much of what search engines, Google Shopping and AI
assistants read of it is there, and what to do about the rest.

- One reading of the rules. The score reads what the page, its structured data and the feed already
  compute (seo/page_meta.py, seo/facts.py, seo/feeds/google.py), never a copy of their rules: a
  score that disagreed with the report would be one more thing to reconcile.
- A criterion is good (its points), to improve (half of them) or missing (none). One that does not
  concern the product is left out of the total: a gift card is not punished for having no barcode.
  Reviews and videos are shown, never counted: they depend on the customers, not on the work.
- The offer and "sent to Google" are what a visitor gets, computed as the feed computes them:
  inside seo.feeds.google.serving(), which only a background job may enter. So the score is
  computed in a job (after the item is saved, when its form opens, every night) and stored on the
  item: seo_score for the list, the cards and the charts, seo_score_details for the form's
  checklist, which the job's answer (EVENT, on the document's room) redraws.
- The score is the merchant's, never the public's: it only shows on the desk.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, now_datetime, nowdate

GOOD, IMPROVE, MISSING, NOT_APPLICABLE = "good", "improve", "missing", "not_applicable"
EARNED = {GOOD: 1.0, IMPROVE: 0.5, MISSING: 0.0}
# (criterion, points): 100 together
CRITERIA = (
	("title", 10),
	("search_description", 10),
	("long_description", 12),
	("pictures", 10),
	("alt_text", 8),
	("identifier", 15),
	("brand", 5),
	("google_category", 5),
	("specifications", 5),
	("offer", 10),
	("sent_to_google", 10),
)
TITLE_SHORT = 30  # characters of the browser tab's title
DESCRIPTION_SHORT = 70  # characters of the description under the title in Google's results
GOOD_PICTURES = 3
GOOD_SPECIFICATIONS = 3
# The feed leaves a product out for these by the merchant's choice or by design: no defect of its own
LEFT_OUT_BY_DESIGN = ("model", "gift_card", "service", "second_hand_off", "excluded")
EVENT = "webshop_seo_score"
# The form's score bands, the list's and the charts'
BANDS = ((0, 49), (50, 79), (80, 100))
SNAPSHOT_DAYS = 400
# A pass over the catalogue commits as it goes: holding every item's row lock until the end would
# make a merchant's save wait on the night job
COMMIT_EVERY = 50
_UNREAD = object()


# ---------------------------------------------------------------------------------------------
# What the score reads


def site_context() -> frappe._dict:
	"""The site being served, as the feed reads it: its settings, whether it has a feed at all,
	the item groups kept out of Google Shopping and the names of the variant attributes."""
	from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings
	from webshop.webshop.seo.feeds import google

	settings = get_shopping_cart_settings()
	return frappe._dict(
		settings=settings,
		refusal=google.site_refusal(settings),
		excluded=google.excluded_groups(),
		mapping=google.attribute_map(settings),
	)


def product_kind(doc, settings) -> str:
	"""What the product is, for the criteria that do not concern every product."""
	from webshop.webshop.seo.feeds.google import is_service
	from webshop.webshop.seo.variants import group_model

	if cint(doc.get("is_gift_card")):
		return "gift_card"
	if cint(doc.get("has_variants")):
		return "model"
	if doc.get("variant_of") and group_model(doc, settings):
		return "grouped_variant"
	if is_service(doc.item_code):
		return "service"
	return "product"


def gather(doc, site, entry=_UNREAD, reason=None) -> frappe._dict:
	"""What the score reads of one product, as a visitor of the site being served gets it. `entry`
	and `reason` are the feed's answer when the caller already has it (the report)."""
	from frappe.website.doctype.website_slideshow.website_slideshow import get_slideshow

	from webshop.webshop.seo import facts, page_meta
	from webshop.webshop.seo.alt_text import pictures
	from webshop.webshop.seo.feeds import google
	from webshop.webshop.seo.text import html_to_text
	from webshop.webshop.utils.renditions import picture_size

	if entry is _UNREAD:
		try:
			entry, reason = google.item_entry(doc, site.settings, site.excluded, site.mapping)
		except Exception:
			frappe.log_error(f"SEO score: the feed's item of {doc.item_code} failed", frappe.get_traceback())
			entry, reason = None, "error"
	kind = product_kind(doc, site.settings)
	name = (doc.web_item_name or doc.item_code or "").strip()
	meta = page_meta.product_meta(doc)
	# what the page prints as the product's description (item.html): the website's text, else the item's
	long_text = html_to_text(doc.get("web_long_description") or "") or html_to_text(doc.get("description") or "")
	context = frappe._dict(get_slideshow(doc)) if doc.get("slideshow") else frappe._dict()
	gallery = facts.gallery_images(doc, context)

	found = frappe._dict(
		kind=kind,
		name=name,
		# what says nothing of the product: its own names and code, which ERPNext writes as the
		# description of an item nobody described
		bare=frozenset(
			text.strip().lower() for text in (name, doc.get("item_name"), doc.item_code) if text and text.strip()
		),
		published=cint(doc.get("published")),
		sold=cint(doc.get("sold")),
		refusal=site.refusal,
		title=meta.html_title or "",
		description=meta.description or "",
		long_text=long_text,
		sent=bool(entry),
		reason=reason,
		brand=doc.get("brand"),
		item_group=doc.get("item_group"),
		no_product_identifier=cint(doc.get("no_product_identifier")),
		specifications=len(facts.specifications(doc)),
		videos=len(doc.get("videos") or []),
	)

	# the offer and the pictures a visitor gets: the feed's item when there is one, else the page's
	images = gallery
	if entry:
		found.offer = frappe._dict(price=entry.get("sale_price") or entry.get("price"), availability=entry.get("availability"))
		images = [entry.get("image_link"), *(entry.get("additional_image_link") or [])]
	elif kind == "model":
		found.variants = model_offers(doc, site.settings)
	elif kind in ("product", "grouped_variant") and reason not in ("no_price", "error"):
		page = google.page_offer(doc, site.settings)
		if page.offer:
			found.offer = frappe._dict(
				price=google.money(page.offer.price, page.offer.currency),
				availability=google.AVAILABILITY.get(page.availability, "out_of_stock"),
			)
		images = page.images or gallery
	found.pictures = len([image for image in dict.fromkeys(images) if image])
	size = picture_size(gallery[0]) if gallery else None
	found.first_picture_width = min(size) if size else None

	described = pictures(doc)
	found.alt_total = len(described)
	found.alt_described = sum(
		1 for picture in described if picture.alt and picture.alt.strip().lower() != name.lower()
	)

	identifiers = facts.product_identifiers(doc.item_code)
	found.gtin = next((value for key, value in identifiers.items() if key.startswith("gtin")), None)
	found.mpn = identifiers.get("mpn")
	# a barcode that is no usable GTIN is said, with why: the merchant corrects it, or learns it is
	# a code of the shop's own
	found.barcode_problem = None
	if not found.gtin and kind not in ("model", "gift_card", "service"):
		found.barcode_problem = facts.barcode_problem(doc.item_code, doc.get("stock_uom"))
	found.google_category = google.google_category(doc.get("item_group"))
	found.reviews, found.rating = reviews_of(doc.name)
	return found


def model_offers(doc, settings) -> frappe._dict:
	"""The variants a model's page offers a visitor: how many have a price, how many can be bought."""
	from webshop.webshop.seo.availability import OUT_OF_STOCK
	from webshop.webshop.seo.variants import model_view

	view = model_view(doc.item_code, settings)
	priced = [row for row in (view.rows.values() if view else []) if row.price]
	return frappe._dict(
		shown=bool(view),
		priced=len(priced),
		available=sum(1 for row in priced if row.availability != OUT_OF_STOCK),
	)


def reviews_of(website_item: str) -> tuple[int, float | None]:
	"""How many reviews the product has, and their average out of 5 (the Rating field stores 0..1)."""
	row = frappe.get_all(
		"Item Review",
		filters={"website_item": website_item},
		fields=["count(name) as reviews", "avg(rating) as rating"],
	)
	count = cint(row[0].reviews) if row else 0
	return count, (flt(row[0].rating) * 5 if count else None)


# ---------------------------------------------------------------------------------------------
# The criteria


def bare_texts(f) -> frozenset:
	"""The texts that say nothing of the product: its names and its code."""
	return f.get("bare") or frozenset({f.name.lower()})


def judge_title(f):
	if f.kind == "grouped_variant":
		return NOT_APPLICABLE, {"why": "model_page"}
	from webshop.webshop.seo.page_meta import TITLE_BUDGET

	length = len(f.title)
	if length > TITLE_BUDGET:
		return IMPROVE, {"length": length, "problem": "long", "target": TITLE_BUDGET}
	if length < TITLE_SHORT:
		return IMPROVE, {"length": length, "problem": "short", "target": TITLE_SHORT}
	return GOOD, {"length": length}


def judge_search_description(f):
	if f.kind == "grouped_variant":
		return NOT_APPLICABLE, {"why": "model_page"}
	from webshop.webshop.seo.page_meta import DESCRIPTION_BUDGET

	text = f.description.strip()
	length = len(text)
	# the page falls back on the product's name when it has nothing else to say
	if not text or text.lower() in bare_texts(f):
		return MISSING, {"length": length}
	if length < DESCRIPTION_SHORT:
		return IMPROVE, {"length": length, "problem": "short", "target": DESCRIPTION_SHORT}
	if length > DESCRIPTION_BUDGET:
		return IMPROVE, {"length": length, "problem": "long", "target": DESCRIPTION_BUDGET}
	return GOOD, {"length": length}


def judge_long_description(f):
	from webshop.webshop.seo.suggestions import DESCRIPTION_WORDS

	text = f.long_text.strip()
	words = len(text.split())
	# an item's description is its name or its code until somebody writes one (ERPNext fills it so)
	if not text or text.lower() in bare_texts(f):
		return MISSING, {"words": 0}
	if words < DESCRIPTION_WORDS[0]:
		return IMPROVE, {"words": words, "target": DESCRIPTION_WORDS[0]}
	return GOOD, {"words": words}


def judge_pictures(f):
	from webshop.webshop.seo.feeds.google import GOOD_PICTURE

	if not f.pictures:
		return MISSING, {"count": 0}
	if f.first_picture_width and f.first_picture_width < GOOD_PICTURE:
		return IMPROVE, {"count": f.pictures, "width": f.first_picture_width, "problem": "small", "target": GOOD_PICTURE}
	if f.pictures < GOOD_PICTURES:
		return IMPROVE, {"count": f.pictures, "problem": "few", "target": GOOD_PICTURES}
	return GOOD, {"count": f.pictures}


def judge_alt_text(f):
	if f.kind == "grouped_variant":
		return NOT_APPLICABLE, {"why": "model_page"}
	if not f.alt_total:
		# no picture: the pictures' criterion says so
		return NOT_APPLICABLE, {"why": "no_picture"}
	if f.alt_described >= f.alt_total:
		return GOOD, {"described": f.alt_described, "total": f.alt_total}
	if f.alt_described:
		return IMPROVE, {"described": f.alt_described, "total": f.alt_total}
	return MISSING, {"described": 0, "total": f.alt_total}


def judge_identifier(f):
	if f.kind == "model":
		return NOT_APPLICABLE, {"why": "variants"}
	if f.kind in ("gift_card", "service"):
		return NOT_APPLICABLE, {"why": f.kind}
	if f.gtin:
		return GOOD, {"gtin": f.gtin}
	if f.no_product_identifier:
		return NOT_APPLICABLE, {"why": "declared"}
	problem = f.get("barcode_problem")
	detail = {"barcode": problem.barcode, "problem": problem.problem, "uom": problem.get("uom")} if problem else {}
	if f.mpn:
		return IMPROVE, {"mpn": f.mpn, **detail}
	return MISSING, detail


def judge_brand(f):
	if f.kind in ("gift_card", "service"):
		return NOT_APPLICABLE, {"why": f.kind}
	if f.brand:
		return GOOD, {"brand": f.brand}
	return MISSING, {}


def judge_google_category(f):
	if f.refusal:
		return NOT_APPLICABLE, {"why": "no_feed"}
	if f.kind in ("gift_card", "service", "model"):
		return NOT_APPLICABLE, {"why": "variants" if f.kind == "model" else f.kind}
	if f.reason in ("excluded", "second_hand_off"):
		return NOT_APPLICABLE, {"why": "left_out", "reason": f.reason}
	if f.google_category:
		return GOOD, {"category": f.google_category}
	return MISSING, {"group": f.item_group}


def judge_specifications(f):
	if f.kind == "gift_card":
		return NOT_APPLICABLE, {"why": f.kind}
	if f.kind == "grouped_variant":
		return NOT_APPLICABLE, {"why": "model_page"}
	if f.specifications >= GOOD_SPECIFICATIONS:
		return GOOD, {"count": f.specifications}
	if f.specifications:
		return IMPROVE, {"count": f.specifications, "target": GOOD_SPECIFICATIONS}
	return MISSING, {"count": 0}


def judge_offer(f):
	if f.refusal:
		return NOT_APPLICABLE, {"why": "no_feed"}
	if f.kind in ("gift_card", "service"):
		return NOT_APPLICABLE, {"why": f.kind}
	if f.kind == "model":
		variants = f.get("variants") or frappe._dict()
		if not variants.get("shown"):
			return NOT_APPLICABLE, {"why": "own_pages"}
		if not variants.priced:
			return MISSING, {"problem": "no_variant_price"}
		if not variants.available:
			return IMPROVE, {"variants": variants.priced, "problem": "out_of_stock"}
		return GOOD, {"variants": variants.priced}
	if f.reason == "error":
		return MISSING, {"problem": "error"}
	offer = f.get("offer")
	if not offer:
		return MISSING, {"problem": "no_price"}
	if offer.availability == "out_of_stock":
		return IMPROVE, {"price": offer.price, "availability": offer.availability, "problem": "out_of_stock"}
	return GOOD, {"price": offer.price, "availability": offer.availability}


def judge_sent_to_google(f):
	if f.refusal:
		return NOT_APPLICABLE, {"why": "no_feed"}
	if not f.published:
		return NOT_APPLICABLE, {"why": "unpublished"}
	if f.sold:
		return NOT_APPLICABLE, {"why": "sold"}
	if f.sent:
		return GOOD, {}
	if f.reason in LEFT_OUT_BY_DESIGN:
		return NOT_APPLICABLE, {"why": "left_out", "reason": f.reason}
	return MISSING, {"reason": f.reason}


JUDGES = {
	"title": judge_title,
	"search_description": judge_search_description,
	"long_description": judge_long_description,
	"pictures": judge_pictures,
	"alt_text": judge_alt_text,
	"identifier": judge_identifier,
	"brand": judge_brand,
	"google_category": judge_google_category,
	"specifications": judge_specifications,
	"offer": judge_offer,
	"sent_to_google": judge_sent_to_google,
}


def evaluate(found) -> frappe._dict:
	"""The score and its checklist, from what gather() read."""
	criteria = []
	for code, points in CRITERIA:
		status, detail = JUDGES[code](found)
		criteria.append(
			frappe._dict(code=code, points=points, status=status, earned=points * EARNED.get(status, 0), detail=detail)
		)
	counted = [criterion for criterion in criteria if criterion.status != NOT_APPLICABLE]
	possible = sum(criterion.points for criterion in counted)
	score = round(100 * sum(criterion.earned for criterion in counted) / possible) if possible else None
	return frappe._dict(
		score=score,
		criteria=criteria,
		informative=[
			frappe._dict(code="reviews", detail={"count": found.reviews, "rating": found.rating}),
			frappe._dict(code="videos", detail={"count": found.videos}),
		],
		missing=[criterion.code for criterion in criteria if criterion.status == MISSING],
		sent=found.sent,
		google_status=google_status(criteria),
	)


def google_status(criteria) -> str:
	"""What Google Shopping gets of the product, in one word for the list and the chart: "sent",
	why the feed leaves it out (seo.feeds.google.reason_label), or why no feed concerns it."""
	sent = next(criterion for criterion in criteria if criterion.code == "sent_to_google")
	if sent.status == GOOD:
		return "sent"
	detail = sent.detail or {}
	return detail.get("reason") or detail.get("why") or ""


def product_score(doc, site, entry=_UNREAD, reason=None) -> frappe._dict:
	"""One product's score, inside serving(site): see gather()."""
	return evaluate(gather(doc, site, entry, reason))


def band_of(score) -> int | None:
	"""The index of the band a score falls in (BANDS), or None without a score."""
	if score is None:
		return None
	return next(index for index, (low, high) in enumerate(BANDS) if low <= score <= high)


# ---------------------------------------------------------------------------------------------
# Stored on the item


def store(name: str, result, site_key: str):
	"""The score on the item, without touching `modified`: the merchant's form stays saveable."""
	details = {
		"site": site_key,
		"score": result.score,
		"criteria": result.criteria,
		"informative": result.informative,
	}
	frappe.db.set_value(
		"Website Item",
		name,
		{
			"seo_score": result.score or 0,
			"seo_score_checked_on": now_datetime(),
			"seo_score_details": json.dumps(details, default=str),
			# wrapped in commas, so that a card's filter "like %,identifier,%" matches one code
			"seo_missing": f",{','.join(result.missing)}," if result.missing else "",
			"seo_google_status": result.google_status,
		},
		update_modified=False,
	)


def scoring_sites() -> list[frappe._dict]:
	"""The sites a feed is written for, the main one first (its Website Profile is the default)."""
	from webshop.webshop.seo.feeds import google

	return sorted(google.feed_sites(), key=lambda site: 0 if (site.profile or {}).get("is_default") else 1)


def score_item(name: str) -> frappe._dict | None:
	"""A product's score, stored: the one of the first site that shows it and has a feed, the main
	site first. A site that hides its prices from visitors (a business site) has no feed, and its
	score would leave the offer and Google Shopping out: it is kept only when no other site shows
	the product. None when no site shows it."""
	from webshop.webshop.multi_site import excluded_item_names
	from webshop.webshop.seo.feeds import google

	if not frappe.db.exists("Website Item", name):
		return None
	doc = frappe.get_doc("Website Item", name)
	fallback = None
	for site in scoring_sites():
		with google.serving(site):
			if name in set(excluded_item_names() or []):
				continue
			context = site_context()
			result = product_score(doc, context)
		if not context.refusal:
			store(name, result, site.key)
			return result
		fallback = fallback or (result, site.key)
	if fallback:
		store(name, *fallback)
		return fallback[0]
	return None


def refresh_item(name: str):
	"""The job behind a save and an opened form: the product's score, stored, then told to every
	form open on it."""
	result = score_item(name)
	if result is not None:
		frappe.publish_realtime(
			EVENT,
			{"name": name, "score": result.score},
			doctype="Website Item",
			docname=name,
			after_commit=True,
		)


def queue_item(name: str, after_commit: bool = True):
	"""One computation per product in the queue at a time: a save and the form's reload share it.
	After a save, the job waits for the commit, or it would read the item as it was."""
	frappe.enqueue(
		"webshop.webshop.seo.score.refresh_item",
		queue="short",
		job_id=f"webshop_seo_score::{name}",
		deduplicate=True,
		enqueue_after_commit=after_commit,
		name=name,
	)


def on_website_item_update(doc, method=None):
	"""doc_events: a saved product is scored again, in the background."""
	if frappe.flags.in_import or frappe.flags.in_install or frappe.flags.in_patch or frappe.flags.in_migrate:
		return
	queue_item(doc.name)


@frappe.whitelist()
def checklist(name: str, refresh: int = 1):
	"""The product's stored score and checklist, in the reader's language. With `refresh`, a fresh
	computation is queued: when it is stored, EVENT reaches every form open on the product."""
	frappe.has_permission("Website Item", "read", name, throw=True)
	values = frappe.db.get_value(
		"Website Item", name, ["seo_score", "seo_score_checked_on", "seo_score_details"], as_dict=True
	)
	if values is None:
		frappe.throw(_("Website Item {0} not found").format(name), frappe.DoesNotExistError)
	if cint(refresh):
		# nothing of this request to wait for, and a GET is never committed
		queue_item(name, after_commit=False)
	details = json.loads(values.seo_score_details) if values.seo_score_details else None
	return {
		"name": name,
		"event": EVENT,
		"score": details.get("score") if details else None,
		"band": band_of(details.get("score")) if details else None,
		"checked_on": values.seo_score_checked_on,
		"criteria": [explain(frappe._dict(row)) for row in details.get("criteria") or []] if details else [],
		"informative": [explain_informative(frappe._dict(row)) for row in details.get("informative") or []]
		if details
		else [],
	}


# ---------------------------------------------------------------------------------------------
# In the reader's words


def criterion_label(code: str) -> str:
	return {
		"title": _("Title for search engines"),
		"search_description": _("Description for search engines"),
		"long_description": _("Description of the product"),
		"pictures": _("Pictures"),
		"alt_text": _("Picture descriptions"),
		"identifier": _("GTIN (EAN) or manufacturer's reference"),
		"brand": _("Brand"),
		"google_category": _("Google product category"),
		"specifications": _("Characteristics"),
		"offer": _("Price and availability"),
		"sent_to_google": _("Sent to Google Shopping"),
		"reviews": _("Customer reviews"),
		"videos": _("Videos"),
	}.get(code, code)


def not_applicable_message(detail: dict) -> str:
	from webshop.webshop.seo.feeds.google import reason_label

	why = detail.get("why")
	if why == "left_out":
		return reason_label(detail.get("reason"))
	return {
		"model_page": _("Sold on its model's page, which search engines read instead"),
		"variants": _("Its variants carry it"),
		"gift_card": _("Not asked of a gift card"),
		"service": _("Not asked of a service"),
		"declared": _("No barcode exists for this product (declared on the item)"),
		"no_feed": _("This site sends no feed to Google Shopping"),
		"no_picture": _("No picture yet"),
		"own_pages": _("Each variant is sold on its own page"),
		"unpublished": _("Not published"),
		"sold": _("Sold"),
	}.get(why, "")


def google_status_label(status: str) -> str:
	"""A value of Website Item.seo_google_status, as the chart names it."""
	from webshop.webshop.seo.feeds.google import reason_label

	if status == "sent":
		return _("Sent")
	if status in ("no_feed", "unpublished", "sold"):
		return not_applicable_message({"why": status})
	return reason_label(status) if status else _("Not scored yet")


def barcode_problem_message(d: dict) -> str:
	"""Why the item's barcode is not used as its GTIN (seo.facts.gtin_problem)."""
	barcode = d.get("barcode")
	if not barcode:
		return ""
	return {
		"length": _("The barcode {0} is not an EAN, UPC or GTIN (8, 12, 13 or 14 digits): a code of the shop's own"),
		"check_digit": _("The barcode {0} has a wrong check digit: compare it with the packaging"),
		"restricted": _("The barcode {0} is a number for use inside a shop (GS1 prefix 2, 02 or 04): Google refuses it"),
		"coupon": _("The barcode {0} is a coupon's number: Google refuses it"),
		"other_unit": _("The barcode {0} is the one of another unit ({1}), not of the product sold"),
	}.get(d.get("problem"), "").format(barcode, d.get("uom") or "")


def availability_label(availability: str) -> str:
	return {
		"in_stock": _("in stock"),
		"backorder": _("on backorder"),
		"out_of_stock": _("out of stock"),
	}.get(availability, availability or "")


def criterion_message(code: str, status: str, d: dict) -> str:
	"""What the criterion found, and what to do about it."""
	from webshop.webshop.seo.feeds.google import reason_label
	from webshop.webshop.seo.page_meta import DESCRIPTION_BUDGET

	if status == NOT_APPLICABLE:
		return not_applicable_message(d)
	problem = d.get("problem")
	if code == "title":
		if problem == "long":
			return _("{0} characters: Google cuts it after about {1}").format(d["length"], d["target"])
		if problem == "short":
			return _("{0} characters: too short to say what the product is").format(d["length"])
		return _("{0} characters, shown whole").format(d["length"])
	if code == "search_description":
		if status == MISSING:
			return _("Nothing but the product's name: write one, or a description it can be taken from")
		if problem == "short":
			return _("{0} characters: Google shows about {1}").format(d["length"], DESCRIPTION_BUDGET)
		if problem == "long":
			return _("{0} characters: Google cuts it after about {1}").format(d["length"], d["target"])
		return _("{0} characters").format(d["length"])
	if code == "long_description":
		if status == MISSING:
			return _("No description: the page says nothing a search could find")
		if status == IMPROVE:
			return _("{0} words: say more, from {1} words on").format(d["words"], d["target"])
		return _("{0} words").format(d["words"])
	if code == "pictures":
		if status == MISSING:
			return _("No picture: Google Shopping refuses the product")
		if problem == "small":
			return _("The main picture is {0} px wide: {1} px or more").format(d["width"], d["target"])
		if problem == "few":
			return _("Pictures: {0}. Show other views, from {1} on").format(d["count"], d["target"])
		return _("Pictures: {0}").format(d["count"])
	if code == "alt_text":
		if status == MISSING:
			return _("No picture is described: screen readers and image searches read only the product's name")
		if status == IMPROVE:
			return _("{0} of {1} pictures described").format(d["described"], d["total"])
		return _("Every picture is described")
	if code == "identifier":
		if status == GOOD:
			return _("GTIN {0}").format(d["gtin"])
		why = barcode_problem_message(d)
		if status == IMPROVE:
			message = _("Manufacturer's reference {0} but no GTIN: add the EAN if the product has one").format(d["mpn"])
			return f"{message}. {why}" if why else message
		message = _("No GTIN (EAN) and no manufacturer's reference: Google shows a branded product less often without one")
		return f"{message}. {why}" if why else message
	if code == "brand":
		return d["brand"] if status == GOOD else _("No brand")
	if code == "google_category":
		if status == GOOD:
			return d["category"]
		return _("No Google product category on the item group {0} or above it").format(d.get("group") or "")
	if code == "specifications":
		if status == MISSING:
			return _("No characteristics listed")
		if status == IMPROVE:
			return _("Characteristics: {0}. List at least {1}").format(d["count"], d["target"])
		return _("Characteristics: {0}").format(d["count"])
	if code == "offer":
		if problem == "no_price":
			return _("No price shown to a visitor")
		if problem == "no_variant_price":
			return _("No variant has a price for a visitor")
		if problem == "error":
			return _("The offer could not be read: see the Error Log")
		if problem == "out_of_stock":
			return _("Shown out of stock: Google shows it less")
		if "variants" in d:
			return _("Variants on sale: {0}").format(d["variants"])
		return f"{d.get('price') or ''}, {availability_label(d.get('availability'))}".strip(", ")
	if code == "sent_to_google":
		return _("In the feed") if status == GOOD else reason_label(d.get("reason"))
	return ""


def explain(criterion) -> dict:
	return {
		"code": criterion.code,
		"status": criterion.status,
		"points": criterion.points,
		"earned": criterion.earned,
		"label": criterion_label(criterion.code),
		"message": criterion_message(criterion.code, criterion.status, criterion.detail or {}),
	}


def explain_informative(row) -> dict:
	detail = row.detail or {}
	count = cint(detail.get("count"))
	if row.code == "reviews":
		message = (
			_("{0} reviews, {1} out of 5").format(count, flt(detail.get("rating"), 1)) if count else _("No review yet")
		)
	else:
		message = _("Videos: {0}").format(count) if count else _("No video")
	return {"code": row.code, "label": criterion_label(row.code), "message": message}


# ---------------------------------------------------------------------------------------------
# Every night: the whole catalogue, and one snapshot per site


def refresh_all():
	"""Every product the shop shows, scored on each site that shows it, then one snapshot per site
	for the charts. The item keeps the score score_item() would give it: the first site with a feed
	that shows it, the main site first. The scheduler's job, and the patch's."""
	from webshop.webshop.seo.feeds import google

	stored, stored_with_feed, written = set(), set(), 0
	for site in scoring_sites():
		totals = frappe._dict(products=0, scores=0, sent=0, missing={})
		try:
			with google.serving(site):
				context = site_context()
				for name in google.feed_candidates():
					doc = frappe.get_cached_doc("Website Item", name)
					try:
						result = product_score(doc, context)
					except Exception:
						frappe.log_error(f"SEO score: {doc.item_code} failed", frappe.get_traceback())
						continue
					count(totals, result)
					if name in stored_with_feed or (context.refusal and name in stored):
						continue
					store(name, result, site.key)
					stored.add(name)
					if not context.refusal:
						stored_with_feed.add(name)
					written += 1
					if written % COMMIT_EVERY == 0:
						frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
		except Exception:
			frappe.log_error(f"SEO score: site {site.key} failed", frappe.get_traceback())
			continue
		write_snapshot(site.key, totals)
	frappe.db.delete("Webshop SEO Snapshot", {"date": ("<", add_days(nowdate(), -SNAPSHOT_DAYS))})


def count(totals, result):
	if result.score is None:
		return
	totals.products += 1
	totals.scores += result.score
	totals.sent += 1 if result.sent else 0
	for code in result.missing:
		totals.missing[code] = totals.missing.get(code, 0) + 1


def write_snapshot(site_key: str, totals):
	"""The day's figures of a site: one row per site and day, rewritten when the job runs again."""
	values = {
		"products": totals.products,
		"average_score": flt(totals.scores / totals.products, 1) if totals.products else 0,
		"sent_to_google": totals.sent,
		"without_long_description": totals.missing.get("long_description", 0),
		"without_identifier": totals.missing.get("identifier", 0),
		"without_alt_text": totals.missing.get("alt_text", 0),
	}
	today = nowdate()
	existing = frappe.db.get_value("Webshop SEO Snapshot", {"date": today, "site": site_key}, "name")
	if existing:
		frappe.db.set_value("Webshop SEO Snapshot", existing, values)
		return
	frappe.get_doc({"doctype": "Webshop SEO Snapshot", "date": today, "site": site_key, **values}).insert(
		ignore_permissions=True
	)
