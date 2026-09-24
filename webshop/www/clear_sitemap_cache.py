#!/usr/bin/env python
# //// Neoffice — added file (no upstream equivalent). bench helper that drops every
# //// sitemap cache so the next request rebuilds them, for when a catalogue change must
# //// show up in the sitemap immediately (84530bf61b, 2025-06-26 "add sitemap
# //// generation for webshop pages"). Since 2026-09-24 the caches live in
# //// webshop/webshop/seo/sitemaps.py, and clearing them goes through redis_cache's own
# //// clear_cache(): deleting the bare function names, as this script did, matched no key.
"""
Usage: bench --site site1.local execute webshop.www.clear_sitemap_cache.clear_sitemap_cache
"""

import frappe


def clear_sitemap_cache():
	"""Clear all sitemap caches to force regeneration."""
	from webshop.webshop.seo.sitemaps import clear_caches

	clear_caches()
	print("Sitemap caches cleared: the sitemaps are rebuilt on their next request.")


if __name__ == "__main__":
	clear_sitemap_cache()
