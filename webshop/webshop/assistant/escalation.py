# //// Neoffice — added file (shop assistant, no upstream equivalent).
"""Handing a conversation to people: a word to the team, a ticket for the customer.

Raven and Helpdesk are optional on a site; both paths degrade to email when
the app or the setting is missing, and always tell the customer what was done.
"""

import frappe
from frappe import _
from frappe.utils import escape_html, get_url, now_datetime


# //// Neoffice — a public visitor must never see the shop's mail-server error. frappe.sendmail
# //// resolves the outgoing account inline and frappe.throw's "Incorrect Configuration" when it
# //// cannot (osiris: the SMTP host does not resolve); the throw is caught, but the message it
# //// already pushed on the log still travels back to the browser as a modal. Restore the log.
def _send_quietly(**kwargs):
	"""Queue a mail; on any failure log it and leave the visitor's message log untouched."""
	saved = list(frappe.local.message_log or [])
	try:
		frappe.sendmail(**kwargs)
		return True
	except Exception:
		frappe.log_error("Shop assistant: mail not sent", frappe.get_traceback())
		return False
	finally:
		frappe.local.message_log = saved


def _team_channel(settings):
	return (settings.get("assistant_escalation_channel") or "").strip()


def _support_email(settings):
	return (settings.get("assistant_support_email") or "").strip() or frappe.db.get_single_value("Website Settings", "email")


def _customer_label(ctx, email):
	if ctx.customer:
		return frappe.db.get_value("Customer", ctx.customer, "customer_name") or ctx.customer
	return email


def _post_to_raven(channel, text):
	"""A message in a Raven channel, by its name or id; False when Raven is not there."""
	if not channel or not frappe.db.exists("DocType", "Raven Channel"):
		return False
	channel_id = channel if frappe.db.exists("Raven Channel", channel) else frappe.db.get_value("Raven Channel", {"channel_name": channel}, "name")
	if not channel_id:
		return False
	try:
		frappe.get_doc(
			{"doctype": "Raven Message", "channel_id": channel_id, "text": text, "message_type": "Text"}
		).insert(ignore_permissions=True)
		return True
	except Exception:
		frappe.log_error("Shop assistant: Raven message failed", frappe.get_traceback())
		return False


def _notify_customer(email, subject, message, ctx):
	"""The confirmation the visitor asked for a moment ago.

	Transactional, so it is not sent through the follow-ups' path: that one carries
	Frappe's unsubscribe scoped to the Customer, and a customer who once stopped the
	reminders was silently dropped here too (nothing queued, nothing logged). The
	mail references the conversation instead; the Customer's timeline still shows it.
	"""
	# //// Neoffice — was send_customer_email(): its Customer-scoped unsubscribe swallowed
	# //// this confirmation for a customer who had opted out of the follow-ups.
	from webshop.webshop.utils.follow_ups import outgoing_sender

	conversation = ctx.conversation
	try:
		if ctx.customer:
			frappe.get_doc(
				{
					"doctype": "Communication",
					"communication_type": "Communication",
					"communication_medium": "Email",
					"sent_or_received": "Sent",
					"subject": subject,
					"content": message,
					"sender": outgoing_sender(),
					"recipients": email,
					"reference_doctype": "Customer",
					"reference_name": ctx.customer,
				}
			).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error("Shop assistant: customer notification failed", frappe.get_traceback())
	# the mail on its own quiet path: an SMTP error must not surface to the visitor
	_send_quietly(
		recipients=[email],
		subject=subject,
		message=message,
		reference_doctype="Shop Assistant Conversation" if conversation else None,
		reference_name=conversation.name if conversation else None,
	)


def contact_team(ctx, summary, email):
	settings = ctx.settings
	conversation = ctx.conversation
	link = get_url(f"/app/shop-assistant-conversation/{conversation.name}") if conversation else ""
	who = _customer_label(ctx, email)
	text = f"**Assistant boutique** — {escape_html(who)} ({escape_html(email)}) demande l'équipe :\n{escape_html(summary)}\n{link}"
	channel_done = _post_to_raven(_team_channel(settings), text)
	support = _support_email(settings)
	if support:
		_send_quietly(
			recipients=[support],
			subject=_("Assistant boutique : {0} demande l'équipe").format(who),
			message=text.replace("\n", "<br>"),
			reference_doctype="Shop Assistant Conversation" if conversation else None,
			reference_name=conversation.name if conversation else None,
		)
	if conversation:
		conversation.status = "Escalated"
		conversation.escalated_to = "Team"
		conversation.escalation_note = summary
	_notify_customer(
		email,
		_("Votre demande a été transmise à l'équipe"),
		_("Bonjour,<br><br>Votre demande a été transmise à notre équipe : « {0} ». Quelqu'un vous recontacte rapidement à cette adresse.<br><br>{1}").format(
			escape_html(summary), frappe.db.get_single_value("Website Settings", "app_name") or ""
		),
		ctx,
	)
	return {
		"escalated": True,
		"via": "raven" if channel_done else ("email" if support else "none"),
		"note": _("La demande est transmise à l'équipe ; elle recontactera le client à {0}. Dis-le lui, sans promettre de délai précis.").format(email),
	}


def create_support_ticket(ctx, subject, description, email):
	settings = ctx.settings
	conversation = ctx.conversation
	if not frappe.db.exists("DocType", "HD Ticket"):
		out = contact_team(ctx, f"{subject} — {description}", email)
		out["note"] = _("Pas de helpdesk sur cette boutique : la demande est partie à l'équipe par message.")
		return out
	team = (settings.get("assistant_helpdesk_team") or "").strip()
	ticket = frappe.get_doc(
		{
			"doctype": "HD Ticket",
			"subject": subject or _("Demande depuis l'assistant de la boutique"),
			"description": escape_html(description).replace("\n", "<br>"),
			"raised_by": email,
			# //// Neoffice — HD Ticket.customer links to Helpdesk's own HD Customer, not to ERPNext's Customer; inserting the ERPNext one raised LinkValidationError and the request fell back to contact_team (231ad396f5 "fix(assistant): le ticket Helpdesk ne pointe pas un Client ERPNext")
			# HD Ticket.customer links to Helpdesk's own HD Customer, not to ERPNext's
			"customer": ctx.customer if ctx.customer and frappe.db.exists("HD Customer", ctx.customer) else None,
			"agent_group": team if team and frappe.db.exists("HD Team", team) else None,
			"via_customer_portal": 1,
		}
	)
	ticket.flags.ignore_permissions = True
	try:
		ticket.insert()
	except Exception:
		frappe.log_error("Shop assistant: ticket creation failed", frappe.get_traceback())
		out = contact_team(ctx, f"{subject} — {description}", email)
		out["note"] = _("Le ticket n'a pas pu être créé ; la demande est partie à l'équipe par message.")
		return out
	if conversation:
		conversation.status = "Escalated"
		conversation.escalated_to = "Helpdesk"
		conversation.helpdesk_ticket = ticket.name
		conversation.escalation_note = subject
	_post_to_raven(
		_team_channel(settings),
		f"**Assistant boutique** — ticket {ticket.name} ouvert pour {escape_html(_customer_label(ctx, email))} : {escape_html(subject)}",
	)
	_notify_customer(
		email,
		_("Votre demande {0} est enregistrée").format(ticket.name),
		_("Bonjour,<br><br>Votre demande « {0} » est enregistrée sous le numéro {1}. Notre équipe la traite et vous répond à cette adresse.").format(
			escape_html(subject), ticket.name
		),
		ctx,
	)
	return {
		"escalated": True,
		"ticket": ticket.name,
		"note": _("Le ticket {0} est ouvert au nom du client ; l'équipe lui répondra par email. Donne-lui le numéro.").format(ticket.name),
	}
