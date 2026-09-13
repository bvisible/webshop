# //// Neoffice — added file (no upstream equivalent).
"""Product videos: what a row of Website Item's `videos` table means on the page.

A merchant pastes a YouTube or Vimeo address as the browser shows it, or attaches a
file the shop hosts. The page needs three things from a row — what to show in the
gallery before anyone clicks (a poster), what to play when they do (an embed URL or
the file itself), and a title — and nothing here talks to the network: a YouTube
poster is the address of YouTube's own thumbnail, a hosted file's poster is the file's
first frame unless the merchant attached one.

Third-party players load only when the visitor opens the video: the gallery draws the
poster, the lightbox creates the iframe. YouTube goes through youtube-nocookie.com and
Vimeo carries dnt=1, so a visitor who never presses play never talks to either.
"""

import re
from urllib.parse import quote

import frappe

YOUTUBE_ID = re.compile(
	r"(?:youtube(?:-nocookie)?\.com/(?:(?:watch|attribution_link)\?(?:[^#]*&)?v=|embed/|shorts/|live/|v/)|youtu\.be/)"
	r"([A-Za-z0-9_-]{11})"
)
VIMEO_ID = re.compile(r"vimeo\.com/(?:video/|channels/[^/]+/|groups/[^/]+/videos/|showcase/\d+/video/)?(\d+)")

VIDEO_MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".ogv": "video/ogg", ".mov": "video/quicktime"}


def youtube_id(url):
	"""The 11-character id of a YouTube address, or None."""
	match = YOUTUBE_ID.search(url or "")
	return match.group(1) if match else None


def vimeo_id(url):
	"""The numeric id of a Vimeo address, or None."""
	match = VIMEO_ID.search(url or "")
	return match.group(1) if match else None


def video_info(row):
	"""What the page needs from one row: kind, id, embed or src, poster, title — or None
	when the row cannot be played (an address that is not the platform's, no file)."""
	row = frappe._dict(row) if not isinstance(row, dict) else frappe._dict(row)
	source = row.get("source") or "YouTube"
	title = row.get("title") or ""
	poster = row.get("poster") or None
	if source == "YouTube":
		vid = youtube_id(row.get("url"))
		if not vid:
			return None
		return frappe._dict(
			kind="youtube",
			id=vid,
			embed=f"https://www.youtube-nocookie.com/embed/{vid}?rel=0&modestbranding=1&playsinline=1&autoplay=1",
			poster=poster or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
			title=title,
		)
	if source == "Vimeo":
		vid = vimeo_id(row.get("url"))
		if not vid:
			return None
		return frappe._dict(
			kind="vimeo",
			id=vid,
			embed=f"https://player.vimeo.com/video/{vid}?dnt=1&autoplay=1",
			poster=poster,
			title=title,
		)
	path = row.get("file")
	if not path:
		return None
	ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
	return frappe._dict(
		kind="file",
		id=path,
		src=path if path.startswith(("http://", "https://")) else quote(path),
		mime=VIDEO_MIME.get(ext, "video/mp4"),
		poster=poster,
		title=title,
	)


def product_videos(website_item):
	"""The playable videos of a Website Item (document or dict with a `videos` list), in order."""
	rows = website_item.get("videos") if hasattr(website_item, "get") else getattr(website_item, "videos", None)
	videos = []
	for row in rows or []:
		info = video_info(row.as_dict() if hasattr(row, "as_dict") else row)
		if info:
			videos.append(info)
	return videos


def has_playable_video(website_item):
	return bool(product_videos(website_item))
