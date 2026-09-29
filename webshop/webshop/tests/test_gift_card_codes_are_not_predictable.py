# //// Neoffice — added file (no upstream equivalent).
"""The codes of gift cards and coupons come from `secrets`, and their existence check is limited (#953).

A gift card or a coupon code is a token of value. Two things were wrong: the server minted the codes with
the `random` module (a predictable generator), and `check_gift_cards`, open to guests and answering
« this code exists », had no limit on how often it could be asked. The tests read the source with `ast` and
import nothing of the app, so they run anywhere, site or no site.
"""

import ast
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
CART = APP / "webshop" / "shopping_cart" / "cart.py"
ABANDONED_CARTS = APP / "webshop" / "utils" / "abandoned_carts.py"


def _tree(path):
	return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _uses_of_random(tree):
	"""Every import of `random` and every attribute read on the name `random`."""
	found = []
	for node in ast.walk(tree):
		if isinstance(node, ast.Import) and any(alias.name == "random" for alias in node.names):
			found.append(f"import random (line {node.lineno})")
		if isinstance(node, ast.ImportFrom) and node.module == "random":
			found.append(f"from random import … (line {node.lineno})")
		if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "random":
			found.append(f"random.{node.attr} (line {node.lineno})")
	return found


def _decorator_names(function):
	names = []
	for decorator in function.decorator_list:
		target = decorator.func if isinstance(decorator, ast.Call) else decorator
		names.append(ast.unparse(target))
	return names


class TestGiftCardCodesAreNotPredictable(unittest.TestCase):
	def test_the_cart_mints_no_code_with_random(self):
		self.assertEqual(_uses_of_random(_tree(CART)), [])

	def test_the_coupon_of_a_reminder_is_minted_with_secrets(self):
		tree = _tree(ABANDONED_CARTS)
		self.assertEqual(_uses_of_random(tree), [])
		imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
		self.assertIn("secrets", imported)

	def test_the_check_of_a_code_is_rate_limited_and_still_open_to_guests(self):
		function = next(
			node for node in ast.walk(_tree(CART)) if isinstance(node, ast.FunctionDef) and node.name == "check_gift_cards"
		)
		names = _decorator_names(function)
		self.assertIn("rate_limit", names, names)
		self.assertIn("frappe.whitelist", names, names)
		# the limit must sit under the whitelist decorator, the way frappe applies it
		self.assertLess(names.index("frappe.whitelist"), names.index("rate_limit"), names)


if __name__ == "__main__":
	unittest.main()
