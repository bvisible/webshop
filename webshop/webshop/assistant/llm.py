# //// Neoffice — added file (shop assistant, no upstream equivalent).
"""The one place that talks to a language model.

Any OpenAI-compatible endpoint will do (`/v1/chat/completions` with `tools`).
Nothing else in the assistant knows a URL or a key: tests replace
`complete()` with a fake and exercise everything around it.
"""

import time

import frappe
import requests
from frappe import _
from frappe.utils import cint

DEFAULT_TIMEOUT = 25
DEFAULT_MODEL = "nora"


# //// Neoffice — the one failure that means "the model is down" (lot A of the 2026-10-30 audit).
# //// `send` used to arm the shop-wide outage flag on ANY exception, so a database error caused by one
# //// visitor's two parallel requests switched the assistant off for everybody for two minutes.
class ModelUnavailable(Exception):
	"""The model could not be reached, refused, or answered in a form that cannot be read.

	Raised by `complete()` and by nothing else: it is the only failure that sends the visitors to the
	answering machine for everyone. A fault of ours stays a fault of ours.
	"""


def config(settings=None):
	"""Endpoint, key and model: the shop's own when set, otherwise Nora's.

	Nora keeps its LLM in site config (`nora.nora_settings`); a shop on an
	instance without the nora app has to fill its own fields.
	"""
	settings = settings or frappe.get_cached_doc("Webshop Settings")
	base_url = (settings.get("assistant_llm_base_url") or "").strip()
	model = (settings.get("assistant_llm_model") or "").strip()
	api_key = ""
	if base_url:
		api_key = settings.get_password("assistant_llm_api_key", raise_exception=False) or ""
	elif "nora" in frappe.get_installed_apps():
		try:
			from nora.nora_settings import get_llm_config

			nora = get_llm_config() or {}
			base_url = (nora.get("base_url") or "").strip()
			api_key = nora.get("api_key") or ""
			model = model or (nora.get("model") or "")
		except Exception:
			frappe.log_error("Shop assistant: Nora LLM config unavailable", frappe.get_traceback())
	if not base_url:
		frappe.throw(_("The assistant has no language model configured."))
	return frappe._dict(
		base_url=base_url.rstrip("/"),
		api_key=api_key,
		model=model or DEFAULT_MODEL,
		timeout=cint(settings.get("assistant_llm_timeout")) or DEFAULT_TIMEOUT,
		# //// Neoffice — lot C of the 2026-10-30 audit: empty or 0 sends nothing
		priority=cint(settings.get("assistant_llm_priority")) or None,
	)


def complete(messages, tools=None, settings=None, temperature=0.2, max_tokens=700):
	"""One round trip. Returns content, tool calls, usage and timing."""
	try:
		cfg = config(settings)
	except frappe.ValidationError as error:  # nothing configured: as unavailable as a model that is down
		raise ModelUnavailable(str(error)) from error
	payload = {
		"model": cfg.model,
		"messages": messages,
		"temperature": temperature,
		"max_tokens": max_tokens,
	}
	if tools:
		payload["tools"] = tools
		payload["tool_choice"] = "auto"
	# //// Neoffice — a model shared with the team's own use may serve its requests by priority (vLLM's `priority`: the
	# //// lower the number, the sooner). The shop sets a high one so that anonymous visitors never delay the team; the
	# //// field is not sent when empty, because an endpoint without that scheduling refuses it (lot C of the 2026-10-30 audit)
	if cfg.priority:
		payload["priority"] = cfg.priority
	headers = {"Content-Type": "application/json"}
	if cfg.api_key:
		headers["Authorization"] = f"Bearer {cfg.api_key}"
	started = time.monotonic()
	try:
		response = requests.post(
			f"{cfg.base_url}/chat/completions", json=payload, headers=headers, timeout=cfg.timeout
		)
		response.raise_for_status()
		data = response.json()
		choice = (data.get("choices") or [{}])[0]
		message = choice.get("message") or {}
		usage = data.get("usage") or {}
		return frappe._dict(
			content=message.get("content") or "",
			tool_calls=message.get("tool_calls") or [],
			finish_reason=choice.get("finish_reason"),
			prompt_tokens=cint(usage.get("prompt_tokens")),
			completion_tokens=cint(usage.get("completion_tokens")),
			model=data.get("model") or cfg.model,
			duration_ms=int((time.monotonic() - started) * 1000),
		)
	except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
		# transport, HTTP status, a body that is not JSON, a JSON that is not an answer: all the model's
		raise ModelUnavailable(f"{type(error).__name__}: {error}") from error
