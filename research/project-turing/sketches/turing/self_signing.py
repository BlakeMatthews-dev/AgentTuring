"""Bootstrap seed registry + signed audit. See specs/bootstrap-seed-registry.md.

HMAC-SHA256 signing of the bootstrap-complete memory, and verification
on conduit startup. Seed reuse detection via self_bootstrap_seeds table.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime


class BootstrapTamperDetected(Exception):
    def __init__(self, self_id: str) -> None:
        self.self_id = self_id
        super().__init__(f"bootstrap signature tamper detected for {self_id}")


class SeedReused(Exception):
    def __init__(self, seed: int, existing_self_id: str) -> None:
        self.seed = seed
        self.existing_self_id = existing_self_id
        super().__init__(f"seed {seed} already used by {existing_self_id}")


def _signing_key() -> bytes:
    key = os.environ.get("OPERATOR_SIGNING_KEY", "")
    if not key:
        raise RuntimeError("OPERATOR_SIGNING_KEY env var is not set")
    return key.encode()


def sign_bootstrap(self_id: str, seed: int, created_at: datetime, content: str) -> str:
    canonical = f"{self_id}|{seed}|{created_at.isoformat()}|{content}"
    return hmac.new(_signing_key(), canonical.encode(), hashlib.sha256).hexdigest()


def verify_bootstrap_signature(
    self_id: str,
    seed: int,
    created_at: datetime,
    content: str,
    signature: str,
) -> bool:
    expected = sign_bootstrap(self_id, seed, created_at, content)
    return hmac.compare_digest(expected, signature)


def check_bootstrap_signature(
    self_id: str,
    seed: int,
    created_at: datetime,
    content: str,
    signature: str,
) -> None:
    if not verify_bootstrap_signature(self_id, seed, created_at, content, signature):
        raise BootstrapTamperDetected(self_id)
