# //// Neoffice — added file (no upstream equivalent). neoffice-maintenance#691, lot 5.
"""Smaller copies of the shop's pictures, in WebP, at a few fixed widths.

A card showed a 6429 px, 3.5 MB photograph in a 300 px box: on osiris (2026-09-24) the 96
published product pictures weighed 24 MB, eleven of them wider than 1200 px. Every public picture
of the catalogue gets WebP copies at WIDTHS, next to the files and named after the picture:
`/files/wsr/<file name>.<width>w.webp`. A job writes them ahead of time (a Website Item saved, and
the whole catalogue once, from a patch); a copy nobody has written yet is made by the first request
for it (RenditionRenderer: nginx serves a file that exists and hands Frappe the rest). From then
on nginx serves it like any other file.

`webshop_picture(url, layout)` gives an <img> what it needs: `srcset` with the copies narrower than
the picture (the picture itself too when it is no wider than the largest copy), the `sizes` of the
layout it sits in, and the picture's width and height. A picture that is not a public raster file
of this site keeps its plain `src`: an external address, an SVG, a GIF (it may be animated).
The `src` stays the original — what a crawler or an old browser fetches, and what the product's
structured data names."""

import os
import re
import tempfile
from urllib.parse import quote

import frappe
from frappe.website.page_renderers.base_renderer import BaseRenderer
from werkzeug.wrappers import Response

WIDTHS = (400, 800, 1200, 1600)
FOLDER = "wsr"
SOURCE_EXTENSIONS = ("jpg", "jpeg", "png", "webp")
QUALITY = 80
SIZE_CACHE = "webshop:picture_size"
RENDITION_PATH = re.compile(r"^/?files/" + FOLDER + r"/(?P<name>[^/]+)\.(?P<width>\d+)w\.webp$")
# Rotations stored in a photograph's EXIF orientation: its stored width is its displayed height
QUARTER_TURNS = (5, 6, 7, 8)
EXIF_ORIENTATION = 0x0112

# How wide each place draws a picture, for the browser to pick a copy before it lays the page out
# (the grids of webshop_catalogue.scss and webshop_product_card.scss, the gallery of
# webshop_product_gallery.scss). An estimate is enough: the browser takes the smallest copy at
# least that wide, times the screen's density.
SIZES = {
	# four columns from 1200 px beside the filters, three from 768 px, two on a phone
	"grid": "(min-width: 1200px) 320px, (min-width: 768px) 33vw, 50vw",
	"wishlist": "(min-width: 1200px) 320px, (min-width: 768px) 33vw, 50vw",
	# two cards and a half on a phone, three or four beyond
	"carousel": "(min-width: 1200px) 300px, (min-width: 768px) 33vw, 45vw",
	# the list view's picture column (col-2)
	"list": "(min-width: 768px) 17vw, 33vw",
	# the product page: the picture column is 60 % of the container from 768 px, the screen's
	# width below; the container stops growing around 1300 px
	"gallery": "(min-width: 1300px) 800px, (min-width: 768px) 60vw, 100vw",
	# the mosaic's two large tiles share that column, its small ones take a third of it
	"gallery_large": "(min-width: 1300px) 400px, (min-width: 768px) 30vw, 100vw",
	"gallery_small": "(min-width: 1300px) 260px, (min-width: 768px) 20vw, 50vw",
	# the rail's thumbnails
	"thumb": "72px",
}


def source_name(url):
	"""The file name of a public raster picture of this site, or None."""
	if not isinstance(url, str) or not url.startswith("/files/"):
		return None
	name = url[len("/files/") :]
	if not name or "/" in name or "\\" in name or name.startswith(".") or "?" in name or "#" in name:
		return None
	if name.rsplit(".", 1)[-1].lower() not in SOURCE_EXTENSIONS:
		return None
	return name


def source_path(name):
	return frappe.get_site_path("public", "files", name)


def rendition_url(name, width):
	return f"/files/{FOLDER}/{name}.{width}w.webp"


def rendition_path(name, width):
	return frappe.get_site_path("public", "files", FOLDER, f"{name}.{width}w.webp")


def picture_size(url):
	"""(width, height) of a public picture as a browser shows it, or None. Read from the file's
	header once, then kept: file names are unique, and on_file_trash forgets a deleted one."""
	name = source_name(url)
	if not name:
		return None
	cache = frappe.cache()
	known = cache.hget(SIZE_CACHE, name)
	if known:
		return tuple(known)
	path = source_path(name)
	if not os.path.isfile(path):
		return None
	try:
		from PIL import Image

		with Image.open(path) as image:
			width, height = image.size
			if image.getexif().get(EXIF_ORIENTATION) in QUARTER_TURNS:
				width, height = height, width
	except Exception:
		return None
	cache.hset(SIZE_CACHE, name, [width, height])
	return width, height


def webshop_picture(url, layout="grid"):
	"""What an <img> of `layout` (a key of SIZES) needs: src, srcset, sizes, width, height."""
	out = frappe._dict(src=url, srcset="", sizes="", width=None, height=None)
	size = picture_size(url)
	if not size:
		return out
	name = source_name(url)
	width, height = size
	candidates = [f"{quote(rendition_url(name, w))} {w}w" for w in WIDTHS if w < width]
	if candidates:
		if width <= WIDTHS[-1]:
			candidates.append(f"{quote(url)} {width}w")
		out.srcset = ", ".join(candidates)
		out.sizes = SIZES.get(layout) or SIZES["grid"]
	out.width, out.height = width, height
	return out


def make_rendition(name, width):
	"""Write the copy of the picture `name` at `width` and return its path, or None when there is
	nothing to write (not one of WIDTHS, no such picture, not wider than `width`). It goes through
	a temporary file: nginx never serves half a picture."""
	source = source_path(name)
	if width not in WIDTHS or not source_name("/files/" + name) or not os.path.isfile(source):
		return None
	target = rendition_path(name, width)
	if os.path.isfile(target) and os.path.getmtime(target) >= os.path.getmtime(source):
		return target
	from PIL import Image, ImageOps

	with Image.open(source) as image:
		# a phone stores a portrait photograph on its side and says so in its EXIF
		turned = image.getexif().get(EXIF_ORIENTATION) in QUARTER_TURNS
		if (image.height if turned else image.width) <= width:
			return None
		if image.format == "JPEG":
			# decode at a fraction of the size when the copy is much smaller: a 6000 px photograph
			# costs a quarter of the time. Both sides stay at least `width`, whichever way it turns.
			image.draft(image.mode, (width, width))
		picture = ImageOps.exif_transpose(image)
		if picture.mode not in ("RGB", "RGBA"):
			transparent = picture.mode in ("RGBA", "LA", "PA") or "transparency" in picture.info
			picture = picture.convert("RGBA" if transparent else "RGB")
		copy = picture.resize((width, max(1, round(picture.height * width / picture.width))), Image.LANCZOS)
	os.makedirs(os.path.dirname(target), exist_ok=True)
	handle, temporary = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".", suffix=".tmp")
	os.close(handle)
	try:
		copy.save(temporary, "WEBP", quality=QUALITY, method=4)
		os.replace(temporary, target)
	finally:
		if os.path.exists(temporary):
			os.remove(temporary)
	return target


def make_renditions(urls):
	"""Every copy of these pictures that is missing (a job)."""
	for url in dict.fromkeys(urls or []):
		name = source_name(url)
		size = picture_size(url)
		if not name or not size:
			continue
		for width in WIDTHS:
			if width >= size[0]:
				break
			try:
				make_rendition(name, width)
			except Exception:
				frappe.log_error("Picture copy failed", f"{url} at {width} px\n\n{frappe.get_traceback()}")
				break


def item_pictures(doc):
	"""The pictures a Website Item shows: its own, and its slideshow's (the gallery, the hover)."""
	urls = [doc.get("website_image")]
	if doc.get("slideshow"):
		urls += frappe.get_all(
			"Website Slideshow Item", filters={"parent": doc.slideshow}, pluck="image", order_by="idx"
		)
	return [url for url in urls if source_name(url)]


def on_website_item_update(doc, method=None):
	"""A saved Website Item has its copies written in the background, before a visitor asks."""
	urls = item_pictures(doc)
	if urls and doc.get("published"):
		frappe.enqueue(
			"webshop.webshop.utils.renditions.make_renditions",
			urls=urls,
			queue="default",
			job_id=f"webshop-renditions-{doc.name}",
			deduplicate=True,
			enqueue_after_commit=True,
		)


CATALOGUE_CHUNK = 100


def enqueue_catalogue_renditions():
	"""Every published picture of the catalogue, in jobs of CATALOGUE_CHUNK pictures (the patch)."""
	urls = []
	for item in frappe.get_all("Website Item", filters={"published": 1}, fields=["website_image", "slideshow"]):
		urls += item_pictures(item)
	urls = list(dict.fromkeys(urls))
	for start in range(0, len(urls), CATALOGUE_CHUNK):
		frappe.enqueue(
			"webshop.webshop.utils.renditions.make_renditions",
			urls=urls[start : start + CATALOGUE_CHUNK],
			queue="long",
			timeout=1800,
		)
	return len(urls)


def on_file_trash(doc, method=None):
	"""A deleted picture takes its copies with it, and its size out of the cache."""
	name = None if doc.get("is_private") else source_name(doc.get("file_url"))
	if not name:
		return
	for width in WIDTHS:
		path = rendition_path(name, width)
		if os.path.isfile(path):
			os.remove(path)
	frappe.cache().hdel(SIZE_CACHE, name)


class RenditionRenderer(BaseRenderer):
	"""A copy nobody has written yet, at its first request: nginx serves the ones that exist."""

	def match(self):
		found = RENDITION_PATH.match(self.path or "")
		if not found:
			return None
		name, width = found["name"], int(found["width"])
		size = picture_size("/files/" + name)
		if not size or width not in WIDTHS or width >= size[0]:
			return None
		return name, width

	def can_render(self):
		return bool(self.match())

	def render(self):
		name, width = self.match()
		path = make_rendition(name, width)
		if not path:
			raise frappe.PageDoesNotExistError
		# the path is built from a name source_name() accepted (a public file's own name: no "/",
		# no "..") and a width of WIDTHS, both checked by match()
		with open(path, "rb") as handle:  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-security-file-traversal
			response = Response(handle.read(), mimetype="image/webp")
		# a day: the address follows the picture's name, not its content
		response.headers["Cache-Control"] = "public, max-age=86400"
		return response
