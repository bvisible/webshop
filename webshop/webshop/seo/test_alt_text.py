# //// Neoffice — added file (no upstream equivalent): the pictures' descriptions proposed by a model
# //// that sees them (seo/alt_text.py). neoffice-maintenance#691, decision D-11, 2026-09-25.
"""What a product's pictures show, for those who cannot see them: proposed one by one, stopped
once when the site has no model that sees, and written only onto the item's own pictures."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.seo import alt_text
from webshop.webshop.tests.utils import leaf_item_group, make_test_item

ITEM = "WSP-D11-SHOE"
SLIDESHOW = "WSP D11 shoe pictures"


class Failure(Exception):
	def __init__(self, reason):
		super().__init__(reason)
		self.reason = reason


def _doc(**fields):
	return frappe._dict(
		{"name": "WEB-1", "web_item_name": "Trail shoe", "brand": "Trailhead", "website_image": None, "slideshow": None, **fields}
	)


class TestThePictures(FrappeTestCase):
	def test_each_picture_once_with_every_place_it_sits_in(self):
		slides = [
			frappe._dict(name="ROW-1", image="/files/side.jpg", image_alt=""),
			frappe._dict(name="ROW-2", image="/files/sole.jpg", image_alt="The sole"),
		]
		with patch.object(alt_text.frappe, "get_all", return_value=slides):
			found = alt_text.pictures(_doc(website_image="/files/side.jpg", website_image_alt="Side", slideshow="S"))
		self.assertEqual([p.image for p in found], ["/files/side.jpg", "/files/sole.jpg"])
		self.assertEqual(found[0].places, ["website_image", "ROW-1"])
		self.assertEqual((found[0].alt, found[1].alt), ("Side", "The sole"))

	def test_a_variant_is_described_by_its_model_s_name(self):
		with patch.object(alt_text.frappe.db, "get_value", return_value="Coastline tee"):
			self.assertEqual(alt_text.context_of(_doc(web_item_name="Coastline tee XL", variant_of="TEE")), "Coastline tee, Trailhead")
		self.assertEqual(alt_text.context_of(_doc()), "Trail shoe, Trailhead")

	def test_a_description_is_cut_at_a_word(self):
		text = "A grey trail shoe seen from the side " * 6
		cut = alt_text.cut(text, 140)
		self.assertLessEqual(len(cut), 140)
		self.assertTrue(text.startswith(cut))
		self.assertFalse(cut.endswith(" "))


class TestTheProposals(FrappeTestCase):
	def run_job(self, describe):
		pictures = [
			frappe._dict(image="/files/a.jpg", alt="", places=["website_image"]),
			frappe._dict(image="/files/b.jpg", alt="", places=["ROW-1"]),
			frappe._dict(image="/files/c.jpg", alt="", places=["ROW-2"]),
		]
		with (
			patch.object(alt_text.frappe, "get_doc", return_value=_doc()),
			patch.object(alt_text, "pictures", return_value=pictures),
			patch.object(alt_text, "vision", return_value=describe),
			patch.object(alt_text.frappe, "publish_realtime") as publish,
			patch.object(alt_text.frappe, "log_error"),
		):
			alt_text.propose_in_background("WEB-1", "merchant@example.com")
		return [call.args[1] for call in publish.call_args_list]

	def test_one_proposal_per_picture_and_its_own_failure(self):
		def describe(image, context=""):
			self.assertEqual(context, "Trail shoe, Trailhead")
			if image == "/files/b.jpg":
				raise Failure("image_unreadable")
			return f"Seen: {image}"

		messages = self.run_job(describe)
		self.assertEqual(
			messages,
			[
				{"name": "WEB-1", "image": "/files/a.jpg", "alt": "Seen: /files/a.jpg"},
				{"name": "WEB-1", "image": "/files/b.jpg", "reason": "image_unreadable"},
				{"name": "WEB-1", "image": "/files/c.jpg", "alt": "Seen: /files/c.jpg"},
				{"name": "WEB-1", "done": True},
			],
		)

	def test_a_site_without_a_model_that_sees_says_so_once(self):
		calls = []

		def describe(image, context=""):
			calls.append(image)
			raise Failure("no_vision_model")

		self.assertEqual(self.run_job(describe), [{"name": "WEB-1", "done": True, "reason": "no_vision_model"}])
		self.assertEqual(calls, ["/files/a.jpg"], "the batch stops at the first answer")
		self.assertEqual(self.run_job(None), [{"name": "WEB-1", "done": True, "reason": "no_vision_model"}])


class TestKeepingThem(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from webshop.patches.add_picture_alt_field import execute

		execute()
		cls._purge()
		make_test_item(ITEM, is_stock_item=0)
		slideshow = frappe.get_doc(
			{
				"doctype": "Website Slideshow",
				"slideshow_name": SLIDESHOW,
				"slideshow_items": [{"image": "/files/wsp-d11-side.jpg"}, {"image": "/files/wsp-d11-sole.jpg"}],
			}
		).insert(ignore_permissions=True)
		web_item = frappe.get_doc(
			{
				"doctype": "Website Item",
				"item_code": ITEM,
				"web_item_name": "D11 shoe",
				"item_group": leaf_item_group(),
				"published": 0,
			}
		)
		web_item.flags.ignore_permissions = True
		web_item.insert()
		# set as they are: the website image's validation looks for the file on disk
		web_item.db_set({"website_image": "/files/wsp-d11-side.jpg", "slideshow": slideshow.name})
		cls.web_item = web_item.name
		# class fixtures survive FrappeTestCase's rollback only committed (CLAUDE.md, Testing Strategy)
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		cls._purge()
		# see setUpClass
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
		super().tearDownClass()

	@staticmethod
	def _purge():
		for name in frappe.get_all("Website Item", filters={"item_code": ITEM}, pluck="name"):
			frappe.delete_doc("Website Item", name, force=True, ignore_permissions=True)
		if frappe.db.exists("Website Slideshow", SLIDESHOW):
			frappe.delete_doc("Website Slideshow", SLIDESHOW, force=True, ignore_permissions=True)
		if frappe.db.exists("Item", ITEM):
			frappe.delete_doc("Item", ITEM, force=True, ignore_permissions=True)

	def test_only_the_item_s_own_pictures_are_written(self):
		long_text = "A grey trail shoe with a mesh upper and a white midsole, seen from the side on a dark ground, laces tied, heel tab raised"
		answer = alt_text.save(
			self.web_item,
			{
				"/files/wsp-d11-side.jpg": long_text,
				"/files/wsp-d11-sole.jpg": "The sole's lugs, seen from below",
				"/private/files/somebody-else.pdf": "never written",
			},
		)
		self.assertEqual(answer, {"kept": 2})
		alt, assisted = frappe.db.get_value("Website Item", self.web_item, ["website_image_alt", "alt_ai_assisted"])
		self.assertTrue(long_text.startswith(alt) and len(alt) <= alt_text.DATA_LENGTH)
		self.assertEqual(assisted, 1)
		slides = dict(
			frappe.get_all(
				"Website Slideshow Item", filters={"parent": SLIDESHOW}, fields=["image", "image_alt"], as_list=True
			)
		)
		self.assertEqual(slides["/files/wsp-d11-side.jpg"], long_text, "a slide keeps the whole sentence")
		self.assertEqual(slides["/files/wsp-d11-sole.jpg"], "The sole's lugs, seen from below")

	def test_a_visitor_writes_nothing(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			alt_text.save(self.web_item, {"/files/wsp-d11-side.jpg": "Nothing"})
		with self.assertRaises(frappe.PermissionError):
			alt_text.propose(self.web_item)
