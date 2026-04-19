"""NewsletterSubscriber (scaffold) — submit subscription forms.

Submits an email to a configured subscription endpoint. Most newsletter
providers accept POST <url> { email: ..., name: ... }; some have extra
fields. The constructor takes a `template` dict that's merged with the
required `email` field on each invoke().

Bring-your-own-confirmation: if the newsletter requires a
double-opt-in confirmation, the operator handles that out-of-band (the
confirmation lands in their email, not the Conduit's).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .base import Tool, ToolMode


logger = logging.getLogger("turing.runtime.tools.newsletter")


class NewsletterSubscriber:
    name = "newsletter_subscriber"
    mode = ToolMode.SUBSCRIBE

    def __init__(
        self,
        *,
        endpoint: str,
        email: str,
        template: dict[str, Any] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if not (endpoint and email):
            raise ValueError("NewsletterSubscriber requires endpoint, email")
        self._endpoint = endpoint
        self._email = email
        self._template = dict(template or {})
        self._client = client or httpx.Client(timeout=20.0)

    def invoke(
        self,
        *,
        list_name: str | None = None,
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"email": self._email}
        if list_name is not None:
            body["list"] = list_name
        body.update(self._template)
        if extra_fields:
            body.update(extra_fields)
        response = self._client.post(self._endpoint, json=body)
        response.raise_for_status()
        try:
            return response.json()
        except ValueError:
            return {"status": response.status_code}
