"""Post a note to Slack with ``chat.postMessage``.

The HTTP call goes through an injectable ``transport`` so tests never touch
the network. Nothing in this module runs unless the CLI is given ``--send``.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Callable

API_URL = "https://slack.com/api/chat.postMessage"
MAX_TEXT = 39000  # Slack rejects messages over 40,000 characters

Transport = Callable[[str, dict, bytes], dict]


class SlackError(RuntimeError):
    pass


def http_transport(url: str, headers: dict, body: bytes) -> dict:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def build_payload(channel: str, text: str) -> dict:
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT].rstrip() + "\n… (truncated)"
    return {"channel": channel, "text": text, "unfurl_links": False}


def post_message(channel: str, text: str, token: str, transport: Transport = http_transport) -> dict:
    if not token:
        raise SlackError("no Slack token: set SLACK_BOT_TOKEN to a bot token with the chat:write scope")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    try:
        reply = transport(API_URL, headers, json.dumps(build_payload(channel, text)).encode("utf-8"))
    except OSError as exc:
        raise SlackError(f"could not reach Slack: {exc}") from exc
    if not reply.get("ok"):
        raise SlackError(f"Slack rejected the message: {reply.get('error', 'unknown error')}")
    return reply
