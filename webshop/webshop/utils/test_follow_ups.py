# //// Neoffice — added file (purchase follow-ups and abandoned carts).
"""Enrolment on an order, the daily send, the stop rules, the cart reminders.

Emails are muted: what is asserted is the Communication on the customer and
the entry's log, which is what the seller sees. Orders and quotations are
committed fixtures (the cart commits anyway) and purged at the end.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, getdate, now_datetime, nowdate

from webshop.webshop.tests.utils import (
	PREFIX,
	make_test_item,
	portal_customer,
	restore_webshop_settings,
	selling_price_list,
	snapshot_webshop_settings,
)
from webshop.webshop.utils import abandoned_carts, follow_ups

USER = "_wstest_followup@example.com"
CUSTOMER = "_WSTEST Follow-up Customer"
SETTINGS = (
	"enable_abandoned_cart_emails",
	"abandoned_cart_delays",
	"abandoned_cart_template",
	"abandoned_cart_incentive_step",
	"abandoned_cart_discount_percentage",
	"abandoned_cart_coupon_validity_days",
)


class TestFollowUps(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.flags.mute_emails = True
		cls.snapshot = snapshot_webshop_settings(SETTINGS)
		cls.suffix = frappe.generate_hash(length=5).upper()
		cls.item = make_test_item(f"{PREFIX} Coffee {cls.suffix}", is_stock_item=0).name
		cls.other = make_test_item(f"{PREFIX} Filter {cls.suffix}", is_stock_item=0).name
		if frappe.db.has_column("Item", "replenishment_days"):
			frappe.db.set_value("Item", cls.item, "replenishment_days", 30)
		# a shopping-cart quotation only takes items that have a Website Item
		from webshop.webshop.doctype.website_item.website_item import make_website_item

		for code in (cls.item, cls.other):
			if not frappe.db.exists("Website Item", {"item_code": code}):
				make_website_item(frappe.get_doc("Item", code))
		portal_customer(USER, CUSTOMER)
		for name in ("Webshop - How is it going", "Webshop - Your opinion", "Webshop - Your cart is waiting"):
			if not frappe.db.exists("Email Template", name):
				from webshop.patches.seed_follow_up_email_templates import execute

				execute()
				break
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		cls.purge()
		for code in (cls.item, cls.other):
			for name in frappe.get_all("Website Item", filters={"item_code": code}, pluck="name"):
				frappe.delete_doc("Website Item", name, force=True, ignore_permissions=True)
		restore_webshop_settings(cls.snapshot)
		frappe.flags.mute_emails = False
		frappe.db.commit()
		super().tearDownClass()

	@classmethod
	def purge(cls):
		for doctype in ("Purchase Follow-up Entry", "Abandoned Cart Reminder"):
			for name in frappe.get_all(doctype, filters={"customer": CUSTOMER}, pluck="name"):
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Purchase Follow-up", filters={"title": ("like", f"{PREFIX}%")}, pluck="name"):
			frappe.delete_doc("Purchase Follow-up", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Communication", filters={"reference_doctype": "Customer", "reference_name": CUSTOMER}, pluck="name"):
			frappe.delete_doc("Communication", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Sales Order", filters={"customer": CUSTOMER}, pluck="name"):
			doc = frappe.get_doc("Sales Order", name)
			if doc.docstatus == 1:
				doc.cancel()
			frappe.delete_doc("Sales Order", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Quotation", filters={"party_name": CUSTOMER}, pluck="name"):
			frappe.delete_doc("Quotation", name, force=True, ignore_permissions=True)
		for coupon in frappe.get_all("Coupon Code", filters={"customer": CUSTOMER}, fields=["name", "pricing_rule"]):
			frappe.delete_doc("Coupon Code", coupon.name, force=True, ignore_permissions=True)
			if coupon.pricing_rule:
				frappe.delete_doc("Pricing Rule", coupon.pricing_rule, force=True, ignore_permissions=True)
		frappe.db.delete("Email Unsubscribe", {"email": USER})

	def setUp(self):
		frappe.set_user("Administrator")
		self.purge()
		frappe.db.commit()

	# --- fixtures ----------------------------------------------------------

	def make_flow(self, **values):
		data = {
			"doctype": "Purchase Follow-up",
			"title": f"{PREFIX} Follow-up {self.suffix}",
			"enabled": 1,
			"trigger_type": "All Purchases",
			"only_website_orders": 1,
			"steps": [
				{"label": "Check-in", "days_after": 7, "email_template": "Webshop - How is it going"},
				{"label": "Review", "days_after": 14, "email_template": "Webshop - Your opinion", "stop_if_reordered": 1},
			],
		}
		data.update(values)
		return frappe.get_doc(data).insert(ignore_permissions=True)

	def make_order(self, item=None, website=True, submit=True, date=None):
		order = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"customer": CUSTOMER,
				"contact_email": USER,
				"order_type": "Shopping Cart" if website else "Sales",
				"transaction_date": date or nowdate(),
				"delivery_date": add_days(date or nowdate(), 7),
				"selling_price_list": selling_price_list(),
				"items": [{"item_code": item or self.item, "qty": 1, "rate": 25, "delivery_date": add_days(date or nowdate(), 7)}],
			}
		)
		order.flags.ignore_permissions = True
		order.insert()
		if submit:
			order.submit()
		return order

	def entries(self, **filters):
		filters.setdefault("customer", CUSTOMER)
		return frappe.get_all(
			"Purchase Follow-up Entry", filters=filters, fields=["name", "status", "next_step", "next_send_on", "item_code", "stop_reason"]
		)

	# --- enrolment -----------------------------------------------------------

	def test_an_order_from_the_shop_enrols_the_customer(self):
		flow = self.make_flow()
		order = self.make_order()

		entries = self.entries(flow=flow.name)
		self.assertEqual(len(entries), 1)
		entry = entries[0]
		self.assertEqual(entry.item_code, self.item)
		self.assertEqual(entry.status, "Scheduled")
		self.assertEqual(entry.next_step, 1)
		self.assertEqual(getdate(entry.next_send_on), add_days(getdate(order.transaction_date), 7))
		self.assertEqual(frappe.db.get_value("Purchase Follow-up", flow.name, "enrolled"), 1)

		# submitting again (or a second hook run) never enrols twice
		follow_ups.enroll_from_sales_order(order)
		self.assertEqual(len(self.entries(flow=flow.name)), 1)

	def test_a_counter_sale_is_left_out_when_the_flow_says_shop_only(self):
		flow = self.make_flow()
		self.make_order(website=False)
		self.assertEqual(self.entries(flow=flow.name), [])

	def test_the_trigger_selects_the_item(self):
		flow = self.make_flow(trigger_type="Item", trigger_item=self.other)
		self.make_order(item=self.item)
		self.assertEqual(self.entries(flow=flow.name), [])
		self.make_order(item=self.other)
		self.assertEqual(len(self.entries(flow=flow.name)), 1)

	def test_the_replenishment_step_follows_the_item_cycle(self):
		if not frappe.db.has_column("Item", "replenishment_days"):
			self.fail("Item.replenishment_days is missing: the patch did not run")
		flow = self.make_flow(steps=[{"label": "Restock", "days_after": 0, "use_item_cycle": 1, "email_template": "Webshop - How is it going"}])
		order = self.make_order(item=self.item)  # 30-day cycle -> day 24
		entry = self.entries(flow=flow.name)[0]
		self.assertEqual(getdate(entry.next_send_on), add_days(getdate(order.transaction_date), 24))
		# an item without a cycle is not enrolled at all
		self.make_order(item=self.other)
		self.assertEqual(len(self.entries(flow=flow.name)), 1)

	def test_cancelling_the_order_stops_the_follow_up(self):
		flow = self.make_flow()
		order = self.make_order()
		order.cancel()
		self.assertEqual(self.entries(flow=flow.name)[0].status, "Stopped")

	# --- the daily send -------------------------------------------------------

	def test_a_due_step_goes_to_the_customer_and_schedules_the_next(self):
		flow = self.make_flow()
		order = self.make_order(date=add_days(nowdate(), -8))
		entry = frappe.get_doc("Purchase Follow-up Entry", self.entries(flow=flow.name)[0].name)
		self.assertLessEqual(getdate(entry.next_send_on), getdate(nowdate()))

		self.assertTrue(follow_ups.process_entry(entry))

		entry.reload()
		self.assertEqual(entry.status, "Scheduled")
		self.assertEqual(entry.next_step, 2)
		self.assertEqual(getdate(entry.next_send_on), add_days(getdate(order.transaction_date), 14))
		self.assertEqual(len(entry.log), 1)
		self.assertEqual(entry.log[0].outcome, "Sent")
		communication = frappe.get_doc("Communication", entry.log[0].communication)
		self.assertEqual(communication.reference_name, CUSTOMER)
		self.assertEqual(communication.recipients, USER)
		self.assertIn(frappe.db.get_value("Item", self.item, "item_name"), communication.subject)
		self.assertEqual(frappe.db.get_value("Purchase Follow-up", flow.name, "sent"), 1)

		# not due yet: the daily job leaves it alone (other flows enabled on the
		# site may well have something to send: only this entry is asserted)
		follow_ups.send_due_follow_ups()
		entry.reload()
		self.assertEqual(len(entry.log), 1)
		self.assertEqual(entry.next_step, 2)

	def test_the_last_step_completes_the_entry(self):
		flow = self.make_flow()
		self.make_order(date=add_days(nowdate(), -15))
		entry = frappe.get_doc("Purchase Follow-up Entry", self.entries(flow=flow.name)[0].name)
		follow_ups.process_entry(entry)  # step 1, late but within two weeks
		entry.reload()
		follow_ups.process_entry(entry)  # step 2
		entry.reload()
		self.assertEqual(entry.status, "Completed")
		self.assertEqual(len(entry.log), 2)

	def test_an_unsubscribed_customer_is_never_written_to(self):
		flow = self.make_flow()
		self.make_order(date=add_days(nowdate(), -8))
		frappe.get_doc(
			{"doctype": "Email Unsubscribe", "email": USER, "reference_doctype": "Customer", "reference_name": CUSTOMER}
		).insert(ignore_permissions=True)
		entry = frappe.get_doc("Purchase Follow-up Entry", self.entries(flow=flow.name)[0].name)
		self.assertFalse(follow_ups.process_entry(entry))
		entry.reload()
		self.assertEqual(entry.status, "Stopped")
		self.assertEqual(entry.stop_reason, "Unsubscribed")
		self.assertEqual(entry.log, [])

	def test_a_second_order_stops_the_steps_that_ask_for_it(self):
		flow = self.make_flow()
		self.make_order(date=add_days(nowdate(), -15))
		entry = frappe.get_doc("Purchase Follow-up Entry", self.entries(flow=flow.name)[0].name)
		follow_ups.process_entry(entry)  # step 1 does not care about reorders
		entry.reload()
		self.make_order(item=self.other)  # a second order, today
		entry.reload()
		self.assertFalse(follow_ups.process_entry(entry))
		entry.reload()
		self.assertEqual(entry.status, "Stopped")
		self.assertEqual(entry.stop_reason, "Ordered again")

	def test_a_step_missed_by_more_than_two_weeks_is_skipped_not_sent(self):
		flow = self.make_flow()
		self.make_order(date=add_days(nowdate(), -40))
		entry = frappe.get_doc("Purchase Follow-up Entry", self.entries(flow=flow.name)[0].name)
		self.assertFalse(follow_ups.process_entry(entry))
		entry.reload()
		self.assertEqual(entry.log[0].outcome, "Skipped (too old)")
		self.assertEqual(entry.next_step, 2)

	# --- abandoned carts --------------------------------------------------------

	def stale_cart(self, hours):
		cart = frappe.get_doc(
			{
				"doctype": "Quotation",
				"quotation_to": "Customer",
				"party_name": CUSTOMER,
				"contact_email": USER,
				"order_type": "Shopping Cart",
				"selling_price_list": selling_price_list(),
				"items": [{"item_code": self.item, "qty": 2, "rate": 25}],
			}
		)
		cart.flags.ignore_permissions = True
		cart.insert()
		frappe.db.set_value("Quotation", cart.name, "modified", add_to_date(now_datetime(), hours=-hours), update_modified=False)
		return cart

	def enable_reminders(self, incentive_step=None):
		settings = frappe.get_single("Webshop Settings")
		settings.enable_abandoned_cart_emails = 1
		settings.abandoned_cart_delays = "1,24,72"
		settings.abandoned_cart_template = "Webshop - Your cart is waiting"
		settings.abandoned_cart_incentive_step = str(incentive_step) if incentive_step else ""
		settings.abandoned_cart_discount_percentage = 10
		settings.abandoned_cart_coupon_validity_days = 7
		settings.flags.ignore_permissions = True
		settings.flags.ignore_mandatory = True
		settings.save()
		frappe.db.commit()

	def reminders(self, cart):
		return frappe.get_all(
			"Abandoned Cart Reminder", filters={"quotation": cart.name}, fields=["step", "coupon_code", "communication", "converted"], order_by="step asc"
		)

	def test_a_cart_left_for_an_hour_gets_its_first_reminder_only_once(self):
		self.enable_reminders()
		cart = self.stale_cart(hours=2)
		fresh = self.stale_cart(hours=0)

		self.assertGreaterEqual(abandoned_carts.send_abandoned_cart_reminders(), 1)
		sent = self.reminders(cart)
		self.assertEqual([r.step for r in sent], [1])
		self.assertFalse(sent[0].coupon_code)
		communication = frappe.get_doc("Communication", sent[0].communication)
		self.assertEqual(communication.reference_name, CUSTOMER)
		self.assertIn(frappe.db.get_value("Item", self.item, "item_name"), communication.content)
		self.assertEqual(self.reminders(fresh), [])

		# the next hour: nothing new, the second email waits for its delay
		abandoned_carts.send_abandoned_cart_reminders()
		self.assertEqual([r.step for r in self.reminders(cart)], [1])

	def test_the_second_reminder_brings_the_coupon_when_asked(self):
		self.enable_reminders(incentive_step=2)
		cart = self.stale_cart(hours=30)
		abandoned_carts.send_abandoned_cart_reminders()  # step 1, its delay is long past
		frappe.db.set_value(
			"Abandoned Cart Reminder", {"quotation": cart.name}, "sent_on", add_to_date(now_datetime(), hours=-25), update_modified=False
		)
		abandoned_carts.send_abandoned_cart_reminders()  # step 2
		sent = self.reminders(cart)
		self.assertEqual([r.step for r in sent], [1, 2])
		self.assertFalse(sent[0].coupon_code)
		self.assertTrue(sent[1].coupon_code)
		coupon = frappe.get_doc("Coupon Code", sent[1].coupon_code)
		self.assertEqual(coupon.customer, CUSTOMER)
		self.assertEqual(coupon.maximum_use, 1)
		self.assertEqual(frappe.db.get_value("Pricing Rule", coupon.pricing_rule, "discount_percentage"), 10)
		self.assertIn(coupon.coupon_code, frappe.get_doc("Communication", sent[1].communication).content)

	def test_an_order_from_the_cart_marks_the_reminders_converted(self):
		self.enable_reminders()
		cart = self.stale_cart(hours=2)
		abandoned_carts.send_abandoned_cart_reminders()
		order = self.make_order(submit=False)
		order.items[0].prevdoc_docname = cart.name
		order.save()
		order.submit()
		self.assertTrue(self.reminders(cart)[0].converted)

	def test_the_customer_who_unsubscribed_is_not_reminded(self):
		self.enable_reminders()
		frappe.get_doc({"doctype": "Email Unsubscribe", "email": USER, "global_unsubscribe": 1}).insert(ignore_permissions=True)
		cart = self.stale_cart(hours=2)
		abandoned_carts.send_abandoned_cart_reminders()
		self.assertEqual(self.reminders(cart), [])
