# //// Neoffice — added file (no upstream equivalent). XML escaping and URL quoting
# //// shared by the seven sitemaps (84530bf61b, 2025-06-26). A product name with an
# //// ampersand made the whole sitemap unparseable for Google.
# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import html
from urllib.parse import quote

def escape_xml(text):
    """Escape text for XML output"""
    if not text:
        return ""
    # HTML escape handles &, <, >, ", '
    return html.escape(str(text), quote=True)

def prepare_url_for_xml(url):
    """Prepare URL for XML sitemap - properly encode and escape"""
    if not url:
        return ""
    # The URL should already be properly quoted, but we need to escape & for XML
    return escape_xml(url)