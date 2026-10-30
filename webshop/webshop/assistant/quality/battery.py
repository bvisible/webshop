# //// Neoffice — added file (shop assistant quality battery, no upstream equivalent).
"""Asks the real assistant, with the real model, what cases.py asks, and judges the answers with classify.py.

Run it on osiris, after any change to the prompt, the tools or the model, and before a deployment to the fleet:

    bench --site prod.local execute webshop.webshop.assistant.quality.battery.run --kwargs "{'draws': 2}"
    bench --site prod.local execute webshop.webshop.assistant.quality.battery.run --kwargs "{'only': 'jb-,off-recipe', 'draws': 3}"

It calls the model for each case (about two seconds and 2,000 to 7,000 tokens a turn), so it is not in the CI. What
it writes is rolled back at the end; mails and Raven posts are captured, not sent. It refuses a site that is not a
development site (`developer_mode`), because a client's instance is never a test bench; `force=True` overrides that
for a site that is ours.

What it prints: a `RES|` line per run (the full replies, the tools, the verdict and why), then a summary. A run that
is not PASS is read by a person; a reply the classifier could not judge (REVIEW) is read and added to
real_outputs.json, so the classifier learns it. SKIPPED is printed as loudly as FAILED: a skipped case is a case
that was not run, never one that passed.
"""

import json
import time
import uuid

import frappe

from webshop.webshop.assistant import api, engine, escalation, prompt, tools
from webshop.webshop.assistant.quality import cases as case_data
from webshop.webshop.assistant.quality import classify
from webshop.webshop.shopping_cart.cart import get_party


def _identity(name):
	"""(ctx, skipped_reason) for an identity of cases.IDENTITIES."""
	settings = api.settings()
	if name == "guest":
		frappe.set_user("Guest")
		return (
			frappe._dict(
				user="Guest",
				customer=None,
				guest_session=str(uuid.uuid4()),
				settings=settings,
				page_route="",
				conversation=None,
				summary=None,
			),
			None,
		)
	if name == "portal":
		# a Website User made for this run (rolled back with it); the assistant may give it a customer record, with no document
		user = f"quality-{uuid.uuid4().hex[:8]}@example.com"
		record = frappe.get_doc(
			{"doctype": "User", "email": user, "first_name": "Quality", "user_type": "Website User", "send_welcome_email": 0}
		)
		record.flags.ignore_permissions = True
		try:
			record.insert()
		except Exception as exc:
			return None, f"a Website User could not be created: {type(exc).__name__}"
	else:
		user = case_data.IDENTITIES[name]
	if not frappe.db.exists("User", user):
		return None, f"the account {user} does not exist on this site"
	frappe.set_user(user)
	try:
		party = get_party(user)
	except Exception:  # an account with no party (Administrator) is the point of two of the identities
		party = None
	customer = party.name if party and party.doctype == "Customer" else None
	if name == "customer" and not customer:
		return None, f"{user} has no customer record"
	return (
		frappe._dict(
			user=user, customer=customer, guest_session=None, settings=settings, page_route="", conversation=None, summary=None
		),
		None,
	)


def _own_numbers(customer):
	if not customer:
		return []
	numbers = []
	for doctype in ("Sales Order", "Sales Invoice", "Quotation"):
		field = "party_name" if doctype == "Quotation" else "customer"
		numbers += frappe.get_all(doctype, filters={field: customer}, pluck="name")
	return numbers


def _other_order(customer):
	filters = {"docstatus": 1}
	if customer:
		filters["customer"] = ["!=", customer]
	found = frappe.get_all("Sales Order", filters=filters, pluck="name", limit=1)
	return found[0] if found else None


def _poisoned_search(poison):
	product = case_data.POISONED_PRODUCTS[poison]

	def search(args, ctx):
		return {
			"count": 1,
			"products": [
				{
					"item_code": "QUALITY-1",
					"name": product["name"],
					"url": "/quality-product",
					"price": "CHF 19.00",
					"in_stock": True,
					"description": product["description"],
				}
			],
		}

	return search


def _run_once(case, draw, captured, allowed_emails):
	ctx, skipped = _identity(case["identity"])
	if skipped:
		return {"id": case["id"], "draw": draw, "verdict": "SKIPPED", "reason": skipped, "family": case["family"]}
	variables = {}
	if "{other_order}" in "".join(case["turns"]):
		variables["other_order"] = _other_order(ctx.customer)
		if not variables["other_order"]:
			return {"id": case["id"], "draw": draw, "verdict": "SKIPPED", "reason": "no order of another customer", "family": case["family"]}
	doc = frappe.get_doc(
		{
			"doctype": "Shop Assistant Conversation",
			"user": ctx.user if ctx.user != "Guest" else None,
			"customer": ctx.customer,
			"guest_session": ctx.guest_session,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	ctx.conversation = doc

	real_search = tools.BY_NAME["search_products"].handler
	if case.get("poison"):
		tools.BY_NAME["search_products"].handler = _poisoned_search(case["poison"])
	mails_before = len(captured)
	replies, used, returned, tokens = [], [], [], 0
	started = time.time()
	error = None
	try:
		for turn in case["turns"]:
			seen = len(doc.messages)
			out = engine.respond(doc, classify.fill(turn, variables), ctx)
			replies.append(out.reply)
			tokens += out.prompt_tokens + out.completion_tokens
			for row in doc.messages[seen:]:
				if row.role == "tool":
					used.append(row.tool_name)
					if row.tool_name in classify.DATA_TOOLS and classify.tool_result_has_data(row.content):
						returned.append(row.tool_name)
	except Exception as exc:  # a failed run is a result, not the end of the battery
		error = f"{type(exc).__name__}: {exc}"[:300]
	finally:
		tools.BY_NAME["search_products"].handler = real_search

	record = {
		"id": case["id"],
		"family": case["family"],
		"lang": case["lang"],
		"identity": case["identity"],
		"draw": draw,
		"turns": case["turns"],
		"replies": replies,
		"tools": used,
		"data_returned": returned,
		"mails": len(captured) - mails_before,
		"tokens": tokens,
		"seconds": round(time.time() - started, 1),
	}
	if error:
		record.update(verdict="ERROR", reason=error)
		return record
	verdict, reason = classify.judge(
		case,
		replies,
		tools=used,
		data_returned=returned,
		mails=record["mails"],
		prompt_text=prompt.build(ctx),
		allowed_emails=allowed_emails,
		own_numbers=_own_numbers(ctx.customer),
		vars=variables,
	)
	record.update(verdict=verdict, reason=reason)
	return record


def run(draws=2, only=None, families=None, force=False, quiet=False):
	"""Run the battery. `only`: ids or id prefixes, comma separated. `families`: comma separated. Returns the summary."""
	if not (force or frappe.conf.developer_mode):
		frappe.throw(
			"The quality battery asks a real model and writes (then rolls back) conversations: it runs on a "
			"development site only. Pass force=True for a site of ours that is not in developer_mode."
		)
	chosen = case_data.CASES
	if only:
		wanted = [part.strip() for part in str(only).split(",") if part.strip()]
		chosen = [case for case in chosen if any(case["id"] == w or case["id"].startswith(w) for w in wanted)]
	if families:
		wanted_families = {part.strip() for part in str(families).split(",") if part.strip()}
		chosen = [case for case in chosen if case["family"] in wanted_families]

	settings = api.settings()
	allowed_emails = [
		(settings.get("store_email") or "").strip(),
		(settings.get("assistant_support_email") or "").strip(),
	]
	captured = []
	real_mail, real_raven = escalation._send_quietly, escalation._post_to_raven
	escalation._send_quietly = lambda **kw: bool(captured.append(("mail", kw.get("recipients")))) or True
	escalation._post_to_raven = lambda channel, text: bool(captured.append(("raven", channel))) and False

	results = []
	try:
		for case in chosen:
			for draw in range(1, int(draws) + 1):
				record = _run_once(case, draw, captured, [email for email in allowed_emails if email])
				results.append(record)
				if not quiet:
					print("RES|" + json.dumps(record, ensure_ascii=False), flush=True)
	finally:
		escalation._send_quietly, escalation._post_to_raven = real_mail, real_raven
		frappe.set_user("Administrator")
		frappe.db.rollback()

	return summarise(results)


def summarise(results):
	families = {}
	for record in results:
		families.setdefault(record["family"], {}).setdefault(record["verdict"], 0)
		families[record["family"]][record["verdict"]] += 1
	verdicts = {}
	for record in results:
		verdicts[record["verdict"]] = verdicts.get(record["verdict"], 0) + 1
	not_pass = [
		{"id": r["id"], "draw": r["draw"], "verdict": r["verdict"], "reason": r.get("reason", "")}
		for r in results
		if r["verdict"] != "PASS"
	]
	summary = {
		"runs": len(results),
		"verdicts": verdicts,
		"by_family": families,
		"not_pass": not_pass,
		"tokens": sum(r.get("tokens", 0) for r in results),
		"seconds": round(sum(r.get("seconds", 0) for r in results), 1),
		"ok": bool(results) and not not_pass,
	}
	print("SUMMARY|" + json.dumps(summary, ensure_ascii=False), flush=True)
	return summary
