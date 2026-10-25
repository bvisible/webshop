# //// Neoffice — added file (no upstream equivalent).
"""The cart builds its tax table with erpnext's TaxService when there is one (2026-10-25).

frappe/webshop b2b697361d (2026-09-15) calls `TaxService(quotation).append_taxes_from_master()` where the
cart called the same method on the quotation. The service does not exist in every erpnext the shop runs on
(the fleet's has none yet), and importing it unconditionally would break the tax table of every cart there.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from webshop.webshop.shopping_cart import cart


class TestTaxBuilder(unittest.TestCase):
	def test_the_document_builds_its_own_taxes_when_erpnext_has_no_tax_service(self):
		quotation = MagicMock()
		# a None entry in sys.modules makes the import raise, as a missing module does
		with patch.dict(sys.modules, {"erpnext.accounts.services": None, "erpnext.accounts.services.taxes": None}):
			self.assertIs(cart.tax_builder(quotation), quotation)

	def test_the_tax_service_builds_them_when_erpnext_has_one(self):
		quotation, service = MagicMock(), MagicMock()
		module = types.ModuleType("erpnext.accounts.services.taxes")
		module.TaxService = MagicMock(return_value=service)
		with patch.dict(
			sys.modules,
			{"erpnext.accounts.services": types.ModuleType("erpnext.accounts.services"), "erpnext.accounts.services.taxes": module},
		):
			self.assertIs(cart.tax_builder(quotation), service)
		module.TaxService.assert_called_once_with(quotation)

	def test_set_taxes_asks_the_builder_for_both_tables(self):
		quotation, builder = MagicMock(), MagicMock()
		with patch("erpnext.accounts.party.set_taxes", return_value="Tax Master"), patch.object(
			cart.frappe.db, "get_value", return_value="Group"
		), patch.object(cart, "tax_builder", return_value=builder) as factory:
			cart.set_taxes(quotation, MagicMock())
		factory.assert_called_once_with(quotation)
		quotation.set.assert_called_once_with("taxes", [])
		builder.append_taxes_from_master.assert_called_once_with()
		builder.append_taxes_from_item_tax_template.assert_called_once_with()
