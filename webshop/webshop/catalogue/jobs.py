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

from webshop.webshop.catalogue import book, book_pdf, rows, selection, tables
from webshop.webshop.catalogue import api as brand_api
from webshop.webshop.catalogue.pdf import chromium_available
from webshop.webshop.catalogue.refusals import catalogue_message
from webshop.webshop.catalogue.sheet_api import _filename
from webshop.webshop.doctype.reseller_catalogue.reseller_catalogue import (
	CSV,
	FAILED,
	PDF,
	QUEUED,
	READY,
	RUNNING,
	XLSX,
)

DOCTYPE = "Reseller Catalogue"
KEEP_DAYS = 30
DAILY_LIMIT = 10  # catalogues one customer may ask for in 24 hours
JOB_TIMEOUT = 1500  # seconds: the long queue's own limit is 1500
STALLED_MINUTES = 40  # a catalogue Queued or Running for longer lost its worker: it blocks nobody and is closed
# the share of the progress bar each stage covers: prices dominate, then the pictures, then the two renders
STAGES = {"prices": (2, 45), "pictures": (45, 75), "render": (75, 98)}
# a table of products has no pictures to prepare and nothing to lay out: the prices are nearly all of it
TABLE_STAGES = {"prices": (2, 92), "file": (92, 98)}
NUMBERS = {
	"too_many_products": selection.MAX_PRODUCTS,
	"too_many_pages": book_pdf.MAX_PAGES,
	"too_many_rows": rows.MAX_ROWS,
}
EXTENSIONS = {PDF: "pdf", XLSX: "xlsx", CSV: "csv"}


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


def reporter(name, stages=STAGES, setter=None):
	"""progress(stage, done, total) for the builders: the bar moves when a figure changes, not on every product.
	`setter(name, **values)` writes it (the catalogue's `_set`, or the feed's)."""
	last = {"percent": -1, "stage": None}
	write = setter or _set

	def report(stage, done, total):
		low, high = stages.get(stage, (0, 100))
		percent = int(low + (high - low) * (done / total if total else 1))
		if percent != last["percent"] or stage != last["stage"]:
			last.update(percent=percent, stage=stage)
			write(name, progress=percent, stage=stage)

	return report


def pin_site(doc):
	"""Compute on the site the catalogue was asked on: a job has no request, so no profile, so the default list."""
	profile = doc.get("website_profile")
	if not profile or not frappe.db.exists("DocType", "Website Profile") or not frappe.db.exists("Website Profile", profile):
		return
	frappe.local.website_profile = profile
	frappe.local.website_profile_doc = frappe.get_doc("Website Profile", profile).as_dict()


def _make_pdf(doc, payload, clean):
	"""(content, file name, products, pages) of a PDF catalogue."""
	if not chromium_available():
		raise book.CatalogueRefused("no_engine")
	options = book.clean_options(json.loads(doc.options or "{}"), payload["values"]["default_markup_percent"])
	report = reporter(doc.name)
	data = book.build_book(doc.customer, payload, payload["credit_line"], doc.title, clean, options, report)
	pdf, pages = book_pdf.make_pdf(data, report)
	if pages > book_pdf.MAX_PAGES:
		raise book.CatalogueRefused("too_many_pages")
	return pdf, _filename(doc.title), data.product_count, pages


def _make_table(doc, payload, clean, fmt):
	"""(content, file name, lines, no pages) of a workbook or a CSV file."""
	options = rows.clean_options(json.loads(doc.options or "{}"), payload["values"]["default_markup_percent"])
	report = reporter(doc.name, TABLE_STAGES)
	data = rows.build_rows(doc.customer, payload, clean, options, report)
	report("file", 0, 1)
	if fmt == XLSX:
		issuer = payload["values"].get("brand_name") or ""
		content = tables.xlsx_bytes(data, rows.labels(data, doc.title, issuer))
	else:
		content = tables.csv_bytes(data)
	return content, _filename(doc.title, EXTENSIONS[fmt], "catalogue"), len(data.rows), None


def generate(catalogue):
	"""Make the catalogue named `catalogue`. Does nothing for one that is not waiting for it."""
	doc = frappe.get_doc(DOCTYPE, catalogue)
	if doc.status != QUEUED:
		return
	_set(catalogue, status=RUNNING, progress=1, stage="start", error="")
	try:
		frappe.set_user_lang(doc.owner)
		pin_site(doc)
		payload = brand_api._payload(doc.customer)
		clean = selection.clean_selection(doc.selection)
		fmt = doc.get("format") or PDF
		if fmt == PDF:
			content, name, count, pages = _make_pdf(doc, payload, clean)
		else:
			content, name, count, pages = _make_table(doc, payload, clean, fmt)
		file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": name,
				"attached_to_doctype": DOCTYPE,
				"attached_to_name": catalogue,
				"attached_to_field": "file",
				"is_private": 1,
				"content": content,
			}
		).insert(ignore_permissions=True)
		_set(
			catalogue,
			status=READY,
			progress=100,
			stage="",
			file=file.file_url,
			item_count=count,
			page_count=pages or 0,
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
