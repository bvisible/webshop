# //// Neoffice — added file (no upstream equivalent).
"""The job that makes a catalogue, and the night's cleaning.

A catalogue is never made inside a web request: prices cost about 25 ms a product, so three hundred of them
and two renders are ten to fifteen seconds. The page asks for one (`catalogue_api.create_catalogue`), a record
`Queued` is written and this job takes it: `Running` with a progress the page polls, then `Ready` with a
private PDF attached, or `Failed` with a sentence the reseller can read.

A job starts in English whatever the site speaks (it sets no language): the owner's language is set first, so
the sentence a failure leaves reads in it. The job runs as the reseller (the queue keeps the user who enqueued
it), and prices as THEIR customer on the site they asked on: that site's profile is put back on `frappe.local`
(`website_profile`, which a job has none of) before anything reads a price list.
"""

import json

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, nowdate

from webshop.webshop.catalogue import book, book_pdf, selection
from webshop.webshop.catalogue import api as brand_api
from webshop.webshop.catalogue.pdf import chromium_available
from webshop.webshop.catalogue.refusals import catalogue_message
from webshop.webshop.catalogue.sheet_api import _filename
from webshop.webshop.doctype.reseller_catalogue.reseller_catalogue import FAILED, QUEUED, READY, RUNNING

DOCTYPE = "Reseller Catalogue"
KEEP_DAYS = 30
DAILY_LIMIT = 10  # catalogues one customer may ask for in 24 hours
JOB_TIMEOUT = 1500  # seconds: the long queue's own limit is 1500
STALLED_MINUTES = 40  # a catalogue Queued or Running for longer lost its worker: it blocks nobody and is closed
# the share of the progress bar each stage covers: prices dominate, then the pictures, then the two renders
STAGES = {"prices": (2, 45), "pictures": (45, 75), "render": (75, 98)}
NUMBERS = {"too_many_products": selection.MAX_PRODUCTS, "too_many_pages": book_pdf.MAX_PAGES}


def enqueue_generation(name):
	"""Queue the job once the request that wrote the record has committed."""
	frappe.enqueue(
		"webshop.webshop.catalogue.jobs.generate",
		queue="long",
		timeout=JOB_TIMEOUT,
		enqueue_after_commit=True,
		catalogue=name,
	)


def _set(name, **values):
	"""Write fields of the record without touching `modified`, and commit: the page reads them as they come."""
	frappe.db.set_value(DOCTYPE, name, values, update_modified=False)
	frappe.db.commit()


def _reporter(name):
	"""progress(stage, done, total) for the builders: the bar moves when a figure changes, not on every product."""
	last = {"percent": -1, "stage": None}

	def report(stage, done, total):
		low, high = STAGES.get(stage, (0, 100))
		percent = int(low + (high - low) * (done / total if total else 1))
		if percent != last["percent"] or stage != last["stage"]:
			last.update(percent=percent, stage=stage)
			_set(name, progress=percent, stage=stage)

	return report


def _pin_site(doc):
	"""Compute on the site the catalogue was asked on: a job has no request, so no profile, so the default list."""
	profile = doc.get("website_profile")
	if not profile or not frappe.db.exists("DocType", "Website Profile") or not frappe.db.exists("Website Profile", profile):
		return
	frappe.local.website_profile = profile
	frappe.local.website_profile_doc = frappe.get_doc("Website Profile", profile).as_dict()


def generate(catalogue):
	"""Make the catalogue named `catalogue`. Does nothing for one that is not waiting for it."""
	doc = frappe.get_doc(DOCTYPE, catalogue)
	if doc.status != QUEUED:
		return
	_set(catalogue, status=RUNNING, progress=1, stage="start", error="")
	try:
		frappe.set_user_lang(doc.owner)
		_pin_site(doc)
		if not chromium_available():
			raise book.CatalogueRefused("no_engine")
		payload = brand_api._payload(doc.customer)
		clean = selection.clean_selection(doc.selection)
		options = book.clean_options(json.loads(doc.options or "{}"), payload["values"]["default_markup_percent"])
		data = book.build_book(
			doc.customer, payload, payload["credit_line"], doc.title, clean, options, _reporter(catalogue)
		)
		pdf, pages = book_pdf.make_pdf(data, _reporter(catalogue))
		if pages > book_pdf.MAX_PAGES:
			raise book.CatalogueRefused("too_many_pages")
		file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": _filename(doc.title),
				"attached_to_doctype": DOCTYPE,
				"attached_to_name": catalogue,
				"attached_to_field": "file",
				"is_private": 1,
				"content": pdf,
			}
		).insert(ignore_permissions=True)
		_set(
			catalogue,
			status=READY,
			progress=100,
			stage="",
			file=file.file_url,
			item_count=data.product_count,
			page_count=pages,
			generated_on=now_datetime(),
			prices_as_of=nowdate(),
			expires_on=add_days(nowdate(), KEEP_DAYS),
		)
	except book.CatalogueRefused as refusal:
		frappe.db.rollback()
		_set(catalogue, status=FAILED, error=catalogue_message(refusal.reason, NUMBERS.get(refusal.reason)))
	except Exception:
		frappe.db.rollback()
		frappe.log_error("Reseller catalogue failed", frappe.get_traceback())
		_set(catalogue, status=FAILED, error=catalogue_message("failed"))


def is_running(customer):
	"""Whether this customer has a catalogue being made. One that has been Queued or Running for too long is not
	counted: its worker is gone, and it must not shut its owner out."""
	since = add_to_date(now_datetime(), minutes=-STALLED_MINUTES)
	return bool(
		frappe.db.exists(
			DOCTYPE, {"customer": customer, "status": ["in", [QUEUED, RUNNING]], "creation": [">", since]}
		)
	)


def asked_since(customer, hours=24):
	"""How many catalogues this customer asked for in the last `hours` hours, failed ones included."""
	since = add_to_date(now_datetime(), hours=-hours)
	return frappe.db.count(DOCTYPE, {"customer": customer, "creation": [">", since]})


def purge():
	"""Daily: close what lost its worker, delete what has been kept long enough (the file goes with it)."""
	since = add_to_date(now_datetime(), minutes=-STALLED_MINUTES)
	for name in frappe.get_all(
		DOCTYPE, filters={"status": ["in", [QUEUED, RUNNING]], "creation": ["<", since]}, pluck="name"
	):
		frappe.db.set_value(
			DOCTYPE, name, {"status": FAILED, "error": catalogue_message("stalled"), "stage": ""}, update_modified=False
		)
	for name in frappe.get_all(DOCTYPE, filters={"expires_on": ["<", nowdate()]}, pluck="name"):
		frappe.delete_doc(DOCTYPE, name, ignore_permissions=True, force=True)
	frappe.db.commit()
