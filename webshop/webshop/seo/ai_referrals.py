# //// Neoffice — added file (no upstream equivalent): which visits of the shop came from an AI
# //// assistant, the measure of the GEO work (neoffice-maintenance#691, lot 4).
"""An assistant that cites a shop links to it: the visit carries the assistant's host as its
referrer, or its name as `utm_source` (ChatGPT adds `?utm_source=chatgpt.com` to the links it
gives). Frappe records both in Web Page View once view tracking is on (Website Settings, off by
default); the report `Visits From AI Assistants` counts them."""

from urllib.parse import urlparse

# the hosts an assistant's links come from, by assistant; a utm_source may also carry the bare name
ASSISTANTS = {
	"ChatGPT": ("chatgpt.com", "chat.openai.com"),
	"Perplexity": ("perplexity.ai",),
	"Gemini": ("gemini.google.com", "bard.google.com"),
	"Copilot": ("copilot.microsoft.com", "copilot.cloud.microsoft"),
	"Claude": ("claude.ai",),
	"Mistral": ("chat.mistral.ai",),
	"DeepSeek": ("chat.deepseek.com",),
	"Meta AI": ("meta.ai",),
}


def assistant_of(referrer: str | None = None, source: str | None = None) -> str | None:
	"""The assistant a visit came from, read off its referrer's host or its utm_source; None for
	any other visit."""
	candidates = []
	if referrer:
		address = referrer if "://" in referrer else "//" + referrer
		candidates.append(urlparse(address).netloc.lower().split(":")[0])
	if source:
		candidates.append(source.strip().lower())
	for name, hosts in ASSISTANTS.items():
		for candidate in candidates:
			if not candidate:
				continue
			if candidate == name.lower() or any(candidate == host or candidate.endswith("." + host) for host in hosts):
				return name
	return None


def like_patterns() -> list[str]:
	"""SQL LIKE patterns that pre-select the views worth reading (the rest is read in Python)."""
	return sorted({f"%{host}%" for hosts in ASSISTANTS.values() for host in hosts})
