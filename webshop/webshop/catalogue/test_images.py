# //// Neoffice — added file (no upstream equivalent).
"""The pictures of a product sheet: which file may be read, and what comes out of it.

A PDF engine embeds a photo as it is, so a 4 MB camera file would make a 4 MB page: every picture is
rebuilt as a bounded JPEG first. And a picture is read only from the site's public files, whatever
address the product names. Pure functions (Pillow only): no site needed.
"""

import io
import os
import unittest

from PIL import Image

from webshop.webshop.catalogue import images


def _png(size=(1200, 800), mode="RGB", colour=(10, 110, 79)):
	out = io.BytesIO()
	Image.new(mode, size, colour).save(out, "PNG")
	return out.getvalue()


def _opened(data):
	return Image.open(io.BytesIO(data))


class TestEncode(unittest.TestCase):
	def test_a_picture_comes_out_as_a_jpeg(self):
		with _opened(images.encode_jpeg(_png())) as image:
			self.assertEqual(image.format, "JPEG")

	def test_a_big_picture_is_brought_down_and_a_small_one_never_enlarged(self):
		with _opened(images.encode_jpeg(_png(size=(3000, 2000)), max_side=900)) as image:
			self.assertEqual(max(image.size), 900)
		with _opened(images.encode_jpeg(_png(size=(300, 200)), max_side=900)) as image:
			self.assertEqual(image.size, (300, 200))

	def test_transparency_is_laid_on_white_not_on_black(self):
		with _opened(images.encode_jpeg(_png(size=(40, 40), mode="RGBA", colour=(0, 0, 0, 0)))) as image:
			red, green, blue = image.getpixel((0, 0))
			self.assertGreater(min(red, green, blue), 245)

	def test_a_palette_and_a_cmyk_picture_are_read(self):
		out = io.BytesIO()
		Image.new("P", (40, 40)).save(out, "PNG")
		self.assertIsNotNone(images.encode_jpeg(out.getvalue()))
		out = io.BytesIO()
		Image.new("CMYK", (40, 40), (0, 0, 0, 0)).save(out, "JPEG")
		with _opened(images.encode_jpeg(out.getvalue())) as image:
			self.assertEqual(image.mode, "RGB")

	def test_what_is_not_a_picture_gives_nothing(self):
		for raw in (b"", None, b"not an image", b"<svg xmlns='http://www.w3.org/2000/svg'/>"):
			with self.subTest(raw=raw):
				self.assertIsNone(images.encode_jpeg(raw))

	def test_a_file_of_absurd_size_gives_nothing(self):
		self.assertIsNone(images.encode_jpeg(b"\x00" * (images.MAX_SOURCE_BYTES + 1)))

	def test_a_data_uri_names_its_type_and_decodes_to_the_same_bytes(self):
		import base64

		jpeg = images.encode_jpeg(_png())
		uri = images.data_uri(jpeg)
		self.assertTrue(uri.startswith("data:image/jpeg;base64,"))
		self.assertEqual(base64.b64decode(uri.split(",", 1)[1]), jpeg)


class TestSmallerPictures(unittest.TestCase):
	def test_a_camera_file_is_brought_down_to_the_wanted_size_even_when_it_is_decoded_small(self):
		out = io.BytesIO()
		Image.new("RGB", (4000, 3000), (10, 110, 79)).save(out, "JPEG", quality=90)
		with _opened(images.encode_jpeg(out.getvalue(), max_side=440)) as image:
			self.assertEqual(max(image.size), 440)
			self.assertAlmostEqual(image.size[0] / image.size[1], 4 / 3, delta=0.01)

	def test_the_shops_own_copy_is_preferred_when_there_is_one_wide_enough(self):
		import tempfile
		from unittest import mock

		from webshop.webshop.utils import renditions

		with tempfile.TemporaryDirectory() as folder:
			for width in (400, 800):
				open(os.path.join(folder, f"a.png.{width}w.webp"), "wb").close()
			path = lambda name, width: os.path.join(folder, f"{name}.{width}w.webp")  # noqa: E731
			with mock.patch.object(renditions, "rendition_path", side_effect=path):
				self.assertEqual(images.smaller_copy("/files/a.png", 440), "/files/wsr/a.png.800w.webp", "400 is too small for 440")
				self.assertEqual(images.smaller_copy("/files/a.png", 300), "/files/wsr/a.png.400w.webp", "the smallest wide enough")
				self.assertEqual(images.smaller_copy("/files/a.png", 1000), "/files/a.png", "no copy that wide: the picture itself")
				self.assertEqual(images.smaller_copy("/files/b.png", 300), "/files/b.png", "no copy at all")
				for url in ("https://example.com/a.png", "/private/files/a.png", "/files/a.svg", "/files/../a.png", "", None):
					self.assertEqual(images.smaller_copy(url, 300), url, url)


class TestWhichFileMayBeRead(unittest.TestCase):
	ROOT = os.path.join(os.sep, "sites", "shop.local", "public")

	def path(self, url):
		return images.public_file_path(url, self.ROOT)

	def test_a_public_file_is_read_from_the_public_folder(self):
		self.assertEqual(self.path("/files/a.jpg"), os.path.join(self.ROOT, "files", "a.jpg"))
		self.assertEqual(self.path("/files/sub/dir/a.jpg"), os.path.join(self.ROOT, "files", "sub", "dir", "a.jpg"))

	def test_a_site_folder_written_relative_to_the_bench_is_read_like_an_absolute_one(self):
		# frappe.get_site_path answers "./shop.local/public" from the bench's sites folder
		for root in ("./shop.local/public", "shop.local/public", "./shop.local/../shop.local/public"):
			with self.subTest(root=root):
				path = images.public_file_path("/files/a.jpg", root)
				self.assertEqual(path, os.path.normpath(os.path.join(root, "files", "a.jpg")))
				self.assertIsNone(images.public_file_path("/files/../../site_config.json", root))

	def test_a_name_with_spaces_or_accents_written_as_an_address_is_read_back(self):
		self.assertEqual(self.path("/files/chaise%20pliante%20%C3%A9t%C3%A9.jpg"), os.path.join(self.ROOT, "files", "chaise pliante été.jpg"))

	def test_nothing_outside_the_public_files_is_ever_read(self):
		for url in (
			"/files/../../site_config.json",
			"/files/%2e%2e/%2e%2e/site_config.json",
			"/files/a/../../../etc/passwd",
			"/private/files/invoice.jpg",
			"/assets/frappe/a.jpg",
			"files/a.jpg",
			"https://example.com/files/a.jpg",
			"//example.com/files/a.jpg",
			"file:///etc/passwd",
			"/files/a\x00.jpg",
			"/files/",
			"",
			None,
		):
			with self.subTest(url=url):
				self.assertIsNone(self.path(url))


if __name__ == "__main__":
	unittest.main()
