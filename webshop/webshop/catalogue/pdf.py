# //// Neoffice — added file (no upstream equivalent).
"""HTML to PDF through the Chromium that Frappe's Chrome PDF generator already keeps running.

A product sheet or a catalogue is a document of its own, not a print format: no letterhead merged after the
fact, no margins forced to zero. So this talks to the same shared Chromium (the systemd service, DevTools
on `chromium_remote_debugging_port`) one level below `frappe.utils.pdf_generator.Browser`, with the page
layout left to the document's own `@page` rule (`preferCSSPageSize`).

Every page and every socket opened here is closed, whatever happens: a render that raised once left orphan
tabs and CLOSE-WAIT sockets in the web workers (the incident behind `Browser`'s own try/finally, 2026-09-08).
The HTML handed in must be complete and self-contained — its pictures inline as data URIs: the engine is
never asked to fetch anything, which is also what keeps a stranger's text from making it do so.
"""

import os

import frappe

# `generateDocumentOutline` writes the PDF's bookmarks from the document's headings; the tagged PDF carries
# the reading order for screen readers.
PRINT_PARAMS = {
	"printBackground": True,
	"preferCSSPageSize": True,
	"displayHeaderFooter": False,
	"marginTop": 0,
	"marginBottom": 0,
	"marginLeft": 0,
	"marginRight": 0,
	"generateTaggedPDF": True,
	"generateDocumentOutline": True,
	"transferMode": "ReturnAsStream",
}


class PdfRenderError(RuntimeError):
	"""The engine could not produce the document."""


def chromium_available():
	"""Whether this bench has the Chromium of the Chrome PDF generator, without downloading one.

	A bench that has none (a fresh CI site) would have `ChromePDFGenerator` fetch 170 MB; the tests of the
	rendering skip there, and say so, rather than waiting for a download."""
	if frappe.conf.get("chromium_remote_debugging_port"):
		return True
	return os.path.isdir(os.path.join(frappe.utils.get_bench_path(), "chromium"))


def render_pdf(html):
	"""The PDF of `html`, as bytes."""
	from frappe.utils.pdf_generator.cdp_connection import CDPSocketClient
	from frappe.utils.pdf_generator.chrome_pdf_generator import ChromePDFGenerator
	from frappe.utils.pdf_generator.page import Page

	generator = ChromePDFGenerator()
	browser_id = frappe.generate_hash(length=10)
	generator.add_browser(browser_id)
	session = page = None
	try:
		url = generator.ensure_devtools_url()
		session = CDPSocketClient(url)
		try:
			session.connect()
		except (ConnectionRefusedError, OSError):
			# the shared Chromium may have restarted since the address was read
			session = CDPSocketClient(generator.ensure_devtools_url(force=True))
			session.connect()
		context, error = session.send("Target.createBrowserContext", {"disposeOnDetach": True})
		if error:
			raise PdfRenderError(f"no browser context: {error}")
		page = Page(session, context["browserContextId"], "body")
		page.set_content(html)
		page.wait_for_set_content()
		result, error = page.send("Page.printToPDF", dict(PRINT_PARAMS))
		if error:
			raise PdfRenderError(f"printToPDF: {error}")
		if "stream" not in result:
			raise PdfRenderError("printToPDF returned no stream")
		return page.get_pdf_from_stream(result["stream"], raw=True)
	finally:
		if page:
			try:
				page.close()
			except Exception:
				pass
		if session:
			try:
				session.disconnect()
			except Exception:
				pass
		generator.remove_browser(browser_id)
