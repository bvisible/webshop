# //// Neoffice — added file (no upstream equivalent).
"""The pictures of a product sheet: read from the site's public files, rebuilt small, embedded in the page.

A PDF engine embeds a photograph as it is, so a camera file of 4 MB makes a page of 4 MB: every picture is
rebuilt as a JPEG bounded in size and quality (measured at about 46 KB a product at 700 px, quality 78).
A picture is read only from the site's public files, whatever address a product names: the sheet is built
for a stranger, and the address of a picture is a merchant's text. The pictures travel inside the HTML as
data URIs, so the rendering engine is never asked to fetch anything.
"""

import base64
import io
import os
from urllib.parse import unquote

from PIL import Image, ImageFile, ImageOps

MAX_SOURCE_BYTES = 12 * 1024 * 1024
MAX_SOURCE_PIXELS = 50_000_000
PUBLIC_PREFIX = "/files/"


def encode_jpeg(raw, max_side=900, quality=82):
	"""`raw` as a JPEG no larger than `max_side` on its long side, or None when it is not a picture.

	Transparency is laid on white (a PDF page is white; black would be the default), a palette or a CMYK
	picture is converted, and a photograph taken sideways is turned upright.
	"""
	if not raw or len(raw) > MAX_SOURCE_BYTES:
		return None
	# the process-wide setting Frappe makes (core/doctype/file) forgives a half-sent picture: a merchant's
	# picture that Pillow cannot read whole is left out of the sheet rather than printed with a grey bottom
	forgiving = ImageFile.LOAD_TRUNCATED_IMAGES
	ImageFile.LOAD_TRUNCATED_IMAGES = False
	try:
		with Image.open(io.BytesIO(raw)) as header:
			if header.size[0] * header.size[1] > MAX_SOURCE_PIXELS:
				return None
		with Image.open(io.BytesIO(raw)) as image:
			if image.format == "JPEG":
				# a camera file is decoded at a fraction of its size when far more than needed
				image.draft(None, (max_side, max_side))
			image.load()
			image = ImageOps.exif_transpose(image)
			if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
				image = image.convert("RGBA")
				flat = Image.new("RGB", image.size, (255, 255, 255))
				flat.paste(image, mask=image.getchannel("A"))
				image = flat
			else:
				image = image.convert("RGB")
			image.thumbnail((max_side, max_side))
			out = io.BytesIO()
			image.save(out, "JPEG", quality=quality, optimize=True)
			return out.getvalue()
	except Exception:
		return None
	finally:
		ImageFile.LOAD_TRUNCATED_IMAGES = forgiving


def data_uri(content, mime="image/jpeg"):
	return f"data:{mime};base64," + base64.b64encode(content).decode("ascii")


def public_file_path(url, public_root):
	"""The path of a public file of the site, or None for anything else.

	Only `/files/…` is read. The address is decoded first (a `%2e%2e` is a `..`), then resolved: what ends
	up outside `<public>/files` — a parent folder, a private file, another scheme, another host — is refused.
	"""
	if not isinstance(url, str) or not url.startswith(PUBLIC_PREFIX) or url.startswith("//"):
		return None
	decoded = unquote(url)
	if "\x00" in decoded or not decoded.startswith(PUBLIC_PREFIX) or decoded == PUBLIC_PREFIX:
		return None
	# both sides normalised alike: the site's folder may come as "./shop.local/public" (frappe.get_site_path)
	# and normpath drops the "./" from the path it is compared with
	public_root = os.path.normpath(public_root)
	files_root = os.path.join(public_root, "files")
	path = os.path.normpath(os.path.join(public_root, decoded.lstrip("/")))
	if not path.startswith(files_root + os.sep):
		return None
	return path


def smaller_copy(url, max_side):
	"""The address of the shop's own WebP copy of a picture (`utils/renditions.py`) when it has one at least
	`max_side` wide, else `url`: a catalogue of three hundred products decodes a 800 px file, not a 4000 px one."""
	from webshop.webshop.utils import renditions

	name = renditions.source_name(url)
	if not name:
		return url
	for width in renditions.WIDTHS:
		if width >= max_side and os.path.isfile(renditions.rendition_path(name, width)):
			return renditions.rendition_url(name, width)
	return url


def site_picture(url, max_side=900, quality=82, small_copy=False):
	"""A product's picture, from the site's public files, as a JPEG data URI — or None.

	`small_copy` reads the shop's WebP copy of the picture when there is one wide enough (see `smaller_copy`)."""
	import frappe

	if small_copy:
		url = smaller_copy(url, max_side)
	path = public_file_path(url, frappe.get_site_path("public"))
	if not path or not os.path.isfile(path):
		return None
	try:
		with open(path, "rb") as handle:
			raw = handle.read(MAX_SOURCE_BYTES + 1)
	except OSError:
		return None
	jpeg = encode_jpeg(raw, max_side=max_side, quality=quality)
	return data_uri(jpeg) if jpeg else None
