# //// Neoffice — added file (no upstream equivalent).
"""What a reseller may upload as a logo, and what comes out of it.

A file sent by a customer is the one piece of input of the catalogue that is not text: it goes through
Pillow, comes out as a PNG built from the pixels alone, and nothing else survives. No site needed.
"""

import io
import unittest

from PIL import Image, ImageFile, PngImagePlugin

from webshop.webshop.catalogue import logo


def _png(size=(120, 40), mode="RGB", colour=(10, 110, 79), **save):
	out = io.BytesIO()
	Image.new(mode, size, colour).save(out, "PNG", **save)
	return out.getvalue()


def _jpeg(size=(120, 40)):
	out = io.BytesIO()
	Image.new("RGB", size, (200, 30, 30)).save(out, "JPEG")
	return out.getvalue()


def _opened(data):
	return Image.open(io.BytesIO(data))


class TestWhatComesOut(unittest.TestCase):
	def test_a_png_comes_out_as_a_png(self):
		with _opened(logo.clean_logo(_png())) as image:
			self.assertEqual(image.format, "PNG")
			self.assertEqual(image.size, (120, 40))

	def test_a_jpeg_comes_out_as_a_png(self):
		with _opened(logo.clean_logo(_jpeg())) as image:
			self.assertEqual(image.format, "PNG")

	def test_transparency_is_kept(self):
		with _opened(logo.clean_logo(_png(mode="RGBA", colour=(10, 110, 79, 0)))) as image:
			self.assertEqual(image.mode, "RGBA")
			self.assertEqual(image.getpixel((0, 0))[3], 0)

	def test_a_big_logo_is_brought_down_and_a_small_one_never_enlarged(self):
		with _opened(logo.clean_logo(_png(size=(3000, 1000)))) as image:
			self.assertEqual(max(image.size), logo.MAX_SIDE)
		with _opened(logo.clean_logo(_png(size=(50, 20)))) as image:
			self.assertEqual(image.size, (50, 20))

	def test_what_the_file_carried_besides_its_pixels_does_not_survive(self):
		meta = PngImagePlugin.PngInfo()
		meta.add_text("Comment", "written by the camera of somebody")
		with _opened(logo.clean_logo(_png(pnginfo=meta))) as image:
			self.assertNotIn("Comment", image.info)
			self.assertNotIn("written by the camera", str(image.info))


class TestWhatIsRefused(unittest.TestCase):
	def refused(self, data):
		with self.assertRaises(logo.LogoRefused) as caught:
			logo.clean_logo(data)
		return caught.exception.reason

	def test_nothing_is_refused(self):
		self.assertEqual(self.refused(b""), "not_an_image")
		self.assertEqual(self.refused(None), "not_an_image")

	def test_an_svg_is_refused(self):
		# an SVG can carry a script and point at other files: not an image this page accepts
		svg = b'<svg xmlns="http://www.w3.org/2000/svg"><image href="file:///etc/passwd"/></svg>'
		self.assertEqual(self.refused(svg), "not_an_image")

	def test_a_file_that_only_claims_to_be_an_image_is_refused(self):
		self.assertEqual(self.refused(b"\x89PNG\r\n\x1a\n" + b"not really"), "not_an_image")
		self.assertEqual(self.refused(b"%PDF-1.7 ..."), "not_an_image")

	def test_a_truncated_png_is_refused(self):
		self.assertEqual(self.refused(_png(size=(400, 400))[:200]), "not_an_image")

	def test_a_truncated_png_is_refused_even_where_pillow_is_told_to_forgive_it(self):
		# Frappe sets ImageFile.LOAD_TRUNCATED_IMAGES = True for the whole process (core/doctype/file):
		# a half-sent logo would then load with a grey bottom and be kept
		previous = ImageFile.LOAD_TRUNCATED_IMAGES
		ImageFile.LOAD_TRUNCATED_IMAGES = True
		try:
			self.assertEqual(self.refused(_png(size=(400, 400))[:200]), "not_an_image")
			self.assertTrue(ImageFile.LOAD_TRUNCATED_IMAGES, "the setting of the process is given back as it was")
		finally:
			ImageFile.LOAD_TRUNCATED_IMAGES = previous

	def test_a_gif_is_refused(self):
		out = io.BytesIO()
		Image.new("P", (10, 10)).save(out, "GIF")
		self.assertEqual(self.refused(out.getvalue()), "format")

	def test_a_file_over_two_megabytes_is_refused(self):
		self.assertEqual(self.refused(b"\x00" * (logo.MAX_BYTES + 1)), "too_large")

	def test_a_picture_with_too_many_pixels_is_refused(self):
		# a few kilobytes of file that would unpack into a quarter of a gigabyte
		self.assertEqual(self.refused(_png(size=(6000, 6000))), "too_many_pixels")


if __name__ == "__main__":
	unittest.main()
