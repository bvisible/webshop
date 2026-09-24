# //// Neoffice — added file (no upstream equivalent). Plain text out of the rich text a
# //// merchant writes, for the meta description and the structured data.
"""Rich text to plain text, the way a reader would see it.

`frappe.utils.strip_html` drops the tags and nothing else, so the paragraphs and the list
items of a product description ran into each other in the JSON-LD ("180 g/m²Col rond
côtelé"), and a hard cut at 500 characters stopped in the middle of a word. Search engines
and AI crawlers read exactly that text.
"""

import re
from html import unescape

# Tags after which a reader sees a new line: a paragraph, a list item, a table cell, a heading.
BLOCK_TAGS = r"(?:p|div|br|li|ul|ol|h[1-6]|tr|td|th|table|section|article|blockquote|dd|dt|dl)"


def html_to_text(html, limit=None):
	"""The text of `html`, one line per block, cut at a word boundary under `limit`."""
	if not html:
		return ""
	text = re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", " ", str(html))
	text = re.sub(rf"(?i)<\s*/?\s*{BLOCK_TAGS}\b[^>]*>", "\n", text)
	text = re.sub(r"(?s)<[^>]*>", "", text)
	text = unescape(text).replace("\xa0", " ")
	lines = (" ".join(line.split()) for line in text.splitlines())
	text = "\n".join(line for line in lines if line)
	return truncate(text, limit) if limit else text


def one_line(html, limit=None):
	"""The same text on a single line, for a meta description."""
	text = " ".join(html_to_text(html).split())
	return truncate(text, limit) if limit else text


def truncate(text, limit):
	"""Cut `text` to at most `limit` characters, at a word boundary, with an ellipsis."""
	text = text or ""
	if not limit or len(text) <= limit:
		return text
	cut = text[: max(limit - 1, 1)]
	boundary = max(cut.rfind(" "), cut.rfind("\n"))
	if boundary > limit * 0.6:
		cut = cut[:boundary]
	return cut.rstrip(" ,;:-\n") + "…"
