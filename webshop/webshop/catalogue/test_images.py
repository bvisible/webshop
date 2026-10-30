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
