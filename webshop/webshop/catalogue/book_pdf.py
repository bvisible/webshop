# //// Neoffice — added file (no upstream equivalent).
"""A catalogue's PDF: the document's HTML, and two renders so that its contents says on which page each section is.

Chromium does not know `target-counter()`, so it cannot number a table of contents by itself. What it does
write is the PDF's bookmarks (`generateDocumentOutline`), taken from the document's headings. So: render once
with a placeholder of fixed width where each page number goes, read the bookmarks to learn the page of each
section, put the real numbers where the placeholders were, and render again. The numbers have the same width as
the placeholders, so the second render paginates exactly as the first (checked: a different count of pages is
logged, and the first render's numbers are then not trusted).

Only the sections' titles are headings (`h2`), apart from the cover's own `h1`: the bookmarks are the document's
sections, not its three hundred products.
"""

import io

import frappe

from webshop.webshop.catalogue import brand
from webshop.webshop.catalogue.pdf import render_pdf
from webshop.webshop.catalogue.sheet import DEFAULT_COLOUR, css_string

MAX_PAGES = 400


def page_css(book):
	"""The stylesheet: the file, the reseller's colour, and the page boxes with their footer."""
	with open(frappe.get_app_path("webshop", "templates", "catalogue", "catalogue.css"), encoding="utf-8") as handle:
		base = handle.read()
	colour = book.issuer.colour if brand.is_colour(book.issuer.colour) else DEFAULT_COLOUR
	footer = css_string(book.issuer.name)
	font = '7.5pt "Helvetica Neue", Arial, sans-serif'
	page = (
		"@page { size: A4; margin: 16mm 14mm 20mm 14mm; "
		f'@bottom-left {{ content: "{footer}"; font: {font}; color: #7b8794; }} '
		f'@bottom-right {{ content: counter(page) " / " counter(pages); font: {font}; color: #7b8794; }} }}\n'
		# the cover is the first page and has no margin, no footer
		"@page :first { margin: 0; @bottom-left { content: none; } @bottom-right { content: none; } }"
	)
	return f":root {{ --brand: {colour}; --on-brand: {brand.readable_ink(colour)}; }}\n{base}\n{page}\n"


def render_html(book, numbers=None, show_numbers=True):
	"""The document. `numbers` is the page of each section (a list, in order); without it the contents carries a
	placeholder of the same width, or nothing at all when `show_numbers` is False."""
	return frappe.render_template(
		"templates/catalogue/catalogue.html",
		{"book": book, "css": page_css(book), "numbers": numbers, "show_numbers": show_numbers},
	)


def _normal(text):
	return " ".join((text or "").split())


def read_outline(pdf):
	"""[(title, page)] for every bookmark of the PDF, in document order, pages counted from 1; and the page count."""
	from pypdf import PdfReader

	reader = PdfReader(io.BytesIO(pdf))
	entries = []

	def walk(nodes):
		for node in nodes:
			if isinstance(node, list):
				walk(node)
			else:
				entries.append((node.title, reader.get_destination_page_number(node) + 1))

	walk(reader.outline)
	return entries, len(reader.pages)


def section_pages(entries, cover_title, titles):
	"""The page of each section title, in order, or None when the bookmarks do not say.

	The cover's own title is the first bookmark and is set aside first: a section may carry the same words. The
	rest is matched in order, so two sections with one title each get their own page."""
	entries = list(entries)
	if entries and _normal(entries[0][0]) == _normal(cover_title):
		entries = entries[1:]
	pages, wanted = [], 0
	for title, page in entries:
		if wanted < len(titles) and _normal(title) == _normal(titles[wanted]):
			pages.append(page)
			wanted += 1
	return pages if wanted == len(titles) else None


def make_pdf(book, progress=None):
	"""(the PDF, its page count). `progress(stage, done, total)` is told "render" 1 of 2, then 2 of 2."""
	titles = [section.title for section in book.sections]
	first = render_pdf(render_html(book))
	if progress:
		progress("render", 1, 2)
	entries, pages = read_outline(first)
	numbers = section_pages(entries, book.title, titles)
	if numbers is None:
		# the contents then goes without numbers rather than with wrong ones
		frappe.log_error(
			"Catalogue contents: bookmarks unreadable",
			f"{len(entries)} bookmarks for {len(titles)} sections in a catalogue of {pages} pages",
		)
		second = render_pdf(render_html(book, show_numbers=False))
	else:
		second = render_pdf(render_html(book, numbers=numbers))
	if progress:
		progress("render", 2, 2)
	_entries, final_pages = read_outline(second)
	if numbers is not None and final_pages != pages:
		frappe.log_error(
			"Catalogue contents: the second render paginated differently",
			f"{pages} pages, then {final_pages}: the numbers of the contents may be off",
		)
	return second, final_pages
