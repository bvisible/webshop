# //// Neoffice — added file (no upstream equivalent).
"""Product videos: the addresses a merchant pastes, what the page plays, and the flag
the catalogue badges."""

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.tests.utils import make_test_item
from webshop.webshop.utils.videos import has_playable_video, product_videos, video_info, vimeo_id, youtube_id


class TestVideoAddresses(FrappeTestCase):
	def test_youtube_addresses_as_the_browser_shows_them(self):
		for url in (
			"https://www.youtube.com/watch?v=aqz-KE-bpKQ",
			"https://www.youtube.com/watch?feature=share&v=aqz-KE-bpKQ&t=12",
			"https://youtu.be/aqz-KE-bpKQ?si=abc",
			"https://www.youtube.com/shorts/aqz-KE-bpKQ",
			"https://www.youtube-nocookie.com/embed/aqz-KE-bpKQ",
			"https://m.youtube.com/watch?v=aqz-KE-bpKQ",
		):
			self.assertEqual(youtube_id(url), "aqz-KE-bpKQ", url)
		self.assertIsNone(youtube_id("https://www.youtube.com/channel/UCabc"))
		self.assertIsNone(youtube_id("https://vimeo.com/76979871"))
		self.assertIsNone(youtube_id(""))

	def test_vimeo_addresses(self):
		for url in ("https://vimeo.com/76979871", "https://player.vimeo.com/video/76979871?h=8272103f6e", "https://vimeo.com/channels/staffpicks/76979871"):
			self.assertEqual(vimeo_id(url), "76979871", url)
		self.assertIsNone(vimeo_id("https://vimeo.com/user12345"))

	def test_a_youtube_row_plays_without_cookies_and_shows_its_own_thumbnail(self):
		info = video_info({"source": "YouTube", "url": "https://youtu.be/aqz-KE-bpKQ", "title": "Trail"})
		self.assertEqual(info.kind, "youtube")
		self.assertIn("youtube-nocookie.com/embed/aqz-KE-bpKQ", info.embed)
		self.assertEqual(info.poster, "https://i.ytimg.com/vi/aqz-KE-bpKQ/hqdefault.jpg")
		self.assertEqual(info.title, "Trail")
		# a poster the merchant attached wins over the platform's thumbnail
		info = video_info({"source": "YouTube", "url": "https://youtu.be/aqz-KE-bpKQ", "poster": "/files/poster.jpg"})
		self.assertEqual(info.poster, "/files/poster.jpg")

	def test_a_vimeo_row_carries_do_not_track(self):
		info = video_info({"source": "Vimeo", "url": "https://vimeo.com/76979871"})
		self.assertEqual(info.kind, "vimeo")
		self.assertIn("player.vimeo.com/video/76979871?dnt=1", info.embed)
		self.assertIsNone(info.poster)

	def test_a_hosted_file_is_played_by_the_browser(self):
		info = video_info({"source": "Hosted file", "file": "/files/trail run.webm", "poster": "/files/p.jpg"})
		self.assertEqual(info.kind, "file")
		self.assertEqual(info.src, "/files/trail%20run.webm")
		self.assertEqual(info.mime, "video/webm")
		self.assertEqual(info.poster, "/files/p.jpg")
		self.assertEqual(video_info({"source": "Hosted file", "file": "/files/clip.mp4"}).mime, "video/mp4")

	def test_a_row_that_cannot_play_is_left_out(self):
		self.assertIsNone(video_info({"source": "YouTube", "url": "https://example.com/not-a-video"}))
		self.assertIsNone(video_info({"source": "Hosted file", "file": ""}))
		rows = [
			{"source": "YouTube", "url": "nothing"},
			{"source": "YouTube", "url": "https://youtu.be/aqz-KE-bpKQ"},
			{"source": "Hosted file", "file": "/files/a.mp4"},
		]
		self.assertEqual([v.kind for v in product_videos({"videos": rows})], ["youtube", "file"])
		self.assertFalse(has_playable_video({"videos": [rows[0]]}))


class TestHasVideoFlag(FrappeTestCase):
	"""`has_video` mirrors the table on save, so the listing badges tiles without a join."""

	def test_the_flag_follows_the_playable_rows(self):
		make_test_item("_Test Video Item", item_name="_Test Video Item")
		name = frappe.db.get_value("Website Item", {"item_code": "_Test Video Item"}, "name")
		doc = frappe.get_doc("Website Item", name) if name else frappe.get_doc({"doctype": "Website Item", "item_code": "_Test Video Item", "web_item_name": "_Test Video Item", "published": 1}).insert()
		doc.set("videos", [])
		doc.save()
		self.assertEqual(doc.has_video, 0)
		doc.append("videos", {"source": "YouTube", "url": "https://youtu.be/aqz-KE-bpKQ", "title": "Trail"})
		doc.save()
		self.assertEqual(frappe.db.get_value("Website Item", doc.name, "has_video"), 1)
		doc.set("videos", [{"source": "YouTube", "url": "https://example.com/nope"}])
		doc.save()
		self.assertEqual(frappe.db.get_value("Website Item", doc.name, "has_video"), 0)
