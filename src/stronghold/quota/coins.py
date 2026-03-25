"""Coin-based quota ledger.

Normalizes heterogeneous model costs into a single coin ledger while
preserving raw token telemetry for auditing and analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from stronghold.quota.billing import cycle_key
from stronghold.types.errors import QuotaExhaustedError

MICROCHIPS_PER_COPPER = 1_000
DEFAULT_BANKING_RATE_PCT = 40  # free copper banks at 40% face value; super-admin adjustable
DENOMINATION_FACTORS: dict[str, int] = {
    "copper": 1,
    "silver": 10,
    "gold": 100,
    "platinum": 500,
    "diamond": 1_000,
}

DEFAULT_PRICING_VERSION = "default-v1"


def _decimal(value: object, default: str = "0") -> Decimal:
    """Safely coerce unknown config values into a Decimal."""
    if value in (None, ""):
        return Decimal(default)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def coins_to_microchips(amount: object, denomination: str = "copper") -> int:
    """Convert display coin units into the integer ledger primitive."""
    denom = (denomination or "copper").strip().lower()
    factor = DENOMINATION_FACTORS.get(denom, 1)
    value = _decimal(amount)
    scaled = value * Decimal(factor) * Decimal(MICROCHIPS_PER_COPPER)
    return int(scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_microchips(microchips: int) -> dict[str, object]:
    """Render microchips in the largest human-friendly coin denomination."""
    abs_value = abs(int(microchips))
    chosen = "copper"
    chosen_factor = 1
    for name, factor in DENOMINATION_FACTORS.items():
        if abs_value >= factor * MICROCHIPS_PER_COPPER:
            chosen = name
            chosen_factor = factor
    amount = Decimal(abs_value) / Decimal(chosen_factor * MICROCHIPS_PER_COPPER)
    rendered = float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    if microchips < 0:
        rendered *= -1
    return {
        "amount": rendered,
        "denomination": chosen,
        "microchips": int(microchips),
    }


@dataclass(frozen=True)
class CoinQuote:
    """Resolved cost for a single request."""

    base_microchips: int
    input_rate_microchips: int
    output_rate_microchips: int
    charged_microchips: int
    pricing_version: str
    model_key: str
    provider: str
    denomination: str  # minimum denomination required to use this model


class NoOpCoinLedger:
    """Fallback ledger for dev modes without PostgreSQL."""

    async def ensure_can_afford(
        self,
        *,
        org_id: str,
        team_id: str,
        user_id: str,
        model_used: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, object]:
        q = self.quote(model_used, provider, input_tokens, output_tokens)
        return {"allowed": True, "wallets": [], "quote": q}

    async def charge_usage(
        self,
        *,
        request_id: str,
        org_id: str,
        team_id: str,
        user_id: str,
        model_used: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, object]:
        quote = self.quote(model_used, provider, input_tokens, output_tokens)
        return {
            "charged_microchips": quote.charged_microchips,
            "pricing_version": quote.pricing_version,
            "wallet_count": 0,
        }

    async def list_wallets(
        self, *, org_id: str = "", owner_type: str = "", owner_id: str = ""
    ) -> list[dict[str, object]]:
        return []

    async def get_banking_rate(self) -> int:
        return DEFAULT_BANKING_RATE_PCT

    async def set_banking_rate(self, pct: int) -> None:
        raise RuntimeError("Coin config requires PostgreSQL")

    async def upsert_wallet(self, **_: Any) -> dict[str, object]:
        raise RuntimeError("Coin wallets require PostgreSQL")

    async def get_subject_summary(
        self, *, org_id: str, team_id: str, user_id: str
    ) -> dict[str, object]:
        return {"wallets": [], "denominations": self.denominations()}

    def quote(
        self,
        model_used: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
    ) -> CoinQuote:
        return _resolve_quote({}, {}, model_used, provider, input_tokens, output_tokens)

    @staticmethod
    def denominations() -> dict[str, object]:
        return {
            "microchips_per_copper": MICROCHIPS_PER_COPPER,
            "factors": DENOMINATION_FACTORS,
        }


class PgCoinLedger:
    """PostgreSQL-backed wallet + ledger implementation."""

    def __init__(self, pool: Any, config: Any) -> None:
        self._pool = pool
        self._models = config.models
        self._providers = config.providers

    def quote(
        self,
        model_used: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
    ) -> CoinQuote:
        return _resolve_quote(
            self._models,
            self._providers,
            model_used,
            provider,
            input_tokens,
            output_tokens,
        )

    async def ensure_can_afford(
        self,
        *,
        org_id: str,
        team_id: str,
        user_id: str,
        model_used: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, object]:
        quote = self.quote(model_used, provider, input_tokens, output_tokens)
        wallets = await self._load_wallets(org_id=org_id, team_id=team_id, user_id=user_id)
        model_tier = DENOMINATION_FACTORS.get(quote.denomination, 1)

        # Org/team wallets are budget ceilings — check balance, no denomination filter
        for w in wallets:
            if w["owner_type"] in ("org", "team"):
                remaining = int(str(w["remaining_microchips"]))
                if remaining < quote.charged_microchips:
                    rem_fmt = format_microchips(remaining)
                    req_fmt = format_microchips(quote.charged_microchips)
                    raise QuotaExhaustedError(
                        f"{w['owner_type']}:{w['owner_id']} budget exceeded: "
                        f"{rem_fmt['amount']} {rem_fmt['denomination']} remaining, "
                        f"need {req_fmt['amount']} {req_fmt['denomination']}"
                    )

        # User wallets are denomination-locked — must have tier >= model's tier
        user_wallets = [w for w in wallets if w["owner_type"] == "user"]
        eligible = [
            w for w in user_wallets
            if DENOMINATION_FACTORS.get(str(w["denomination"]), 1) >= model_tier
        ]

        if user_wallets and not eligible:
            raise QuotaExhaustedError(
                f"Model {quote.model_key} requires {quote.denomination} denomination "
                f"or higher. Exchange your coins at the Currency Exchange to unlock "
                f"higher-tier models, or purchase silver/gold/diamond coins."
            )

        affordable = [
            w for w in eligible
            if int(str(w["remaining_microchips"])) >= quote.charged_microchips
        ]
        if eligible and not affordable:
            best = max(eligible, key=lambda w: int(str(w["remaining_microchips"])))
            rem_fmt = format_microchips(int(str(best["remaining_microchips"])))
            req_fmt = format_microchips(quote.charged_microchips)
            raise QuotaExhaustedError(
                f"Insufficient {best['denomination']} balance: "
                f"{rem_fmt['amount']} {rem_fmt['denomination']} remaining, "
                f"need {req_fmt['amount']} {req_fmt['denomination']}"
            )

        return {
            "allowed": True,
            "wallets": wallets,
            "quote": {
                "charged_microchips": quote.charged_microchips,
                "display": format_microchips(quote.charged_microchips),
                "pricing_version": quote.pricing_version,
                "model_key": quote.model_key,
                "provider": quote.provider,
                "denomination": quote.denomination,
            },
        }

    async def charge_usage(
        self,
        *,
        request_id: str,
        org_id: str,
        team_id: str,
        user_id: str,
        model_used: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, object]:
        quote = self.quote(model_used, provider, input_tokens, output_tokens)
        wallets = await self._load_wallets(org_id=org_id, team_id=team_id, user_id=user_id)
        if not wallets:
            return {
                "charged_microchips": quote.charged_microchips,
                "pricing_version": quote.pricing_version,
                "wallet_count": 0,
            }

        model_tier = DENOMINATION_FACTORS.get(quote.denomination, 1)

        # Org/team wallets are budget ceilings — always record the debit
        budget_wallets = [w for w in wallets if w["owner_type"] in ("org", "team")]

        # User wallets: pick the LOWEST denomination that qualifies and can afford it.
        # This spends cheaper coins first, preserving higher-tier coins for expensive models.
        user_wallets = [w for w in wallets if w["owner_type"] == "user"]
        eligible = sorted(
            (w for w in user_wallets
             if DENOMINATION_FACTORS.get(str(w["denomination"]), 1) >= model_tier),
            key=lambda w: DENOMINATION_FACTORS.get(str(w["denomination"]), 1),
        )
        target = None
        for w in eligible:
            if int(str(w["remaining_microchips"])) >= quote.charged_microchips:
                target = w
                break

        to_charge = budget_wallets + ([target] if target else [])
        if not to_charge:
            return {
                "charged_microchips": quote.charged_microchips,
                "pricing_version": quote.pricing_version,
                "wallet_count": 0,
            }

        async with self._pool.acquire() as conn, conn.transaction():
            for wallet in to_charge:
                await conn.execute(
                    """INSERT INTO coin_ledger_entries
                           (wallet_id, cycle_key, entry_kind, delta_microchips,
                            request_id, org_id, team_id, user_id, model_used, provider,
                            input_tokens, output_tokens, pricing_version,
                            base_rate_microchips, input_rate_microchips, output_rate_microchips)
                           VALUES ($1,$2,'debit',$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)""",
                    wallet["id"],
                    wallet["cycle_key"],
                    -quote.charged_microchips,
                    request_id,
                    org_id,
                    team_id,
                    user_id,
                    model_used,
                    provider or quote.provider,
                    input_tokens,
                    output_tokens,
                    quote.pricing_version,
                    quote.base_microchips,
                    quote.input_rate_microchips,
                    quote.output_rate_microchips,
                )
        return {
            "charged_microchips": quote.charged_microchips,
            "pricing_version": quote.pricing_version,
            "wallet_count": len(to_charge),
            "charged_denomination": str(target["denomination"]) if target else "",
        }

    async def upsert_wallet(
        self,
        *,
        owner_type: str,
        owner_id: str,
        org_id: str,
        team_id: str,
        label: str,
        billing_cycle: str,
        denomination: str = "copper",
        budget_microchips: int,
        hard_limit_microchips: int,
        soft_limit_ratio: float,
        overage_allowed: bool,
        active: bool,
    ) -> dict[str, object]:
        owner_type = owner_type.strip().lower()
        if owner_type not in {"user", "team", "org"}:
            raise ValueError("owner_type must be user, team, or org")
        billing_cycle = (billing_cycle or "monthly").strip().lower()
        if billing_cycle not in {"daily", "monthly"}:
            raise ValueError("billing_cycle must be daily or monthly")
        denomination = (denomination or "copper").strip().lower()
        if denomination not in DENOMINATION_FACTORS:
            raise ValueError(f"denomination must be one of {list(DENOMINATION_FACTORS)}")
        hard_limit = hard_limit_microchips or budget_microchips
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO coin_wallets
                   (owner_type, owner_id, org_id, team_id, label, billing_cycle,
                    denomination, budget_microchips, hard_limit_microchips, soft_limit_ratio,
                    overage_allowed, active, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,NOW())
                   ON CONFLICT (owner_type, owner_id, denomination) DO UPDATE SET
                     org_id = EXCLUDED.org_id,
                     team_id = EXCLUDED.team_id,
                     label = EXCLUDED.label,
                     billing_cycle = EXCLUDED.billing_cycle,
                     budget_microchips = EXCLUDED.budget_microchips,
                     hard_limit_microchips = EXCLUDED.hard_limit_microchips,
                     soft_limit_ratio = EXCLUDED.soft_limit_ratio,
                     overage_allowed = EXCLUDED.overage_allowed,
                     active = EXCLUDED.active,
                     updated_at = NOW()
                   RETURNING *""",
                owner_type,
                owner_id,
                org_id,
                team_id,
                label,
                billing_cycle,
                denomination,
                budget_microchips,
                hard_limit,
                soft_limit_ratio,
                overage_allowed,
                active,
            )
        return await self._hydrate_wallet(row)

    async def list_wallets(
        self,
        *,
        org_id: str = "",
        owner_type: str = "",
        owner_id: str = "",
    ) -> list[dict[str, object]]:
        clauses = []
        params: list[object] = []
        if org_id:
            params.append(org_id)
            clauses.append(f"org_id = ${len(params)}")
        if owner_type:
            params.append(owner_type)
            clauses.append(f"owner_type = ${len(params)}")
        if owner_id:
            params.append(owner_id)
            clauses.append(f"owner_id = ${len(params)}")
        sql = "SELECT * FROM coin_wallets"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY owner_type, owner_id"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [await self._hydrate_wallet(row) for row in rows]

    async def get_subject_summary(
        self, *, org_id: str, team_id: str, user_id: str
    ) -> dict[str, object]:
        wallets = await self._load_wallets(org_id=org_id, team_id=team_id, user_id=user_id)
        return {"wallets": wallets, "denominations": self.denominations()}

    @staticmethod
    def denominations() -> dict[str, object]:
        return {
            "microchips_per_copper": MICROCHIPS_PER_COPPER,
            "factors": DENOMINATION_FACTORS,
        }

    async def get_banking_rate(self) -> int:
        """Return the current banking rate (percent). Super-admin adjustable."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT value FROM coin_config WHERE key = 'banking_rate_pct'"
            )
        return int(row) if row else DEFAULT_BANKING_RATE_PCT

    async def set_banking_rate(self, pct: int) -> None:
        """Set the banking rate. Requires 1-100."""
        if not 1 <= pct <= 100:
            raise ValueError("banking_rate_pct must be between 1 and 100")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO coin_config (key, value, updated_at)
                   VALUES ('banking_rate_pct', $1, NOW())
                   ON CONFLICT (key) DO UPDATE SET value = $1, updated_at = NOW()""",
                str(pct),
            )

    async def _load_wallets(
        self, *, org_id: str, team_id: str, user_id: str
    ) -> list[dict[str, object]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM coin_wallets
                   WHERE active = TRUE AND (
                     (owner_type = 'user' AND owner_id = $1)
                     OR (owner_type = 'team' AND owner_id = $2)
                     OR (owner_type = 'org' AND owner_id = $3)
                   )
                   ORDER BY CASE owner_type
                     WHEN 'org' THEN 1
                     WHEN 'team' THEN 2
                     ELSE 3
                   END""",
                user_id,
                team_id,
                org_id,
            )
        return [await self._hydrate_wallet(row) for row in rows]

    async def _hydrate_wallet(self, row: Any) -> dict[str, object]:
        ck = cycle_key(row["billing_cycle"])
        async with self._pool.acquire() as conn:
            agg = await conn.fetchrow(
                """SELECT
                     COALESCE(-SUM(CASE WHEN delta_microchips < 0
                                        THEN delta_microchips END), 0) AS used,
                     COALESCE(SUM(CASE WHEN delta_microchips > 0
                                       THEN delta_microchips END), 0) AS credited
                   FROM coin_ledger_entries
                   WHERE wallet_id = $1 AND cycle_key = $2""",
                row["id"],
                ck,
            )
        used_microchips = int(agg["used"] or 0)
        credited_microchips = int(agg["credited"] or 0)
        hard_limit = int(row["hard_limit_microchips"] or row["budget_microchips"] or 0)
        effective_budget = hard_limit + credited_microchips
        remaining = max(effective_budget - used_microchips, 0)
        soft_limit = int(Decimal(str(effective_budget)) * Decimal(str(row["soft_limit_ratio"] or 0)))
        return {
            "id": row["id"],
            "owner_type": row["owner_type"],
            "owner_id": row["owner_id"],
            "org_id": row["org_id"],
            "team_id": row["team_id"],
            "label": row["label"],
            "billing_cycle": row["billing_cycle"],
            "denomination": row.get("denomination", "copper") or "copper",
            "budget_microchips": int(row["budget_microchips"] or 0),
            "budget_display": format_microchips(int(row["budget_microchips"] or 0)),
            "hard_limit_microchips": hard_limit,
            "hard_limit_display": format_microchips(hard_limit),
            "credited_microchips": credited_microchips,
            "credited_display": format_microchips(credited_microchips),
            "effective_budget_microchips": effective_budget,
            "effective_budget_display": format_microchips(effective_budget),
            "used_microchips": used_microchips,
            "used_display": format_microchips(used_microchips),
            "remaining_microchips": remaining,
            "remaining_display": format_microchips(remaining),
            "soft_limit_microchips": soft_limit,
            "soft_limit_display": format_microchips(soft_limit),
            "soft_limit_ratio": float(row["soft_limit_ratio"] or 0),
            "overage_allowed": bool(row["overage_allowed"]),
            "active": bool(row["active"]),
            "cycle_key": ck,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }


def _resolve_denomination(
    model_raw: dict[str, Any], base: int, in_rate: int, out_rate: int
) -> str:
    """Determine the minimum denomination required to use a model.

    Explicit ``coin_denomination`` in model config takes precedence.
    Otherwise, derives from the typical request cost (base + 1K input + 1K output):
    the highest denomination whose unit threshold the cost meets.
    """
    explicit = str(model_raw.get("coin_denomination", "") or "").strip().lower()
    if explicit and explicit in DENOMINATION_FACTORS:
        return explicit
    typical = base + in_rate + out_rate
    resolved = "copper"
    for name, factor in DENOMINATION_FACTORS.items():
        if typical >= factor * MICROCHIPS_PER_COPPER:
            resolved = name
    return resolved


def _resolve_quote(
    models: dict[str, Any],
    providers: dict[str, Any],
    model_used: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
) -> CoinQuote:
    model_raw, model_key = _find_model(models, model_used)
    provider_name = provider or _extract_provider(model_raw, providers, model_used)
    base_microchips = _rate_value(model_raw, "coin_cost_base", default="0")
    input_rate_microchips = _rate_value(model_raw, "coin_cost_per_1k_input", default="1")
    output_rate_microchips = _rate_value(model_raw, "coin_cost_per_1k_output", default="2")
    prov_raw = providers.get(provider_name, {})
    prov_dict = prov_raw if isinstance(prov_raw, dict) else {}
    pricing_version = str(
        (model_raw or {}).get("coin_pricing_version")
        or prov_dict.get("coin_pricing_version")
        or DEFAULT_PRICING_VERSION
    )
    denomination = _resolve_denomination(
        model_raw, base_microchips, input_rate_microchips, output_rate_microchips
    )
    in_cost = Decimal(max(input_tokens, 0)) / Decimal(1000) * Decimal(input_rate_microchips)
    out_cost = Decimal(max(output_tokens, 0)) / Decimal(1000) * Decimal(output_rate_microchips)
    total = Decimal(base_microchips) + in_cost + out_cost
    charged = int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return CoinQuote(
        base_microchips=base_microchips,
        input_rate_microchips=input_rate_microchips,
        output_rate_microchips=output_rate_microchips,
        charged_microchips=max(charged, 0),
        pricing_version=pricing_version,
        model_key=model_key,
        provider=provider_name,
        denomination=denomination,
    )


def _find_model(models: dict[str, Any], model_used: str) -> tuple[dict[str, Any], str]:
    for key, raw in models.items():
        if key == model_used:
            return raw if isinstance(raw, dict) else {}, key
        if isinstance(raw, dict) and raw.get("litellm_id") == model_used:
            return raw, key
    return {}, model_used


def _extract_provider(
    model_raw: dict[str, Any],
    providers: dict[str, Any],
    model_used: str,
) -> str:
    provider = str(model_raw.get("provider", "") or "")
    if provider:
        return provider
    if "/" in model_used:
        prefix = model_used.split("/", 1)[0]
        if prefix in providers:
            return prefix
    return ""


def _rate_value(model_raw: dict[str, Any], field: str, *, default: str) -> int:
    micro_field = f"{field}_microchips"
    if micro_field in model_raw:
        return int(_decimal(model_raw.get(micro_field), default="0"))
    denom_field = f"{field}_denomination"
    denom = str(model_raw.get(denom_field, "copper") or "copper")
    return coins_to_microchips(model_raw.get(field, default), denom)
