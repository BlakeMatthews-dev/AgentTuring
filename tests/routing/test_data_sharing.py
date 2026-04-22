"""Tests for data-sharing provider consent gate."""

from stronghold.conduit import _CONSENT_AFFIRMATIVE
from stronghold.router.filter import filter_candidates
from stronghold.types.model import ProviderConfig
from tests.factories import build_intent, build_model_config, build_provider_config


class TestDataSharingFiltering:
    """Data-sharing providers are excluded from routing unless consented."""

    def test_data_sharing_provider_excluded_by_default(self) -> None:
        intent = build_intent(task_type="chat")
        models = {
            "safe-model": build_model_config(provider="safe"),
            "ds-model": build_model_config(provider="xai", quality=0.9),
        }
        providers = {
            "safe": build_provider_config(),
            "xai": build_provider_config(data_sharing=True),
        }
        # Pass all providers to filter — xai model is excluded because
        # it's in a data-sharing provider and not in routable_providers.
        # The conduit filters providers BEFORE passing to the router.
        routable = {k: v for k, v in providers.items() if not v.data_sharing}
        result = filter_candidates(intent, models, routable, usage_pcts={"safe": 0.0})
        assert len(result) == 1
        assert result[0][0] == "safe-model"

    def test_data_sharing_provider_included_when_consented(self) -> None:
        intent = build_intent(task_type="chat")
        models = {
            "safe-model": build_model_config(provider="safe"),
            "ds-model": build_model_config(provider="xai", quality=0.9),
        }
        providers = {
            "safe": build_provider_config(),
            "xai": build_provider_config(data_sharing=True),
        }
        # When user has consented, xai stays in the providers dict.
        result = filter_candidates(
            intent, models, providers, usage_pcts={"safe": 0.0, "xai": 0.0}
        )
        assert len(result) == 2
        model_ids = {r[0] for r in result}
        assert "ds-model" in model_ids

    def test_non_data_sharing_provider_unaffected(self) -> None:
        intent = build_intent(task_type="code")
        models = {
            "model-a": build_model_config(provider="a"),
            "model-b": build_model_config(provider="b"),
        }
        providers = {
            "a": build_provider_config(data_sharing=False),
            "b": build_provider_config(data_sharing=False),
        }
        result = filter_candidates(
            intent, models, providers, usage_pcts={"a": 0.0, "b": 0.0}
        )
        assert len(result) == 2


class TestProviderConfigDataSharing:
    """ProviderConfig data_sharing fields."""

    def test_defaults_to_false(self) -> None:
        cfg = ProviderConfig()
        assert cfg.data_sharing is False
        assert cfg.data_sharing_notice == ""

    def test_data_sharing_from_dict(self) -> None:
        cfg = ProviderConfig(
            data_sharing=True,
            data_sharing_notice="xAI uses your data for training.",
        )
        assert cfg.data_sharing is True
        assert "xAI" in cfg.data_sharing_notice

class TestConsentAffirmative:
    """The affirmative word set used for consent detection."""

    def test_common_affirmatives(self) -> None:
        for word in ("yes", "sure", "ok", "yep", "allow", "fine"):
            assert word in _CONSENT_AFFIRMATIVE

    def test_negative_words_not_included(self) -> None:
        for word in ("no", "nah", "nope", "deny", "refuse", "never"):
            assert word not in _CONSENT_AFFIRMATIVE
