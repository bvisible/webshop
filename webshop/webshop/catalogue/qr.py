# //// Neoffice — added file (no upstream equivalent).
"""A QR code as a data URI, with the library Frappe itself depends on (PyQRCode, for two-factor setup)."""

MAX_LENGTH = 300


def qr_data_uri(text, scale=4):
	"""`text` as a QR code in a PNG data URI, or None when there is nothing sensible to encode."""
	if not isinstance(text, str) or not text.strip() or len(text) > MAX_LENGTH:
		return None
	try:
		import pyqrcode

		code = pyqrcode.create(text.strip(), error="M")
		return "data:image/png;base64," + code.png_as_base64_str(scale=scale, quiet_zone=1)
	except Exception:
		return None
