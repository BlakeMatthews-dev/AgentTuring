"""Integration tests for PgCoinLedger against a real PostgreSQL instance."""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest

try:
    import asyncpg

    _has_asyncpg = True
except ImportError:
    _has_asyncpg = False

from stronghold.quota.coins import (
    DEFAULT_BANKING_RATE_PCT,
    DENOMINATION_FACTORS,
    MICROCHIPS_PER_COPPER,
    PgCoinLedger,
    coins_to_microchips,
)
from stronghold.types.errors import QuotaExhaustedError

PG_DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://stronghold:stronghold@localhost:5432/stronghold",
)


async def _can_connect() -> bool:
    if not _has_asyncpg:
        return False
    try:
        conn = await asyncpg.connect(PG_DSN, timeout=3)
        await conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _has_asyncpg, reason="asyncpg not installed")

# ── Schema DDL (merged from migrations 009 + 010) ──────────────────────
_SCHEMA_SQL = """\
-- coin_wallets (009 + 010 merged)
CREATE TABLE IF NOT EXISTS coin_wallets (
    id                    SERIAL PRIMARY KEY,
    owner_type            TEXT NOT NULL CHECK (owner_type IN ('user', 'team', 'org')),
    owner_id              TEXT NOT NULL,
    org_id                TEXT NOT NULL DEFAULT '',
    team_id               TEXT NOT NULL DEFAULT '',
    label                 TEXT NOT NULL DEFAULT '',
    billing_cycle         TEXT NOT NULL DEFAULT 'monthly'
                          CHECK (billing_cycle IN ('daily', 'monthly')),
    denomination          TEXT NOT NULL DEFAULT 'copper',
    budget_microchips     BIGINT NOT NULL DEFAULT 0,
    hard_limit_microchips BIGINT NOT NULL DEFAULT 0,
    soft_limit_ratio      NUMERIC(5,4) NOT NULL DEFAULT 0.8000,
    overage_allowed       BOOLEAN NOT NULL DEFAULT FALSE,
    active                BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_type, owner_id, denomination)
);

-- coin_ledger_entries (009 renamed)
CREATE TABLE IF NOT EXISTS coin_ledger_entries (
    id                      SERIAL PRIMARY KEY,
    wallet_id               INTEGER NOT NULL REFERENCES coin_wallets(id) ON DELETE CASCADE,
    cycle_key               TEXT NOT NULL,
    entry_kind              TEXT NOT NULL DEFAULT 'debit'
                            CHECK (entry_kind IN ('debit', 'credit', 'adjustment')),
    delta_microchips        BIGINT NOT NULL,
    request_id              TEXT NOT NULL DEFAULT '',
    org_id                  TEXT NOT NULL DEFAULT '',
    team_id                 TEXT NOT NULL DEFAULT '',
    user_id                 TEXT NOT NULL DEFAULT '',
    model_used              TEXT NOT NULL DEFAULT '',
    provider                TEXT NOT NULL DEFAULT '',
    input_tokens            BIGINT NOT NULL DEFAULT 0,
    output_tokens           BIGINT NOT NULL DEFAULT 0,
    pricing_version         TEXT NOT NULL DEFAULT 'default-v1',
    base_rate_microchips    BIGINT NOT NULL DEFAULT 0,
    input_rate_microchips   BIGINT NOT NULL DEFAULT 0,
    output_rate_microchips  BIGINT NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- coin_config (010)
CREATE TABLE IF NOT EXISTS coin_config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def _make_config(
    models: dict | None = None,
    providers: dict | None = None,
) -> SimpleNamespace:
    """Build a minimal config object with .models and .providers."""
    return SimpleNamespace(
        models=models
        or {
            "test-small": {
                "provider": "test_provider",
                "coin_cost_base": "0",
                "coin_cost_per_1k_input": "1",
                "coin_cost_per_1k_output": "2",
            },
            "test-large": {
                "provider": "test_provider",
                "coin_cost_base": "10",
                "coin_cost_per_1k_input": "50",
                "coin_cost_per_1k_output": "100",
                "coin_denomination": "gold",
            },
        },
        providers=providers
        or {
            "test_provider": {"status": "active"},
        },
    )


@pytest.fixture
async def pg_pool():
    """Create an asyncpg pool and set up the schema, shared across the module."""
    if not _has_asyncpg:
        pytest.skip("asyncpg not installed")
    try:
        pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=5, timeout=5)
    except Exception as exc:
        pytest.skip(f"Cannot connect to PostgreSQL: {exc}")
        return

    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS coin_ledger_entries CASCADE")
        await conn.execute("DROP TABLE IF EXISTS coin_wallets CASCADE")
        await conn.execute("DROP TABLE IF EXISTS coin_config CASCADE")
        await conn.execute(_SCHEMA_SQL)
    yield pool
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS coin_ledger_entries CASCADE")
        await conn.execute("DROP TABLE IF EXISTS coin_wallets CASCADE")
        await conn.execute("DROP TABLE IF EXISTS coin_config CASCADE")
    await pool.close()


@pytest.fixture
def ledger(pg_pool) -> PgCoinLedger:
    return PgCoinLedger(pg_pool, _make_config())


# ── quote() ─────────────────────────────────────────────────────────────


class TestQuote:
    def test_quote_known_model(self, ledger: PgCoinLedger):
        q = ledger.quote("test-small", "test_provider", 1000, 1000)
        assert q.model_key == "test-small"
        assert q.provider == "test_provider"
        assert q.base_microchips == 0
        assert q.input_rate_microchips == coins_to_microchips("1", "copper")
        assert q.output_rate_microchips == coins_to_microchips("2", "copper")
        assert q.charged_microchips > 0

    def test_quote_unknown_model_uses_defaults(self, ledger: PgCoinLedger):
        q = ledger.quote("nonexistent-model", "", 1000, 500)
        assert q.model_key == "nonexistent-model"
        assert q.charged_microchips > 0
        assert q.pricing_version == "default-v1"

    def test_quote_gold_denomination(self, ledger: PgCoinLedger):
        q = ledger.quote("test-large", "test_provider", 1000, 1000)
        assert q.denomination == "gold"

    def test_quote_zero_tokens(self, ledger: PgCoinLedger):
        q = ledger.quote("test-small", "test_provider", 0, 0)
        assert q.charged_microchips == 0


# ── denominations() ─────────────────────────────────────────────────────


class TestDenominations:
    def test_denominations_static(self, ledger: PgCoinLedger):
        d = ledger.denominations()
        assert d["microchips_per_copper"] == MICROCHIPS_PER_COPPER
        assert d["factors"] == DENOMINATION_FACTORS


# ── upsert_wallet() ─────────────────────────────────────────────────────


class TestUpsertWallet:
    async def test_create_wallet(self, ledger: PgCoinLedger):
        w = await ledger.upsert_wallet(
            owner_type="user",
            owner_id="u-1",
            org_id="org-1",
            team_id="team-1",
            label="Test Wallet",
            billing_cycle="monthly",
            denomination="copper",
            budget_microchips=100_000,
            hard_limit_microchips=100_000,
            soft_limit_ratio=0.8,
            overage_allowed=False,
            active=True,
        )
        assert w["owner_type"] == "user"
        assert w["owner_id"] == "u-1"
        assert w["denomination"] == "copper"
        assert w["budget_microchips"] == 100_000
        assert w["active"] is True
        assert w["remaining_microchips"] == 100_000

    async def test_upsert_updates_existing(self, ledger: PgCoinLedger):
        await ledger.upsert_wallet(
            owner_type="user",
            owner_id="u-2",
            org_id="org-1",
            team_id="team-1",
            label="v1",
            billing_cycle="monthly",
            denomination="copper",
            budget_microchips=50_000,
            hard_limit_microchips=50_000,
            soft_limit_ratio=0.8,
            overage_allowed=False,
            active=True,
        )
        w2 = await ledger.upsert_wallet(
            owner_type="user",
            owner_id="u-2",
            org_id="org-1",
            team_id="team-1",
            label="v2",
            billing_cycle="monthly",
            denomination="copper",
            budget_microchips=200_000,
            hard_limit_microchips=200_000,
            soft_limit_ratio=0.9,
            overage_allowed=True,
            active=True,
        )
        assert w2["label"] == "v2"
        assert w2["budget_microchips"] == 200_000
        assert w2["overage_allowed"] is True

    async def test_upsert_invalid_owner_type(self, ledger: PgCoinLedger):
        with pytest.raises(ValueError, match="owner_type"):
            await ledger.upsert_wallet(
                owner_type="robot",
                owner_id="r-1",
                org_id="org-1",
                team_id="team-1",
                label="bad",
                billing_cycle="monthly",
                denomination="copper",
                budget_microchips=1000,
                hard_limit_microchips=1000,
                soft_limit_ratio=0.8,
                overage_allowed=False,
                active=True,
            )

    async def test_upsert_invalid_billing_cycle(self, ledger: PgCoinLedger):
        with pytest.raises(ValueError, match="billing_cycle"):
            await ledger.upsert_wallet(
                owner_type="user",
                owner_id="u-x",
                org_id="org-1",
                team_id="team-1",
                label="bad",
                billing_cycle="yearly",
                denomination="copper",
                budget_microchips=1000,
                hard_limit_microchips=1000,
                soft_limit_ratio=0.8,
                overage_allowed=False,
                active=True,
            )

    async def test_upsert_invalid_denomination(self, ledger: PgCoinLedger):
        with pytest.raises(ValueError, match="denomination"):
            await ledger.upsert_wallet(
                owner_type="user",
                owner_id="u-x",
                org_id="org-1",
                team_id="team-1",
                label="bad",
                billing_cycle="monthly",
                denomination="mythril",
                budget_microchips=1000,
                hard_limit_microchips=1000,
                soft_limit_ratio=0.8,
                overage_allowed=False,
                active=True,
            )

    async def test_upsert_daily_billing_cycle(self, ledger: PgCoinLedger):
        w = await ledger.upsert_wallet(
            owner_type="user",
            owner_id="u-daily",
            org_id="org-1",
            team_id="team-1",
            label="daily",
            billing_cycle="daily",
            denomination="silver",
            budget_microchips=10_000,
            hard_limit_microchips=10_000,
            soft_limit_ratio=0.5,
            overage_allowed=False,
            active=True,
        )
        assert w["billing_cycle"] == "daily"
        assert w["denomination"] == "silver"

    async def test_upsert_hard_limit_defaults_to_budget(self, ledger: PgCoinLedger):
        w = await ledger.upsert_wallet(
            owner_type="user",
            owner_id="u-hl",
            org_id="org-1",
            team_id="team-1",
            label="hl-test",
            billing_cycle="monthly",
            denomination="copper",
            budget_microchips=50_000,
            hard_limit_microchips=0,
            soft_limit_ratio=0.8,
            overage_allowed=False,
            active=True,
        )
        assert w["hard_limit_microchips"] == 50_000


# ── list_wallets() ───────────────────────────────────────────────────────


class TestListWallets:
    async def _seed(self, ledger: PgCoinLedger):
        for owner_type, owner_id, org_id in [
            ("user", "u-a", "org-1"),
            ("user", "u-b", "org-1"),
            ("team", "team-1", "org-1"),
            ("org", "org-1", "org-1"),
            ("user", "u-c", "org-2"),
        ]:
            await ledger.upsert_wallet(
                owner_type=owner_type,
                owner_id=owner_id,
                org_id=org_id,
                team_id="team-1",
                label=f"{owner_type}-{owner_id}",
                billing_cycle="monthly",
                denomination="copper",
                budget_microchips=100_000,
                hard_limit_microchips=100_000,
                soft_limit_ratio=0.8,
                overage_allowed=False,
                active=True,
            )

    async def test_list_all(self, ledger: PgCoinLedger):
        await self._seed(ledger)
        wallets = await ledger.list_wallets()
        assert len(wallets) == 5

    async def test_filter_by_org(self, ledger: PgCoinLedger):
        await self._seed(ledger)
        wallets = await ledger.list_wallets(org_id="org-1")
        assert len(wallets) == 4

    async def test_filter_by_owner_type(self, ledger: PgCoinLedger):
        await self._seed(ledger)
        wallets = await ledger.list_wallets(owner_type="user")
        assert len(wallets) == 3

    async def test_filter_by_owner_id(self, ledger: PgCoinLedger):
        await self._seed(ledger)
        wallets = await ledger.list_wallets(owner_id="u-a")
        assert len(wallets) == 1
        assert wallets[0]["owner_id"] == "u-a"

    async def test_combined_filter(self, ledger: PgCoinLedger):
        await self._seed(ledger)
        wallets = await ledger.list_wallets(org_id="org-1", owner_type="user")
        assert len(wallets) == 2

    async def test_list_empty(self, ledger: PgCoinLedger):
        wallets = await ledger.list_wallets()
        assert wallets == []


# ── get_subject_summary() ───────────────────────────────────────────────


class TestGetSubjectSummary:
    async def test_summary_with_wallets(self, ledger: PgCoinLedger):
        await ledger.upsert_wallet(
            owner_type="user",
            owner_id="u-sum",
            org_id="org-1",
            team_id="team-1",
            label="summary-test",
            billing_cycle="monthly",
            denomination="copper",
            budget_microchips=100_000,
            hard_limit_microchips=100_000,
            soft_limit_ratio=0.8,
            overage_allowed=False,
            active=True,
        )
        summary = await ledger.get_subject_summary(
            org_id="org-1",
            team_id="team-1",
            user_id="u-sum",
        )
        assert "wallets" in summary
        assert "denominations" in summary
        assert len(summary["wallets"]) >= 1
        assert summary["denominations"]["factors"] == DENOMINATION_FACTORS

    async def test_summary_empty(self, ledger: PgCoinLedger):
        summary = await ledger.get_subject_summary(
            org_id="org-none",
            team_id="team-none",
            user_id="u-none",
        )
        assert summary["wallets"] == []


# ── get_banking_rate() / set_banking_rate() ──────────────────────────────


class TestBankingRate:
    async def test_default_rate(self, ledger: PgCoinLedger):
        rate = await ledger.get_banking_rate()
        assert rate == DEFAULT_BANKING_RATE_PCT

    async def test_set_and_get(self, ledger: PgCoinLedger):
        await ledger.set_banking_rate(75)
        assert await ledger.get_banking_rate() == 75

    async def test_set_overwrites(self, ledger: PgCoinLedger):
        await ledger.set_banking_rate(50)
        await ledger.set_banking_rate(90)
        assert await ledger.get_banking_rate() == 90

    async def test_set_invalid_low(self, ledger: PgCoinLedger):
        with pytest.raises(ValueError, match="between 1 and 100"):
            await ledger.set_banking_rate(0)

    async def test_set_invalid_high(self, ledger: PgCoinLedger):
        with pytest.raises(ValueError, match="between 1 and 100"):
            await ledger.set_banking_rate(101)

    async def test_set_boundary_values(self, ledger: PgCoinLedger):
        await ledger.set_banking_rate(1)
        assert await ledger.get_banking_rate() == 1
        await ledger.set_banking_rate(100)
        assert await ledger.get_banking_rate() == 100


# ── ensure_can_afford() ─────────────────────────────────────────────────


class TestEnsureCanAfford:
    async def _make_user_wallet(
        self,
        ledger: PgCoinLedger,
        *,
        owner_id: str = "u-afford",
        denomination: str = "copper",
        budget: int = 500_000,
    ):
        await ledger.upsert_wallet(
            owner_type="user",
            owner_id=owner_id,
            org_id="org-1",
            team_id="team-1",
            label="test",
            billing_cycle="monthly",
            denomination=denomination,
            budget_microchips=budget,
            hard_limit_microchips=budget,
            soft_limit_ratio=0.8,
            overage_allowed=False,
            active=True,
        )

    async def test_allowed_with_budget(self, ledger: PgCoinLedger):
        await self._make_user_wallet(ledger)
        result = await ledger.ensure_can_afford(
            org_id="org-1",
            team_id="team-1",
            user_id="u-afford",
            model_used="test-small",
            provider="test_provider",
            input_tokens=100,
            output_tokens=100,
        )
        assert result["allowed"] is True
        assert "quote" in result

    async def test_insufficient_user_balance(self, ledger: PgCoinLedger):
        await self._make_user_wallet(ledger, budget=1)
        with pytest.raises(QuotaExhaustedError, match="Insufficient.*balance"):
            await ledger.ensure_can_afford(
                org_id="org-1",
                team_id="team-1",
                user_id="u-afford",
                model_used="test-small",
                provider="test_provider",
                input_tokens=10_000,
                output_tokens=10_000,
            )

    async def test_denomination_too_low(self, ledger: PgCoinLedger):
        await self._make_user_wallet(ledger, denomination="copper", budget=10_000_000)
        with pytest.raises(QuotaExhaustedError, match="requires gold"):
            await ledger.ensure_can_afford(
                org_id="org-1",
                team_id="team-1",
                user_id="u-afford",
                model_used="test-large",
                provider="test_provider",
                input_tokens=100,
                output_tokens=100,
            )

    async def test_higher_denomination_can_access_lower_model(self, ledger: PgCoinLedger):
        await self._make_user_wallet(ledger, denomination="gold", budget=10_000_000)
        result = await ledger.ensure_can_afford(
            org_id="org-1",
            team_id="team-1",
            user_id="u-afford",
            model_used="test-small",
            provider="test_provider",
            input_tokens=100,
            output_tokens=100,
        )
        assert result["allowed"] is True

    async def test_org_budget_exceeded(self, ledger: PgCoinLedger):
        await ledger.upsert_wallet(
            owner_type="org",
            owner_id="org-tiny",
            org_id="org-tiny",
            team_id="",
            label="org-budget",
            billing_cycle="monthly",
            denomination="copper",
            budget_microchips=1,
            hard_limit_microchips=1,
            soft_limit_ratio=0.8,
            overage_allowed=False,
            active=True,
        )
        with pytest.raises(QuotaExhaustedError, match="org.*budget exceeded"):
            await ledger.ensure_can_afford(
                org_id="org-tiny",
                team_id="team-1",
                user_id="u-no-wallet",
                model_used="test-small",
                provider="test_provider",
                input_tokens=10_000,
                output_tokens=10_000,
            )

    async def test_team_budget_exceeded(self, ledger: PgCoinLedger):
        await ledger.upsert_wallet(
            owner_type="team",
            owner_id="team-tiny",
            org_id="org-1",
            team_id="team-tiny",
            label="team-budget",
            billing_cycle="monthly",
            denomination="copper",
            budget_microchips=1,
            hard_limit_microchips=1,
            soft_limit_ratio=0.8,
            overage_allowed=False,
            active=True,
        )
        with pytest.raises(QuotaExhaustedError, match="team.*budget exceeded"):
            await ledger.ensure_can_afford(
                org_id="org-1",
                team_id="team-tiny",
                user_id="u-no-wallet",
                model_used="test-small",
                provider="test_provider",
                input_tokens=10_000,
                output_tokens=10_000,
            )

    async def test_no_wallets_raises_quota_exhausted(self, ledger: PgCoinLedger):
        with pytest.raises(QuotaExhaustedError, match="[Ww]allet"):
            await ledger.ensure_can_afford(
                org_id="org-1",
                team_id="team-1",
                user_id="u-none",
                model_used="test-small",
                provider="test_provider",
                input_tokens=100,
                output_tokens=100,
            )


# ── charge_usage() ──────────────────────────────────────────────────────


class TestChargeUsage:
    async def _make_wallet(
        self,
        ledger: PgCoinLedger,
        *,
        owner_type: str = "user",
        owner_id: str = "u-charge",
        denomination: str = "copper",
        budget: int = 1_000_000,
    ):
        await ledger.upsert_wallet(
            owner_type=owner_type,
            owner_id=owner_id,
            org_id="org-1",
            team_id="team-1",
            label="charge-test",
            billing_cycle="monthly",
            denomination=denomination,
            budget_microchips=budget,
            hard_limit_microchips=budget,
            soft_limit_ratio=0.8,
            overage_allowed=False,
            active=True,
        )

    async def test_charge_deducts_from_wallet(self, ledger: PgCoinLedger):
        await self._make_wallet(ledger)
        result = await ledger.charge_usage(
            request_id=str(uuid.uuid4()),
            org_id="org-1",
            team_id="team-1",
            user_id="u-charge",
            model_used="test-small",
            provider="test_provider",
            input_tokens=1000,
            output_tokens=1000,
        )
        assert result["charged_microchips"] > 0
        assert result["wallet_count"] >= 1

        wallets = await ledger.list_wallets(owner_id="u-charge")
        assert wallets[0]["used_microchips"] > 0
        assert wallets[0]["remaining_microchips"] < wallets[0]["budget_microchips"]

    async def test_charge_no_wallets(self, ledger: PgCoinLedger):
        result = await ledger.charge_usage(
            request_id=str(uuid.uuid4()),
            org_id="org-1",
            team_id="team-1",
            user_id="u-ghost",
            model_used="test-small",
            provider="test_provider",
            input_tokens=100,
            output_tokens=100,
        )
        assert result["wallet_count"] == 0
        assert result["charged_microchips"] >= 0

    async def test_charge_picks_cheapest_eligible_denomination(self, ledger: PgCoinLedger):
        await self._make_wallet(ledger, denomination="silver", budget=1_000_000)
        await self._make_wallet(ledger, denomination="gold", budget=1_000_000)
        result = await ledger.charge_usage(
            request_id=str(uuid.uuid4()),
            org_id="org-1",
            team_id="team-1",
            user_id="u-charge",
            model_used="test-small",
            provider="test_provider",
            input_tokens=1000,
            output_tokens=1000,
        )
        assert result["wallet_count"] >= 1
        assert result.get("charged_denomination") == "silver"

    async def test_charge_also_debits_org_wallet(self, ledger: PgCoinLedger):
        await self._make_wallet(
            ledger,
            owner_type="org",
            owner_id="org-1",
            budget=5_000_000,
        )
        await self._make_wallet(
            ledger,
            owner_type="user",
            owner_id="u-charge",
            budget=1_000_000,
        )
        result = await ledger.charge_usage(
            request_id=str(uuid.uuid4()),
            org_id="org-1",
            team_id="team-1",
            user_id="u-charge",
            model_used="test-small",
            provider="test_provider",
            input_tokens=1000,
            output_tokens=1000,
        )
        assert result["wallet_count"] == 2

    async def test_charge_skips_ineligible_denomination(self, ledger: PgCoinLedger):
        await self._make_wallet(ledger, denomination="copper", budget=10_000_000)
        result = await ledger.charge_usage(
            request_id=str(uuid.uuid4()),
            org_id="org-1",
            team_id="team-1",
            user_id="u-charge",
            model_used="test-large",
            provider="test_provider",
            input_tokens=100,
            output_tokens=100,
        )
        assert result["wallet_count"] == 0

    async def test_charge_skips_insufficient_balance(self, ledger: PgCoinLedger):
        await self._make_wallet(ledger, denomination="copper", budget=1)
        result = await ledger.charge_usage(
            request_id=str(uuid.uuid4()),
            org_id="org-1",
            team_id="team-1",
            user_id="u-charge",
            model_used="test-small",
            provider="test_provider",
            input_tokens=10_000,
            output_tokens=10_000,
        )
        assert result["wallet_count"] == 0

    async def test_multiple_charges_accumulate(self, ledger: PgCoinLedger):
        await self._make_wallet(ledger, budget=10_000_000)
        for _ in range(3):
            await ledger.charge_usage(
                request_id=str(uuid.uuid4()),
                org_id="org-1",
                team_id="team-1",
                user_id="u-charge",
                model_used="test-small",
                provider="test_provider",
                input_tokens=1000,
                output_tokens=1000,
            )
        wallets = await ledger.list_wallets(owner_id="u-charge")
        single_quote = ledger.quote("test-small", "test_provider", 1000, 1000)
        assert wallets[0]["used_microchips"] == single_quote.charged_microchips * 3


# ── _hydrate_wallet integration ──────────────────────────────────────────


class TestHydrateWallet:
    async def test_hydrated_fields_present(self, ledger: PgCoinLedger):
        await ledger.upsert_wallet(
            owner_type="user",
            owner_id="u-hydrate",
            org_id="org-1",
            team_id="team-1",
            label="hydrate-test",
            billing_cycle="monthly",
            denomination="silver",
            budget_microchips=500_000,
            hard_limit_microchips=500_000,
            soft_limit_ratio=0.75,
            overage_allowed=True,
            active=True,
        )
        wallets = await ledger.list_wallets(owner_id="u-hydrate")
        w = wallets[0]
        expected_keys = {
            "id",
            "owner_type",
            "owner_id",
            "org_id",
            "team_id",
            "label",
            "billing_cycle",
            "denomination",
            "budget_microchips",
            "budget_display",
            "hard_limit_microchips",
            "hard_limit_display",
            "credited_microchips",
            "credited_display",
            "effective_budget_microchips",
            "effective_budget_display",
            "used_microchips",
            "used_display",
            "remaining_microchips",
            "remaining_display",
            "soft_limit_microchips",
            "soft_limit_display",
            "soft_limit_ratio",
            "overage_allowed",
            "active",
            "cycle_key",
            "created_at",
            "updated_at",
        }
        assert expected_keys.issubset(set(w.keys()))
        assert w["denomination"] == "silver"
        assert w["soft_limit_ratio"] == 0.75
        assert w["overage_allowed"] is True

    async def test_credited_microchips_affect_remaining(self, ledger: PgCoinLedger, pg_pool):
        """Credits increase the effective budget and remaining balance."""
        w = await ledger.upsert_wallet(
            owner_type="user",
            owner_id="u-credit",
            org_id="org-1",
            team_id="team-1",
            label="credit-test",
            billing_cycle="monthly",
            denomination="copper",
            budget_microchips=100_000,
            hard_limit_microchips=100_000,
            soft_limit_ratio=0.8,
            overage_allowed=False,
            active=True,
        )
        from stronghold.quota.billing import cycle_key

        ck = cycle_key("monthly")
        async with pg_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO coin_ledger_entries
                   (wallet_id, cycle_key, entry_kind, delta_microchips)
                   VALUES ($1, $2, 'credit', $3)""",
                w["id"],
                ck,
                50_000,
            )
        wallets = await ledger.list_wallets(owner_id="u-credit")
        w2 = wallets[0]
        assert w2["credited_microchips"] == 50_000
        assert w2["effective_budget_microchips"] == 150_000
        assert w2["remaining_microchips"] == 150_000
