# //// Neoffice — added file (no upstream equivalent). The addresses of a page in the other languages of a site
# //// (multilingual lot 3, neoffice-maintenance#2031).
"""A sitemap lists every page once per language it is translated in, and each entry names all the others.

`expand` is given the links of a sitemap (dicts with a `loc`, the document's `name` and its `route`) and returns them with, for
each document that a visitor can read in an additional language, a copy under that language's prefix; every one of these
carries the same `alternates` (`hreflang` and `href`, the site's own language and an `x-default` included). A document
that is not translated yet is left alone: an alternate towards a page still in French would be a lie to the search engines.
Without an additional language the links come back untouched.
"""

from webshop.webshop.utils import localized


def expand(links, doctype, loc_for):
	"""``loc_for(route, prefix)`` writes an address the way the sitemap does (absolute, encoded, XML-escaped)."""
	languages = localized.site_languages()
	if not languages or not links:
		return links
	done = localized.translated_documents(doctype, [link.get("name") for link in links])
	out = []
	for link in links:
		have = [code for code in languages if link.get("name") in done.get(code, ())]
		# the site's home page has the route "" (its language copy is "/de"): only a link with no route at all is left alone
		if not have or link.get("route") is None:
			out.append(link)
			continue
		alternates = [{"hreflang": localized.source_hreflang(), "href": link["loc"]}]
		alternates += [
			{"hreflang": localized.hreflang_of(code), "href": loc_for(link["route"], f"/{code}")}
			for code in have
		]
		alternates.append({"hreflang": "x-default", "href": link["loc"]})
		out.append({**link, "alternates": alternates})
		out += [
			{**link, "loc": loc_for(link["route"], f"/{code}"), "alternates": alternates} for code in have
		]
	return out


def expand_interface(links, loc_for):
	"""The links flagged `interface` (a page that is no document: the catalogue, a brand's page, with their `route`) with a copy
	under each language that publishes at once; every one names all the others, as `expand` does.

	Such a page exists under every prefix in the language of the interface, so there is no translation to look for: the
	theme's rule says which languages offer it to the search engines (neoffice-maintenance#2089). Without one the links come
	back untouched.
	"""
	codes = localized.interface_page_languages()
	if not codes or not links:
		return links
	out = []
	for link in links:
		if not link.get("interface") or link.get("route") is None:
			out.append(link)
			continue
		alternates = [{"hreflang": localized.source_hreflang(), "href": link["loc"]}]
		alternates += [
			{"hreflang": localized.hreflang_of(code), "href": loc_for(link["route"], f"/{code}")} for code in codes
		]
		alternates.append({"hreflang": "x-default", "href": link["loc"]})
		out.append({**link, "alternates": alternates})
		out += [{**link, "loc": loc_for(link["route"], f"/{code}"), "alternates": alternates} for code in codes]
	return out


def language_urls(route):
	"""The addresses (``/de/route``) a page has in the additional languages where it is translated: for IndexNow."""
	identity = localized.page_identity("/" + route.strip("/"))
	if not identity:
		return []
	return [f"/{code}/{route.strip('/')}" for code in localized.translated_languages(*identity)]
