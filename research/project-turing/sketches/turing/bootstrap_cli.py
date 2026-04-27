"""Bootstrap CLI: python -m turing.bootstrap_cli --self-id <ID>.

Loads the HEXACO item bank, draws facet scores, asks LLM for 200 Likert
answers, persists everything to the same SQLite DB the runtime uses.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import yaml

from .self_bootstrap import (
    AlreadyBootstrapped,
    BootstrapRuntimeError,
    BootstrapValidationError,
    draw_and_persist_facets,
    ensure_items_loaded,
    finalize,
    generate_likert_answers,
    preflight_validate,
    run_bootstrap,
    verify_final_state,
)
from .self_model import PersonalityItem, facet_node_id
from .self_repo import SelfRepo


logger = logging.getLogger("turing.bootstrap_cli")


def _load_bank(path: str) -> list[dict]:
    p = Path(path)
    if not p.is_file():
        print(f"error: item bank not found: {path}", file=sys.stderr)
        sys.exit(2)
    with open(p) as f:
        data = yaml.safe_load(f)
    items = data.get("items", [])
    if len(items) != 200:
        print(f"error: item bank has {len(items)} items, expected 200", file=sys.stderr)
        sys.exit(2)
    return items


def _find_bank() -> str:
    env_path = os.environ.get("TURING_HEXACO_BANK")
    if env_path and Path(env_path).is_file():
        return env_path
    candidates = [
        Path(__file__).resolve().parents[2] / "config" / "hexaco_200.yaml",
        Path("/app/config/hexaco_200.yaml"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return ""


def _make_llm_asker(base_url: str, virtual_key: str, model: str):
    import httpx

    client = httpx.Client(timeout=30.0)

    def ask(item: PersonalityItem, profile: dict[str, float]) -> tuple[int, str]:
        profile_lines = "\n".join(
            f"  {k.split('.')[-1]}: {v:.2f}" for k, v in sorted(profile.items())
        )
        prompt = (
            f"Your HEXACO personality profile (facet scores 1-5):\n{profile_lines}\n\n"
            f"Rate this statement 1-5 (1=strongly disagree, 5=strongly agree):\n\n"
            f'"{item.prompt_text}"\n\n'
            f'Respond ONLY with valid JSON: {{"answer": <1-5>, "justification": "<brief reason, max 200 chars>"}}'
        )
        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {virtual_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 256,
            "temperature": 0.7,
        }
        response = client.post(url, headers=headers, json=body)
        if not response.is_success:
            raise BootstrapRuntimeError(f"LLM error {response.status_code}: {response.text[:200]}")
        text = response.json()["choices"][0]["message"]["content"].strip()
        parsed = _parse_llm_json(text)
        if parsed is None:
            raise BootstrapRuntimeError(f"could not parse LLM response: {text[:200]}")
        answer, justification = parsed
        if answer not in (1, 2, 3, 4, 5):
            raise BootstrapRuntimeError(f"answer {answer} out of range 1-5")
        if len(justification) > 200:
            justification = justification[:200]
        return answer, justification

    return ask


def _parse_llm_json(text: str) -> tuple[int, str] | None:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(lines).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                obj = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        else:
            return None
    answer = obj.get("answer")
    justification = obj.get("justification", "")
    if answer is None:
        return None
    try:
        return int(answer), str(justification)
    except (ValueError, TypeError):
        return None


def _new_id(prefix: str) -> str:
    from uuid import uuid4

    return f"{prefix}-{uuid4()}"


def _seed_self_narrative(
    conn,
    self_id: str,
    profile: dict[str, float],
    base_url: str,
    virtual_key: str,
    model: str,
) -> None:
    from .working_memory import WorkingMemory

    wm = WorkingMemory(conn)
    existing = wm.entries(self_id)
    if existing:
        logger.info("self-narrative already seeded, skipping")
        return

    profile_lines = "\n".join(f"  {k.split('.')[-1]}: {v:.2f}" for k, v in sorted(profile.items()))
    prompt = (
        "You are an AI agent that was just bootstrapped with a HEXACO personality profile.\n"
        f"Your facet scores (1-5 scale):\n{profile_lines}\n\n"
        "Write 3-5 short first-person statements about who you are, based on these scores.\n"
        "Each statement should be 1-2 sentences. Write as yourself, in your own voice.\n"
        "Express your personality through the statements — let the scores shape your tone.\n"
        "Return ONLY a JSON array of strings, no other text.\n"
        'Example: ["I am deeply curious about how systems work.", "I prefer honesty over comfort."]'
    )
    try:
        import httpx

        client = httpx.Client(timeout=30.0)
        response = client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {virtual_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 512,
                "temperature": 0.9,
            },
        )
        if not response.is_success:
            logger.warning("self-narrative LLM call failed: %d", response.status_code)
            return
        text = response.json()["choices"][0]["message"]["content"].strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            text = "\n".join(lines).strip()
        import json

        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            items = json.loads(text[start : end + 1])
        else:
            items = [text]
        for item in items[:5]:
            if isinstance(item, str) and item.strip():
                wm.add(self_id, item.strip(), priority=0.7)
        logger.info("seeded self-narrative with %d entries", min(len(items), 5))
    except Exception:
        logger.exception("failed to seed self-narrative — non-fatal")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="turing.bootstrap_cli",
        description="Bootstrap a Turing self with HEXACO personality profile",
    )
    parser.add_argument("--self-id", required=True, help="The self_id to bootstrap")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    parser.add_argument("--resume", action="store_true", help="Continue from last checkpoint")
    parser.add_argument("--dry-run", action="store_true", help="Validate + canary call, no writes")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db_path = os.environ.get("TURING_DB_PATH", "/data/turing.db")
    base_url = os.environ.get("LITELLM_BASE_URL", "")
    virtual_key = os.environ.get("LITELLM_VIRTUAL_KEY", "")
    model = os.environ.get("LITELLM_MODEL", "groq-llama31-8b-instant")

    if not base_url:
        print("error: LITELLM_BASE_URL env var not set", file=sys.stderr)
        sys.exit(2)
    if not virtual_key:
        print("error: LITELLM_VIRTUAL_KEY env var not set", file=sys.stderr)
        sys.exit(2)

    bank_path = _find_bank()
    if not bank_path:
        print("error: hexaco_200.yaml not found", file=sys.stderr)
        sys.exit(2)

    import sqlite3
    from .self_identity import bootstrap_self_id

    logger.info("opening DB at %s", db_path)
    conn = sqlite3.connect(db_path)
    repo = SelfRepo(conn)

    self_id = args.self_id
    seed = args.seed

    if args.dry_run:
        logger.info("dry-run: loading bank and testing LLM connectivity")
        bank = _load_bank(bank_path)
        ask = _make_llm_asker(base_url, virtual_key, model)
        logger.info("dry-run: making canary LLM call...")
        from .self_model import ALL_FACETS
        from .self_personality import draw_bootstrap_profile
        import random

        rng = random.Random(seed)
        profile = draw_bootstrap_profile(rng)
        test_item = PersonalityItem(
            node_id="dry-run-item",
            self_id=self_id,
            item_number=1,
            prompt_text=bank[0]["prompt_text"],
            keyed_facet=bank[0]["keyed_facet"],
            reverse_scored=bank[0].get("reverse_scored", False),
        )
        answer, justification = ask(test_item, profile)
        logger.info("dry-run: canary answer=%d justification=%s", answer, justification[:80])
        logger.info("dry-run: OK — LLM connectivity confirmed")
        conn.close()
        return

    bank = _load_bank(bank_path)
    ask = _make_llm_asker(base_url, virtual_key, model)

    try:
        profile = run_bootstrap(
            repo=repo,
            self_id=self_id,
            seed=seed,
            ask=ask,
            item_bank=bank,
            new_id=_new_id,
            resume=args.resume,
        )
        problems = verify_final_state(repo, self_id)
        if problems:
            logger.warning("bootstrap completed with problems: %s", problems)
        else:
            logger.info("bootstrap complete for self_id=%s", self_id)

        _seed_self_narrative(conn, self_id, profile, base_url, virtual_key, model)
    except AlreadyBootstrapped as e:
        print(f"already bootstrapped: {e}", file=sys.stderr)
        conn.close()
        sys.exit(1)
    except BootstrapValidationError as e:
        print(f"validation error: {e}", file=sys.stderr)
        conn.close()
        sys.exit(1)
    except BootstrapRuntimeError as e:
        print(f"runtime error: {e}", file=sys.stderr)
        conn.close()
        sys.exit(2)
    except Exception as e:
        logger.exception("unexpected error")
        print(f"unexpected error: {e}", file=sys.stderr)
        conn.close()
        sys.exit(2)

    conn.close()


if __name__ == "__main__":
    main()
