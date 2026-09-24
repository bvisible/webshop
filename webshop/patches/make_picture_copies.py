# //// Neoffice — added file (no upstream equivalent). neoffice-maintenance#691, lot 5.
"""The WebP copies of every published picture, written in the background once: a Website Item
saved later has its own written by on_website_item_update (utils/renditions.py)."""

from webshop.webshop.utils.renditions import enqueue_catalogue_renditions


def execute():
	enqueue_catalogue_renditions()
