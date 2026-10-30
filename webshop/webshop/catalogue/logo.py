# //// Neoffice — added file (no upstream equivalent).
"""A reseller's logo: the one input of the catalogue that is a file, not text.

Whatever a customer uploads is opened by Pillow and rebuilt as a PNG from its pixels alone. What the
file carried besides them (EXIF, text chunks, a profile, anything appended) does not survive, and
what is not a PNG or a JPEG is refused: an SVG can hold a script and point at other files, which a
browser rendering a catalogue would fetch. The size and the pixel count are bounded before the
image is decoded, so a few kilobytes that unpack into gigabytes are turned away at the header.
"""

import io

from PIL import Image, ImageFile, ImageOps

MAX_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 25_000_000
MAX_SIDE = 800
ALLOWED_FORMATS = ("PNG", "JPEG")


class LogoRefused(ValueError):
	"""The file is not a logo this page accepts. `reason` is a code; the caller words it."""

	def __init__(self, reason):
		super().__init__(reason)
		self.reason = reason


def clean_logo(raw):
	"""`raw` as the PNG that will be kept, or a LogoRefused."""
	# Frappe sets ImageFile.LOAD_TRUNCATED_IMAGES = True for the whole process (core/doctype/file),
	# so that a half-sent photo still gets its thumbnail. Here it would keep a half-sent logo with a
	# grey bottom: the setting is turned off for this one file, then given back as it was.
	forgiving = ImageFile.LOAD_TRUNCATED_IMAGES
	ImageFile.LOAD_TRUNCATED_IMAGES = False
	try:
		return _clean(raw)
	finally:
		ImageFile.LOAD_TRUNCATED_IMAGES = forgiving


def _clean(raw):
	if not raw:
		raise LogoRefused("not_an_image")
	if len(raw) > MAX_BYTES:
		raise LogoRefused("too_large")
	try:
		with Image.open(io.BytesIO(raw)) as header:
			image_format, size = header.format, header.size
		if image_format not in ALLOWED_FORMATS:
			raise LogoRefused("format")
		if size[0] * size[1] > MAX_PIXELS:
			raise LogoRefused("too_many_pixels")
		with Image.open(io.BytesIO(raw)) as image:
			image.load()
			# a photo taken sideways is stored sideways and says so in its EXIF: turn it first
			image = ImageOps.exif_transpose(image)
			transparent = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
			image = image.convert("RGBA" if transparent else "RGB")
			image.thumbnail((MAX_SIDE, MAX_SIDE))
			# a fresh image carries the pixels and nothing else
			clean = Image.new(image.mode, image.size)
			clean.paste(image)
		out = io.BytesIO()
		clean.save(out, "PNG", optimize=True)
		return out.getvalue()
	except LogoRefused:
		raise
	except Exception:
		# a truncated file, bytes that only look like an image, a decoder that gave up
		raise LogoRefused("not_an_image") from None
