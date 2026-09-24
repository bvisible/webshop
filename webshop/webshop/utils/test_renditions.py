# //// Neoffice — added file (no upstream equivalent). neoffice-maintenance#691, lot 5.
"""The WebP copies of the shop's pictures (utils/renditions.py): which pictures get them, what an
<img> is given, how a copy is written, served and forgotten. The pictures are drawn by the tests,
written where the site keeps its public files, and removed afterwards."""

import os
import re
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from webshop.webshop.utils import renditions
from webshop.webshop.utils.product_card import render_product_card

PREFIX = "_wstest_renditions"


def draw(name, size, mode="RGB", fmt="JPEG", orientation=None):
	"""A picture of `size` written as a public file; its address."""
	path = renditions.source_path(name)
	os.makedirs(os.path.dirname(path), exist_ok=True)
	picture = Image.new(mode, size, (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30))
	extra = {}
	if orientation:
		exif = Image.Exif()
		exif[renditions.EXIF_ORIENTATION] = orientation
		extra["exif"] = exif
	picture.save(path, fmt, **extra)
	return "/files/" + name


class RenditionsTestCase(FrappeTestCase):
	def setUp(self):
		self.names = []
		self.addCleanup(self.remove_pictures)

	def picture(self, suffix, size, **kwargs):
		name = f"{PREFIX}_{frappe.generate_hash(length=8)}_{suffix}"
		self.names.append(name)
		return draw(name, size, **kwargs)

	def remove_pictures(self):
		for name in self.names:
			for path in [renditions.source_path(name)] + [renditions.rendition_path(name, w) for w in renditions.WIDTHS]:
				if os.path.isfile(path):
					os.remove(path)
			frappe.cache().hdel(renditions.SIZE_CACHE, name)


class TestWhichPictures(FrappeTestCase):
	def test_only_a_public_raster_file_of_this_site(self):
		self.assertEqual(renditions.source_name("/files/a.jpg"), "a.jpg")
		self.assertEqual(renditions.source_name("/files/Photo 1.PNG"), "Photo 1.PNG")
		for url in (
			"/private/files/a.jpg",
			"/files/a.svg",
			"/files/a.gif",
			"https://cdn.example.com/a.jpg",
			"/files/sub/a.jpg",
			"/files/../a.jpg",
			"/files/.a.jpg",
			"/files/a.jpg?v=2",
			"",
			None,
		):
			with self.subTest(url=url):
				self.assertIsNone(renditions.source_name(url))


class TestWhatAnImgIsGiven(RenditionsTestCase):
	def test_the_copies_narrower_than_the_picture_and_the_picture_when_it_is_small_enough(self):
		url = self.picture("mid.jpg", (1000, 500))
		name = renditions.source_name(url)
		pic = renditions.webshop_picture(url, "grid")
		self.assertEqual(pic.src, url)
		self.assertEqual(
			pic.srcset,
			f"/files/wsr/{name}.400w.webp 400w, /files/wsr/{name}.800w.webp 800w, {url} 1000w",
		)
		self.assertEqual(pic.sizes, renditions.SIZES["grid"])
		self.assertEqual((pic.width, pic.height), (1000, 500))

	def test_a_large_photograph_is_offered_as_copies_only(self):
		url = self.picture("big.jpg", (2400, 1600))
		srcset = renditions.webshop_picture(url, "gallery").srcset
		self.assertEqual(re.findall(r" (\d+)w", srcset), ["400", "800", "1200", "1600"])
		self.assertNotIn(url + " ", srcset, "a 2400 px original is never a candidate: 1600 serves every screen")

	def test_a_small_picture_keeps_its_src_and_gives_its_size(self):
		url = self.picture("small.png", (300, 200), fmt="PNG")
		pic = renditions.webshop_picture(url, "grid")
		self.assertEqual((pic.srcset, pic.sizes), ("", ""))
		self.assertEqual((pic.width, pic.height), (300, 200))

	def test_a_name_with_a_space_is_escaped_in_the_srcset(self):
		url = self.picture("with space.jpg", (900, 900))
		self.assertIn("with%20space.jpg.400w.webp 400w", renditions.webshop_picture(url).srcset)

	def test_what_is_not_a_picture_of_this_site_keeps_its_plain_src(self):
		for url in ("https://cdn.example.com/a.jpg", "/files/does-not-exist.jpg", None):
			with self.subTest(url=url):
				pic = renditions.webshop_picture(url)
				self.assertEqual((pic.srcset, pic.width), ("", None))

	def test_a_photograph_turned_by_its_exif_reports_the_size_it_is_shown_at(self):
		url = self.picture("turned.jpg", (1000, 600), orientation=6)
		self.assertEqual(renditions.picture_size(url), (600, 1000))


class TestACopy(RenditionsTestCase):
	def test_it_is_a_webp_at_the_width_and_keeps_the_proportions(self):
		url = self.picture("copy.jpg", (1000, 500))
		path = renditions.make_rendition(renditions.source_name(url), 400)
		with Image.open(path) as copy:
			self.assertEqual((copy.format, copy.size), ("WEBP", (400, 200)))

	def test_it_keeps_a_transparent_background(self):
		url = self.picture("clear.png", (900, 900), mode="RGBA", fmt="PNG")
		path = renditions.make_rendition(renditions.source_name(url), 400)
		with Image.open(path) as copy:
			self.assertEqual((copy.size, copy.mode), ((400, 400), "RGBA"))

	def test_a_turned_photograph_is_copied_upright(self):
		url = self.picture("upright.jpg", (1000, 600), orientation=6)
		path = renditions.make_rendition(renditions.source_name(url), 400)
		with Image.open(path) as copy:
			self.assertEqual(copy.size, (400, 667))

	def test_nothing_is_written_at_a_width_it_does_not_offer(self):
		url = self.picture("narrow.jpg", (500, 500))
		name = renditions.source_name(url)
		self.assertIsNone(renditions.make_rendition(name, 800), "never wider than the picture")
		self.assertIsNone(renditions.make_rendition(name, 300), "only the widths of WIDTHS")
		self.assertIsNone(renditions.make_rendition("does-not-exist.jpg", 400))

	def test_the_job_writes_every_copy_the_picture_needs(self):
		url = self.picture("job.jpg", (1300, 1300))
		renditions.make_renditions([url, url, "https://cdn.example.com/a.jpg"])
		name = renditions.source_name(url)
		written = [w for w in renditions.WIDTHS if os.path.isfile(renditions.rendition_path(name, w))]
		self.assertEqual(written, [400, 800, 1200])

	def test_a_saved_website_item_queues_its_pictures(self):
		item = frappe._dict(name="WEB-ITM-TEST", website_image="/files/a.jpg", slideshow=None, published=1)
		with patch("frappe.enqueue") as enqueue:
			renditions.on_website_item_update(item)
		self.assertEqual(enqueue.call_args.kwargs["urls"], ["/files/a.jpg"])
		self.assertEqual(enqueue.call_args.kwargs["job_id"], "webshop-renditions-WEB-ITM-TEST")
		with patch("frappe.enqueue") as enqueue:
			renditions.on_website_item_update(frappe._dict(item, published=0))
			renditions.on_website_item_update(frappe._dict(item, website_image="https://cdn.example.com/a.jpg"))
		enqueue.assert_not_called()

	def test_a_deleted_picture_takes_its_copies_and_its_size_with_it(self):
		url = self.picture("gone.jpg", (1000, 1000))
		renditions.make_renditions([url])
		name = renditions.source_name(url)
		self.assertTrue(frappe.cache().hget(renditions.SIZE_CACHE, name))
		renditions.on_file_trash(frappe._dict(file_url=url, is_private=0))
		self.assertFalse([w for w in renditions.WIDTHS if os.path.isfile(renditions.rendition_path(name, w))])
		self.assertIsNone(frappe.cache().hget(renditions.SIZE_CACHE, name))


class TestTheFirstRequest(RenditionsTestCase):
	def test_a_missing_copy_is_written_and_served(self):
		url = self.picture("served.jpg", (1000, 1000))
		name = renditions.source_name(url)
		renderer = renditions.RenditionRenderer(f"files/wsr/{name}.400w.webp", 200)
		self.assertTrue(renderer.can_render())
		response = renderer.render()
		self.assertEqual(response.mimetype, "image/webp")
		self.assertTrue(response.get_data().startswith(b"RIFF"))
		self.assertTrue(os.path.isfile(renditions.rendition_path(name, 400)), "nginx serves it from now on")

	def test_nothing_else_is_answered(self):
		url = self.picture("refused.jpg", (1000, 1000))
		name = renditions.source_name(url)
		for path in (
			f"files/wsr/{name}.500w.webp",  # not one of the widths
			f"files/wsr/{name}.1200w.webp",  # wider than the picture
			"files/wsr/does-not-exist.jpg.400w.webp",
			f"files/wsr/sub/{name}.400w.webp",
			f"files/{name}.400w.webp",
			"files/wsr/a.svg.400w.webp",
		):
			with self.subTest(path=path):
				self.assertFalse(renditions.RenditionRenderer(path, 200).can_render())


class TestThePages(RenditionsTestCase):
	def settings(self):
		return frappe._dict(
			enabled=1,
			enable_checkout=1,
			enable_wishlist=1,
			show_stock_availability=1,
			product_image_fit="Contain",
			product_image_aspect_ratio="1/1",
		)

	def item(self, image):
		return frappe._dict(
			name="WEB-ITEM-0001",
			item_code="ITEM-0001",
			web_item_name="A picture",
			route="products/a-picture",
			website_image=image,
			formatted_price="CHF 12.00",
			has_variants=0,
		)

	def test_a_card_offers_the_copies_at_its_layouts_sizes(self):
		url = self.picture("card.jpg", (1000, 800))
		name = renditions.source_name(url)
		for variant in ("grid", "carousel", "list", "wishlist"):
			with self.subTest(variant=variant):
				html = str(render_product_card(self.item(url), self.settings(), variant))
				self.assertIn(f'srcset="/files/wsr/{name}.400w.webp 400w', html)
				self.assertIn(f'sizes="{renditions.SIZES[variant]}"', html)
				self.assertIn('width="1000" height="800"', html)
				self.assertIn(f'src="{url}"', html, "the src stays the original")
		html = str(render_product_card(self.item("https://cdn.example.com/a.jpg"), self.settings(), "grid"))
		self.assertNotIn("srcset=", html)

	def test_the_gallerys_first_picture_is_one_download_wherever_it_shows(self):
		urls = [self.picture(f"gallery{i}.jpg", (1600, 1600)) for i in range(3)]
		doc = frappe._dict(web_item_name="A picture", item_name="A picture", website_image=urls[0])
		html = frappe.render_template(
			"templates/generators/item/item_image.html",
			{
				"doc": doc,
				"slides": [frappe._dict(image=url, heading="") for url in urls],
				"videos": [],
				"shopping_cart": frappe._dict(cart_settings=frappe._dict(product_image_fit="Contain")),
			},
		)
		first = renditions.source_name(urls[0])
		tags = [
			tag
			for tag in re.findall(r"<img[^>]+>", html)
			if f"/files/{first}\"" in tag and "wsp-gallery__img" in tag
		]
		# the mosaic's first tile and the phone strip's first slide
		self.assertGreaterEqual(len(tags), 2)
		sizes = {re.search(r'sizes="([^"]+)"', tag).group(1) for tag in tags}
		self.assertEqual(sizes, {renditions.SIZES["gallery_large"]})
		# the zoom's thumbnails take the small copies too
		thumbs = [tag for tag in re.findall(r"<img[^>]+>", html) if "zoom-thumbnail" in tag]
		self.assertTrue(thumbs and all(f'sizes="{renditions.SIZES["thumb"]}"' in tag for tag in thumbs))
		srcsets = re.search(r'data-srcsets="([^"]+)"', html).group(1)
		self.assertIn(f"{first}.400w.webp", srcsets.replace("&#34;", '"').replace("&quot;", '"'))
