# //// Neoffice — added file (no upstream equivalent).
"""A table of products as a file: CSV and JSON for another system, Excel for a person.

The three read the same lines (`rows.build_rows`), and the CSV and the JSON the same keys in the same order:
the machine names of `rows.columns_for`, English and stable whatever the language of the reseller, because a
script or a shop's importer matches on them. Only Excel is worded for a person (translated headers, "In
stock", "Yes").

- **Figures stay figures.** A price is a number in JSON and in Excel (two decimals shown, more kept when the
  price has more), and a dot-decimal text in CSV.
- **A text that starts like a formula stays text in Excel.** openpyxl turns a string that starts with "="
  into a formula; every text cell is set to a string, so a product named "=1+1" is a product. The CSV is left
  as it is: it is for another system, which matches on what is written, and an apostrophe added to a name
  would be imported with it.
- **The CSV has no byte-order mark** and ends its lines with CRLF (RFC 4180); to read a file in a
  spreadsheet, the page offers Excel.
"""

import csv
import html
import io
import json
import re
import unicodedata
from xml.etree import ElementTree as ET

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

PRICE_KEYS = ("price", "purchase_price")
MAX_WIDTH = 60
SAMPLE = 200  # lines read to size a column


def amount_text(value):
	"""A price as text, a dot, at least two decimals and as many more as it has (up to four): 80.00, 0.125."""
	whole, _dot, decimals = f"{float(value):.4f}".partition(".")
	return f"{whole}.{decimals.rstrip('0').ljust(2, '0')}"


def attributes_text(attributes):
	return "; ".join(f"{name}: {value}" for name, value in (attributes or {}).items())


def _csv_cell(key, value):
	if value is None:
		return ""
	if isinstance(value, bool):
		return "true" if value else "false"
	if isinstance(value, (int, float)):
		return amount_text(value)
	if key == "attributes":
		return attributes_text(value)
	if key == "more_images":
		return ",".join(value or [])
	return str(value)


def csv_bytes(data):
	"""The CSV: a header of machine names, one record per line."""
	out = io.StringIO(newline="")
	writer = csv.writer(out, lineterminator="\r\n")
	writer.writerow(data.columns)
	for line in data.rows:
		writer.writerow([_csv_cell(key, line.get(key)) for key in data.columns])
	return out.getvalue().encode("utf-8")


def json_bytes(data, generated_on=None):
	"""The JSON: the file's own facts, then one object per line with the keys of the CSV's columns."""
	products = []
	for line in data.rows:
		product = {}
		for key in data.columns:
			value = line.get(key)
			if key in PRICE_KEYS and value is not None:
				value = round(float(value), 4)
			product[key] = value
		products.append(product)
	document = {
		"generated_on": generated_on,
		"currency": data.currency if data.prices != "none" else None,
		"prices_as_of": data.prices_as_of,
		"count": len(products),
		"products": products,
	}
	return json.dumps(document, ensure_ascii=False, indent=1).encode("utf-8")


# --- Shopify ------------------------------------------------------------------------------------
# The columns of Shopify's product import (a subset of its template: the importer reads what it finds). Not the machine
# names of the other files: Shopify matches on these exact words.
SHOPIFY_COLUMNS = [
	"Handle", "Title", "Body (HTML)", "Vendor", "Product Category", "Type", "Tags", "Published",
	"Option1 Name", "Option1 Value", "Option2 Name", "Option2 Value", "Option3 Name", "Option3 Value",
	"Variant SKU", "Variant Grams", "Variant Inventory Tracker", "Variant Inventory Qty", "Variant Inventory Policy",
	"Variant Fulfillment Service", "Variant Price", "Variant Compare At Price", "Variant Requires Shipping",
	"Variant Taxable", "Variant Barcode", "Image Src", "Image Position", "Image Alt Text", "Gift Card", "SEO Title",
	"SEO Description", "Variant Image", "Variant Weight Unit", "Cost per item", "Status",
]  # fmt: skip
SHOPIFY_OPTIONS = 3  # a Shopify product has at most three options
SHOPIFY_IMAGES = 10


def shopify_handle(text):
	"""A Shopify handle: lower-case letters, digits and hyphens, from a title that may carry accents."""
	ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
	return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-") or "product"


def _shopify_options(lines):
	"""[(name, [value of each line])] of at most three options: what a model's variants are told apart by. Past the
	third, the others share it ("Size / Fit"), so that nothing a customer chooses by is lost."""
	names = []
	for line in lines:
		for name in line.get("attributes") or {}:
			if name not in names:
				names.append(name)
	if not names:
		return [("Title", ["Default Title"] * len(lines))]
	kept = names[: SHOPIFY_OPTIONS - 1]
	options = [(name, [(line.get("attributes") or {}).get(name, "") for line in lines]) for name in kept]
	rest = names[SHOPIFY_OPTIONS - 1 :]
	options.append(
		(
			" / ".join(rest),
			[" / ".join(str((line.get("attributes") or {}).get(name, "")) for name in rest) for line in lines],
		)
	)
	return options


def shopify_bytes(data):
	"""A Shopify product import file: one product for a model with its variants as lines under it, or for a plain product.

	The same lines as the other files (`rows.build_rows`, in the mode `customers` or `both`): a variant's price is the
	reseller's selling price, and what they pay goes to Shopify's own "Cost per item" column. **A line with no selling
	price is left out**: Shopify refuses a variant with no price, and a price of 0 would sell it for nothing.
	Stock is not tracked (the shop does not tell a quantity to a file). Not tested against a live import."""
	groups, order = {}, []
	for line in data.rows:
		if line.get("price") is None:
			continue
		key = line.get("model") or line["code"]
		if key not in groups:
			groups[key] = []
			order.append(key)
		groups[key].append(line)

	out = io.StringIO(newline="")
	writer = csv.DictWriter(out, fieldnames=SHOPIFY_COLUMNS, lineterminator="\r\n", restval="")
	writer.writeheader()
	handles = set()
	for key in order:
		lines = groups[key]
		first = lines[0]
		title = first.get("model_name") or first["name"]
		handle = shopify_handle(title)
		if handle in handles:
			handle = shopify_handle(f"{title} {key}")
		base, number = handle, 2
		while handle in handles:
			handle, number = f"{base}-{number}", number + 1
		handles.add(handle)

		options = _shopify_options(lines)
		images = []
		for url in [line.get("image") for line in lines] + list(first.get("more_images") or []):
			if url and url not in images:
				images.append(url)
		images = images[:SHOPIFY_IMAGES]
		path = [part for part in (first.get("category") or "").split(" > ") if part]
		for index, line in enumerate(lines):
			row = {"Handle": handle}
			if index == 0:
				row.update(
					{
						"Title": title,
						"Body (HTML)": f"<p>{html.escape(first.get('description') or '')}</p>" if first.get("description") else "",
						"Vendor": first.get("brand") or "",
						"Type": path[-1] if path else "",
						"Tags": ", ".join(path),
						"Published": "TRUE",
						"Gift Card": "FALSE",
						"SEO Title": title,
						"Status": "active",
						"Image Src": images[0] if images else "",
						"Image Position": 1 if images else "",
						"Image Alt Text": title if images else "",
					}
				)
			for number, (name, values) in enumerate(options, start=1):
				if index == 0:
					row[f"Option{number} Name"] = name
				row[f"Option{number} Value"] = values[index]
			row.update(
				{
					"Variant SKU": line["code"],
					"Variant Grams": 0,
					"Variant Inventory Policy": "deny",
					"Variant Fulfillment Service": "manual",
					"Variant Price": amount_text(line["price"]),
					"Variant Requires Shipping": "TRUE",
					"Variant Taxable": "TRUE",
					"Variant Barcode": line.get("ean") or "",
					"Variant Weight Unit": "kg",
					"Cost per item": amount_text(line["purchase_price"]) if line.get("purchase_price") is not None else "",
				}
			)
			writer.writerow(row)
		# the other pictures are rows of their own under the product, in Shopify's way
		for position, url in enumerate(images[1:], start=2):
			writer.writerow({"Handle": handle, "Image Src": url, "Image Position": position, "Image Alt Text": title})
	return out.getvalue().encode("utf-8")


# --- Google Shopping -----------------------------------------------------------------------------
GOOGLE_NS = "http://base.google.com/ns/1.0"
GOOGLE_AVAILABILITY = {"in_stock": "in stock", "out_of_stock": "out of stock", "backorder": "backorder"}
GOOGLE_CONDITION = {"new": "new", "refurbished": "refurbished", "second_hand": "used"}
GOOGLE_IMAGES = 10


def google_bytes(data, channel_title, website=""):
	"""A Google Merchant Center product feed (RSS 2.0 with the `g:` namespace) of the lines, at the reseller's selling
	prices. **Never made without a selling price**: the caller only asks for it in the mode `customers`.

	A line with no selling price or no page address is left out (Google refuses both). The page address is the one the
	shop gives the product: a reseller whose own shop reads this feed puts their own page in its place."""
	ET.register_namespace("g", GOOGLE_NS)
	rss = ET.Element("rss", {"version": "2.0"})
	channel = ET.SubElement(rss, "channel")
	ET.SubElement(channel, "title").text = _sheet_text(channel_title or "Products")
	ET.SubElement(channel, "link").text = website if (website or "").startswith(("http://", "https://")) else (f"https://{website}" if website else "")
	ET.SubElement(channel, "description").text = _sheet_text(channel_title or "Products")

	def g(item, name, text):
		if text not in (None, ""):
			ET.SubElement(item, f"{{{GOOGLE_NS}}}{name}").text = _sheet_text(str(text))

	for line in data.rows:
		if line.get("price") is None or not line.get("url"):
			continue
		item = ET.SubElement(channel, "item")
		g(item, "id", line["code"])
		ET.SubElement(item, "title").text = _sheet_text(line["name"][:150])
		ET.SubElement(item, "description").text = _sheet_text((line.get("description") or line["name"])[:5000])
		ET.SubElement(item, "link").text = _sheet_text(line["url"])
		g(item, "image_link", line.get("image"))
		for url in (line.get("more_images") or [])[:GOOGLE_IMAGES]:
			g(item, "additional_image_link", url)
		g(item, "availability", GOOGLE_AVAILABILITY.get(line.get("availability"), "out of stock"))
		g(item, "price", f"{amount_text(line['price'])} {data.currency}")
		g(item, "condition", GOOGLE_CONDITION.get(line.get("condition"), "new"))
		g(item, "brand", line.get("brand"))
		g(item, "gtin", line.get("ean"))
		g(item, "mpn", line.get("mpn"))
		g(item, "item_group_id", line.get("model"))
		g(item, "product_type", line.get("category"))
	return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def _sheet_text(text):
	"""A control character (a vertical tab pasted from Word) makes openpyxl refuse the whole workbook; it prints
	nothing, so it goes."""
	return ILLEGAL_CHARACTERS_RE.sub("", text)


def _excel_value(key, value, labels):
	if value is None:
		return None
	if isinstance(value, bool):
		return labels["yes"] if value else labels["no"]
	if isinstance(value, (int, float)):
		return float(value)
	if key == "attributes":
		return _sheet_text(attributes_text(value))
	if key == "more_images":
		return _sheet_text("\n".join(value or []))
	if key == "availability":
		return labels["availability"].get(value, value)
	if key == "condition":
		return labels["condition"].get(value, value)
	return _sheet_text(str(value))


def _as_text(cells):
	"""Every string cell is a string for Excel, whatever it starts with."""
	for cell in cells:
		if isinstance(cell.value, str):
			cell.data_type = "s"


def xlsx_bytes(data, labels):
	"""The workbook: a sheet of products and a sheet saying what the file is (`labels`: see `rows.labels`)."""
	workbook = Workbook()
	sheet = workbook.active
	sheet.title = labels["products"]
	sheet.append([labels["columns"].get(key, key) for key in data.columns])
	for cell in sheet[1]:
		cell.font = Font(bold=True)
		cell.fill = PatternFill("solid", fgColor="EFE9DD")
		cell.alignment = Alignment(vertical="center")
	for line in data.rows:
		sheet.append([_excel_value(key, line.get(key), labels) for key in data.columns])
		_as_text(sheet[sheet.max_row])
	for index, key in enumerate(data.columns, start=1):
		letter = get_column_letter(index)
		if key in PRICE_KEYS:
			for cell in sheet[letter][1:]:
				cell.number_format = "0.00##"
		longest = max(
			[len(str(sheet.cell(row=1, column=index).value or ""))]
			+ [len(str(cell.value or "").split("\n")[0]) for cell in sheet[letter][1 : SAMPLE + 1]]
		)
		sheet.column_dimensions[letter].width = min(longest + 2, MAX_WIDTH)
		if key in ("description", "more_images"):
			for cell in sheet[letter][1:]:
				cell.alignment = Alignment(wrap_text=True, vertical="top")
	sheet.freeze_panes = "A2"
	sheet.auto_filter.ref = sheet.dimensions

	facts = workbook.create_sheet(labels["information"])
	for label, value in labels["facts"].items():
		facts.append([label, _sheet_text(value) if isinstance(value, str) else value])
		facts.cell(row=facts.max_row, column=1).font = Font(bold=True)
		_as_text(facts[facts.max_row])
	facts.column_dimensions["A"].width = 28
	facts.column_dimensions["B"].width = 60

	out = io.BytesIO()
	workbook.save(out)
	return out.getvalue()
