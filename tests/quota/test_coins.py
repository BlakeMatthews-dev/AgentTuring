"""Tests for the coin-based quota ledger."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from stronghold.quota.coins import (
    DEFAULT_BANKING_RATE_PCT,
    DEFAULT_PRICING_VERSION,
    DENOMINATION_FACTORS,
    MICROCHIPS_PER_COPPER,
    CoinQuote,
    NoOpCoinLedger,
    _decimal,
    _extract_provider,
    _find_model,
    _rate_value,
    _resolve_denomination,
    _resolve_quote,
    coins_to_microchips,
    format_microchips,
)

# ---------------------------------------------------------------------------
# _decimal
# ---------------------------------------------------------------------------


class TestDecimal:
    def test_none_returns_default(self) -> None:
        assert _decimal(None) == Decimal("0")

    def test_empty_string_returns_default(self) -> None:
        assert _decimal("") == Decimal("0")

    def test_valid_number(self) -> None:
        assert _decimal("3.14") == Decimal("3.14")
        assert _decimal(42) == Decimal("42")

    def test_invalid_string_returns_default(self) -> None:
        assert _decimal("not-a-number") == Decimal("0")

    def test_custom_default(self) -> None:
        assert _decimal(None, default="5") == Decimal("5")
        assert _decimal("bad", default="99") == Decimal("99")


# ---------------------------------------------------------------------------
# coins_to_microchips
# ---------------------------------------------------------------------------


class TestCoinsToMicrochips:
    def test_one_copper_equals_1000_microchips(self) -> None:
        assert coins_to_microchips(1, "copper") == 1_000

    def test_one_silver_equals_10000_microchips(self) -> None:
        assert coins_to_microchips(1, "silver") == 10_000

    def test_one_gold_equals_100000_microchips(self) -> None:
        assert coins_to_microchips(1, "gold") == 100_000

    def test_one_platinum_equals_500000_microchips(self) -> None:
        assert coins_to_microchips(1, "platinum") == 500_000

    def test_one_diamond_equals_1000000_microchips(self) -> None:
        assert coins_to_microchips(1, "diamond") == 1_000_000

    def test_fractional_amount_rounds_half_up(self) -> None:
        # 0.5 copper = 500 microchips exactly
        assert coins_to_microchips("0.5", "copper") == 500
        # 0.0015 gold = 0.0015 * 100 * 1000 = 150
        assert coins_to_microchips("0.0015", "gold") == 150
        # 0.0005 copper = 0.5 -> rounds to 1 (ROUND_HALF_UP)
        assert coins_to_microchips("0.0005", "copper") == 1

    def test_unknown_denomination_uses_factor_1(self) -> None:
        assert coins_to_microchips(1, "mithril") == 1_000

    def test_none_denomination_defaults_to_copper(self) -> None:
        assert coins_to_microchips(1, None) == 1_000

    def test_zero_amount(self) -> None:
        assert coins_to_microchips(0, "gold") == 0


# ---------------------------------------------------------------------------
# format_microchips
# ---------------------------------------------------------------------------


class TestFormatMicrochips:
    def test_format_copper_range(self) -> None:
        result = format_microchips(5_000)
        assert result["denomination"] == "copper"
        assert result["amount"] == 5.0
        assert result["microchips"] == 5_000

    def test_format_silver_range(self) -> None:
        # 10 * 1000 = 10_000 is the silver threshold
        result = format_microchips(15_000)
        assert result["denomination"] == "silver"
        assert result["amount"] == 1.5
        assert result["microchips"] == 15_000

    def test_format_gold_range(self) -> None:
        result = format_microchips(200_000)
        assert result["denomination"] == "gold"
        assert result["amount"] == 2.0
        assert result["microchips"] == 200_000

    def test_negative_value_negates_amount(self) -> None:
        result = format_microchips(-50_000)
        assert result["amount"] == -5.0
        assert result["denomination"] == "silver"
        assert result["microchips"] == -50_000

    def test_zero_microchips(self) -> None:
        result = format_microchips(0)
        assert result["amount"] == 0.0
        assert result["denomination"] == "copper"
        assert result["microchips"] == 0

    def test_exact_boundary(self) -> None:
        # Exactly 10_000 should qualify as silver (abs_value >= 10*1000)
        result = format_microchips(10_000)
        assert result["denomination"] == "silver"
        assert result["amount"] == 1.0


# ---------------------------------------------------------------------------
# _resolve_denomination
# ---------------------------------------------------------------------------


class TestResolveDenomination:
    def test_explicit_denomination_takes_precedence(self) -> None:
        model_raw = {"coin_denomination": "diamond"}
        assert _resolve_denomination(model_raw, base=0, in_rate=1, out_rate=2) == "diamond"

    def test_auto_derives_copper_for_low_cost(self) -> None:
        # typical = 0 + 1 + 2 = 3 < 1000; resolved stays "copper"
        assert _resolve_denomination({}, base=0, in_rate=1, out_rate=2) == "copper"

    def test_auto_derives_silver_for_medium_cost(self) -> None:
        # typical must be >= 10*1000 = 10_000 for silver
        assert _resolve_denomination({}, base=5_000, in_rate=3_000, out_rate=3_000) == "silver"

    def test_auto_derives_gold_for_high_cost(self) -> None:
        # typical >= 100*1000 = 100_000 for gold
        assert _resolve_denomination({}, base=50_000, in_rate=30_000, out_rate=30_000) == "gold"

    def test_empty_explicit_falls_through_to_auto(self) -> None:
        model_raw = {"coin_denomination": ""}
        assert _resolve_denomination(model_raw, base=0, in_rate=1, out_rate=2) == "copper"

    def test_invalid_explicit_falls_through_to_auto(self) -> None:
        model_raw = {"coin_denomination": "mithril"}
        # "mithril" not in DENOMINATION_FACTORS -> falls through
        assert _resolve_denomination(model_raw, base=0, in_rate=1, out_rate=2) == "copper"


# ---------------------------------------------------------------------------
# _resolve_quote
# ---------------------------------------------------------------------------


class TestResolveQuote:
    def test_basic_arithmetic(self) -> None:
        # Default rates: base=0, input="1" copper=1000mc, output="2" copper=2000mc
        # in_cost = 1000/1000 * 1000 = 1000
        # out_cost = 500/1000 * 2000 = 1000
        # total = 0 + 1000 + 1000 = 2000
        q = _resolve_quote({}, {}, "test-model", "", 1000, 500)
        assert q.charged_microchips == 2_000
        assert q.base_microchips == 0
        assert q.input_rate_microchips == 1_000
        assert q.output_rate_microchips == 2_000

    def test_input_output_asymmetry(self) -> None:
        # Same total tokens (1500), but different I/O split -> different cost
        q_a = _resolve_quote({}, {}, "m", "", 1000, 500)
        q_b = _resolve_quote({}, {}, "m", "", 500, 1000)
        assert q_a.charged_microchips == 2_000
        assert q_b.charged_microchips == 2_500

    def test_zero_tokens_charges_base_only(self) -> None:
        models = {
            "zero-model": {
                "coin_cost_base": "5",
                "coin_cost_base_denomination": "copper",
                "coin_cost_per_1k_input": "1",
                "coin_cost_per_1k_input_denomination": "copper",
                "coin_cost_per_1k_output": "2",
                "coin_cost_per_1k_output_denomination": "copper",
            }
        }
        q = _resolve_quote(models, {}, "zero-model", "", 0, 0)
        assert q.charged_microchips == 5_000
        assert q.base_microchips == 5_000

    def test_negative_tokens_clamped_to_zero(self) -> None:
        q = _resolve_quote({}, {}, "m", "", -100, -200)
        assert q.charged_microchips == 0

    def test_missing_model_uses_defaults(self) -> None:
        q = _resolve_quote({}, {}, "nonexistent", "", 1000, 1000)
        assert q.base_microchips == 0
        assert q.input_rate_microchips == 1_000
        assert q.output_rate_microchips == 2_000
        assert q.charged_microchips == 3_000
        assert q.pricing_version == DEFAULT_PRICING_VERSION

    def test_configured_model_uses_its_rates(self) -> None:
        models = {
            "gpt-4": {
                "coin_cost_base_microchips": 500,
                "coin_cost_per_1k_input_microchips": 3000,
                "coin_cost_per_1k_output_microchips": 6000,
            }
        }
        q = _resolve_quote(models, {}, "gpt-4", "", 2000, 1000)
        # base=500, in_cost=2000/1000*3000=6000, out_cost=1000/1000*6000=6000
        assert q.base_microchips == 500
        assert q.input_rate_microchips == 3_000
        assert q.output_rate_microchips == 6_000
        assert q.charged_microchips == 12_500

    def test_charged_never_negative(self) -> None:
        models = {
            "neg-base": {
                "coin_cost_base_microchips": -500,
                "coin_cost_per_1k_input_microchips": 0,
                "coin_cost_per_1k_output_microchips": 0,
            }
        }
        q = _resolve_quote(models, {}, "neg-base", "", 0, 0)
        assert q.charged_microchips == 0

    def test_pricing_version_from_model(self) -> None:
        models = {"m": {"coin_pricing_version": "v2"}}
        q = _resolve_quote(models, {}, "m", "", 0, 0)
        assert q.pricing_version == "v2"

    def test_pricing_version_from_provider(self) -> None:
        providers = {"openai": {"coin_pricing_version": "v3"}}
        q = _resolve_quote({}, providers, "m", "openai", 0, 0)
        assert q.pricing_version == "v3"


# ---------------------------------------------------------------------------
# _find_model
# ---------------------------------------------------------------------------


class TestFindModel:
    def test_exact_key_match(self) -> None:
        models = {"gpt-4": {"litellm_id": "openai/gpt-4", "tier": "gold"}}
        raw, key = _find_model(models, "gpt-4")
        assert key == "gpt-4"
        assert raw["tier"] == "gold"

    def test_litellm_id_match(self) -> None:
        models = {"gpt-4": {"litellm_id": "openai/gpt-4"}}
        raw, key = _find_model(models, "openai/gpt-4")
        assert key == "gpt-4"
        assert raw["litellm_id"] == "openai/gpt-4"

    def test_no_match_returns_empty_dict_and_model_used(self) -> None:
        raw, key = _find_model({"other": {}}, "nonexistent")
        assert raw == {}
        assert key == "nonexistent"


# ---------------------------------------------------------------------------
# _extract_provider
# ---------------------------------------------------------------------------


class TestExtractProvider:
    def test_from_model_raw(self) -> None:
        model_raw = {"provider": "anthropic"}
        assert _extract_provider(model_raw, {}, "claude-3") == "anthropic"

    def test_from_slash_prefix(self) -> None:
        providers = {"openai": {"key": "sk-..."}}
        assert _extract_provider({}, providers, "openai/gpt-4") == "openai"

    def test_no_provider_returns_empty(self) -> None:
        assert _extract_provider({}, {}, "plain-model") == ""

    def test_slash_prefix_not_in_providers(self) -> None:
        assert _extract_provider({}, {}, "unknown/model") == ""

    def test_model_raw_provider_takes_precedence(self) -> None:
        model_raw = {"provider": "anthropic"}
        providers = {"openai": {}}
        assert _extract_provider(model_raw, providers, "openai/gpt-4") == "anthropic"


# ---------------------------------------------------------------------------
# _rate_value
# ---------------------------------------------------------------------------


class TestRateValue:
    def test_microchips_field_takes_precedence(self) -> None:
        model_raw = {
            "coin_cost_base_microchips": 5000,
            "coin_cost_base": "10",
            "coin_cost_base_denomination": "gold",
        }
        assert _rate_value(model_raw, "coin_cost_base", default="0") == 5_000

    def test_denomination_field_used_when_no_microchips(self) -> None:
        model_raw = {
            "coin_cost_base": "2",
            "coin_cost_base_denomination": "silver",
        }
        # 2 silver = 2 * 10 * 1000 = 20_000
        assert _rate_value(model_raw, "coin_cost_base", default="0") == 20_000

    def test_default_when_neither_present(self) -> None:
        # No field at all -- uses default with copper denomination
        assert _rate_value({}, "coin_cost_base", default="3") == 3_000

    def test_default_zero(self) -> None:
        assert _rate_value({}, "coin_cost_base", default="0") == 0


# ---------------------------------------------------------------------------
# NoOpCoinLedger
# ---------------------------------------------------------------------------


class TestNoOpCoinLedger:
    async def test_ensure_can_afford_always_allowed(self) -> None:
        ledger = NoOpCoinLedger()
        result = await ledger.ensure_can_afford(
            org_id="o",
            team_id="t",
            user_id="u",
            model_used="m",
            provider="p",
            input_tokens=1000,
            output_tokens=500,
        )
        assert result["allowed"] is True
        assert isinstance(result["quote"], CoinQuote)

    async def test_charge_usage_returns_zero_wallet_count(self) -> None:
        ledger = NoOpCoinLedger()
        result = await ledger.charge_usage(
            request_id="r1",
            org_id="o",
            team_id="t",
            user_id="u",
            model_used="m",
            provider="p",
            input_tokens=1000,
            output_tokens=500,
        )
        assert result["wallet_count"] == 0
        assert result["charged_microchips"] > 0

    async def test_list_wallets_returns_empty(self) -> None:
        ledger = NoOpCoinLedger()
        result = await ledger.list_wallets(org_id="o")
        assert result == []

    async def test_get_banking_rate_returns_default_40(self) -> None:
        ledger = NoOpCoinLedger()
        rate = await ledger.get_banking_rate()
        assert rate == DEFAULT_BANKING_RATE_PCT
        assert rate == 40

    async def test_set_banking_rate_raises_runtime_error(self) -> None:
        ledger = NoOpCoinLedger()
        with pytest.raises(RuntimeError, match="PostgreSQL"):
            await ledger.set_banking_rate(50)

    async def test_upsert_wallet_raises_runtime_error(self) -> None:
        ledger = NoOpCoinLedger()
        with pytest.raises(RuntimeError, match="PostgreSQL"):
            await ledger.upsert_wallet()

    def test_quote_uses_resolve_quote_with_empty_config(self) -> None:
        ledger = NoOpCoinLedger()
        q = ledger.quote("test-model", "test-provider", 1000, 1000)
        assert isinstance(q, CoinQuote)
        assert q.model_key == "test-model"
        assert q.charged_microchips == 3_000

    def test_denominations_returns_factors(self) -> None:
        ledger = NoOpCoinLedger()
        d = ledger.denominations()
        assert d["microchips_per_copper"] == MICROCHIPS_PER_COPPER
        assert d["factors"] == DENOMINATION_FACTORS

    async def test_get_subject_summary(self) -> None:
        ledger = NoOpCoinLedger()
        result = await ledger.get_subject_summary(org_id="o", team_id="t", user_id="u")
        assert result["wallets"] == []
        assert "denominations" in result


# ---------------------------------------------------------------------------
# CoinQuote frozen
# ---------------------------------------------------------------------------


class TestCoinQuoteFrozen:
    def test_cannot_modify_fields(self) -> None:
        q = CoinQuote(
            base_microchips=0,
            input_rate_microchips=1000,
            output_rate_microchips=2000,
            charged_microchips=3000,
            pricing_version="v1",
            model_key="m",
            provider="p",
            denomination="copper",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            q.charged_microchips = 999  # type: ignore[misc]

    def test_fields_accessible(self) -> None:
        q = CoinQuote(
            base_microchips=100,
            input_rate_microchips=200,
            output_rate_microchips=300,
            charged_microchips=400,
            pricing_version="v2",
            model_key="model",
            provider="prov",
            denomination="silver",
        )
        assert q.base_microchips == 100
        assert q.input_rate_microchips == 200
        assert q.output_rate_microchips == 300
        assert q.charged_microchips == 400
        assert q.pricing_version == "v2"
        assert q.model_key == "model"
        assert q.provider == "prov"
        assert q.denomination == "silver"
