# //// Neoffice — added file (no upstream equivalent).
"""The codes of gift cards and coupons come from `secrets`, and their existence check is limited (#953).

A gift card or a coupon code is a token of value. Two things were wrong: the server minted the codes with
the `random` module (a predictable generator), and `check_gift_cards`, open to guests and answering
« this code exists », had no limit on how often it could be asked. A third: the code of a card bought in the
shop was made in the buyer's browser (Math.random on the item page) and kept by the server; the server mints
it now, when the card's invoice is paid, and drops whatever code a request carries. The tests read the source
with `ast` (and run a helper or two of it against stubs) and import nothing of the app, so they run anywhere,
site or no site.
"""

import ast
import re
import secrets
import unittest
from pathlib import Path
from types import SimpleNamespace

APP = Path(__file__).resolve().parents[2]
CART = APP / "webshop" / "shopping_cart" / "cart.py"
ABANDONED_CARTS = APP / "webshop" / "utils" / "abandoned_carts.py"
ITEM_PAGE = APP / "templates" / "generators" / "item" / "item_add_to_cart.html"


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


def _isolated(names, **namespace):
	"""The top-level functions and constants `names` of cart.py, run in a namespace of their own with the stubs given."""
	tree = _tree(CART)
	nodes = [
		node
		for node in tree.body
		if (isinstance(node, ast.FunctionDef) and node.name in names)
		or (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets))
	]
	exec(compile(ast.Module(body=nodes, type_ignores=[]), str(CART), "exec"), namespace)
	return namespace


def _stub_frappe(taken=()):
	"""A frappe whose database knows the codes `taken`, and whose throw raises."""

	def throw(message):
		raise RuntimeError(message)

	exists = lambda doctype, filters: filters.get("coupon_code") in taken  # noqa: E731
	return SimpleNamespace(db=SimpleNamespace(exists=exists), throw=throw)


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



class TestTheServerMintsTheCodeOfACard(unittest.TestCase):
	def test_a_code_a_request_carries_is_dropped(self):
		at = _isolated(["_gift_card_data_at"])["_gift_card_data_at"]

		data = at({"code": "AAAA-BBBB-CCCC", "codes": ["AAAA-BBBB-CCCC"], "amount_type": "50", "rate": -5}, 50)

		self.assertNotIn("code", data)
		self.assertNotIn("codes", data)
		self.assertEqual((data["rate"], data["price_list_rate"], data["amount_type"]), (50, 50, "50"))

	def test_the_code_comes_from_secrets_in_the_format_of_the_shop_and_is_free(self):
		taken = set()
		mint = _isolated(
			["GIFT_CARD_CODE_ALPHABET", "_new_gift_card_code"], frappe=_stub_frappe(taken), secrets=secrets, _=str
		)["_new_gift_card_code"]

		codes = {mint() for _ in range(50)}

		self.assertEqual(len(codes), 50)
		for code in codes:
			self.assertRegex(code, r"^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")

	def test_a_code_some_card_has_is_never_given(self):
		drawn = iter("AAAABBBBCCCC" + "DDDDEEEEFFFF")
		namespace = _isolated(
			["GIFT_CARD_CODE_ALPHABET", "_new_gift_card_code"],
			frappe=_stub_frappe({"AAAA-BBBB-CCCC"}),
			secrets=SimpleNamespace(choice=lambda alphabet: next(drawn)),
			_=str,
		)

		self.assertEqual(namespace["_new_gift_card_code"](), "DDDD-EEEE-FFFF")

	def test_every_card_of_an_invoice_takes_a_code_of_the_server(self):
		hook = next(
			node
			for node in ast.walk(_tree(CART))
			if isinstance(node, ast.FunctionDef) and node.name == "create_gift_cards_from_invoice"
		)
		made = [
			ast.unparse(node.value)
			for node in ast.walk(hook)
			if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "coupon_code" for t in node.targets)
		]
		self.assertEqual(made, ["_new_gift_card_code()"])

	def test_a_line_whose_cards_were_made_is_found_by_their_codes(self):
		found = _isolated(["_cards_of_the_line_exist"], frappe=_stub_frappe({"SRVR-CODE-0001", "OLD1-BRWS-CODE"}))[
			"_cards_of_the_line_exist"
		]

		self.assertTrue(found({"codes": ["SRVR-CODE-0001"]}))
		self.assertTrue(found({"code": "OLD1-BRWS-CODE"}))  # a line from before: a card already made, never a second
		self.assertFalse(found({"codes": ["NONE-MADE-YET"]}))
		self.assertFalse(found(None))

	def test_the_item_page_makes_no_code(self):
		page = ITEM_PAGE.read_text(encoding="utf-8")
		self.assertFalse("Math.random" in page, "the item page draws a code with Math.random")
		self.assertIsNone(re.search(r"\bcode\s*:\s*uniqueCode", page), "the item page sends a code of its own")
		self.assertFalse("check_gift_cards" in page, "the item page asks whether its own code is free")


if __name__ == "__main__":
	unittest.main()
