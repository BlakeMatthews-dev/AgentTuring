"""Tests for modality-based model filtering."""

from stronghold.router.filter import filter_candidates
from tests.factories import build_intent, build_model_config, build_provider_config


class TestModalityFiltering:
    def test_image_gen_only_matches_image_gen_models(self) -> None:
        intent = build_intent(task_type="image_gen")
        models = {
            "text-model": build_model_config(modality="text", provider="p"),
            "image-model": build_model_config(modality="image_gen", provider="p"),
        }
        providers = {"p": build_provider_config()}
        result = filter_candidates(intent, models, providers, usage_pcts={"p": 0.0})
        assert len(result) == 1
        assert result[0][0] == "image-model"

    def test_text_task_excludes_image_gen_models(self) -> None:
        intent = build_intent(task_type="chat")
        models = {
            "text-model": build_model_config(modality="text", provider="p"),
            "image-model": build_model_config(modality="image_gen", provider="p"),
        }
        providers = {"p": build_provider_config()}
        result = filter_candidates(intent, models, providers, usage_pcts={"p": 0.0})
        assert all(m[0] != "image-model" for m in result)
