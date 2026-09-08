"""The deployment must not quietly differ from what was demonstrated.

Three failures in one day came from a setting being one thing in the code and
another somewhere else, and none of them could fail a test:

  - `.env` pinned RIME_SAMPLE_RATE=22050 while the code default said 48000, so
    editing the default fixed nothing and the process kept aborting.
  - Deepgram was told 48000 while the room stayed on its own 24000 default, and
    a whole session produced no transcript at all.
  - `render.yaml` never declared ACCESS_CODE, so the blueprint could not ask for
    it and the web service refused to start twice.

Each was found by running the thing. These assert the same properties without
having to, so a wrong value fails a build rather than a demo.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config import Settings

ROOT = Path(__file__).resolve().parent.parent
RENDER = ROOT / "render.yaml"
ENV_EXAMPLE = ROOT / ".env.example"


def services() -> dict[str, Any]:
    """Parsed render.yaml. Deliberately untyped: it is a config file, not a model."""
    blueprint = yaml.safe_load(RENDER.read_text(encoding="utf-8"))
    return {s["name"]: s for s in blueprint["services"]}


def env_vars(service: dict[str, Any]) -> dict[str, Any]:
    """Declared variables: name -> pinned value, or None when set in the dashboard."""
    return {e["key"]: e.get("value") for e in service["envVars"]}


def example_keys() -> set[str]:
    keys = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.add(line.split("=", 1)[0].strip())
    return keys


class TestBlueprint:
    def test_it_parses(self) -> None:
        assert RENDER.exists()
        assert set(services()) == {"roundcraft-rime-agent", "roundcraft-rime-web"}

    def test_the_worker_asks_for_every_credential_the_app_requires(self) -> None:
        """`missing()` is what refuses to start; the blueprint must cover it."""
        required = set(Settings().missing())
        declared = set(env_vars(services()["roundcraft-rime-agent"]))
        assert required <= declared, f"blueprint never asks for {sorted(required - declared)}"

    def test_the_web_service_asks_for_the_access_code(self) -> None:
        """It refuses to serve a public instance without one, so it must be asked for."""
        assert "ACCESS_CODE" in env_vars(services()["roundcraft-rime-web"])

    def test_no_credential_is_ever_pinned_in_the_blueprint(self) -> None:
        """A committed credential is an eligibility failure, not a mistake.

        The secrets are named rather than guessed at. A first version matched any
        key containing "TOKEN" and failed on LLM_MAX_TOKENS, which is a count of
        tokens and not a credential; a test that cries wolf about its own config
        gets switched off.
        """
        secrets = set(Settings().missing()) | {"ACCESS_CODE", "LLM_BASE_URL"}
        for name, service in services().items():
            for key, value in env_vars(service).items():
                if key in secrets:
                    assert value is None, f"{name} pins a value for {key}"

    def test_the_web_service_holds_no_speech_or_model_credentials(self) -> None:
        """It only signs room tokens. Nothing else should be reachable from it."""
        declared = set(env_vars(services()["roundcraft-rime-web"]))
        for key in ("RIME_API_KEY", "DEEPGRAM_API_KEY", "LLM_API_KEY"):
            assert key not in declared, f"the token service should not hold {key}"


class TestPinnedValuesMatchTheCode:
    """A deployment running different numbers from the demo is the whole problem."""

    @pytest.mark.parametrize(
        ("key", "field"),
        [
            ("RIME_MODEL", "rime_model"),
            ("RIME_LANG", "rime_lang"),
            ("RIME_SAMPLE_RATE", "rime_sample_rate"),
            ("DEEPGRAM_SAMPLE_RATE", "deepgram_sample_rate"),
            ("LLM_MAX_TOKENS", "llm_max_tokens"),
            ("LLM_REASONING_EFFORT", "llm_reasoning_effort"),
            ("LOOKUP_DELAY_SECONDS", "lookup_delay_seconds"),
        ],
    )
    def test_blueprint_agrees_with_the_default(self, key: str, field: str) -> None:
        pinned = env_vars(services()["roundcraft-rime-agent"]).get(key)
        assert pinned is not None, f"{key} is not pinned in render.yaml"
        expected = getattr(Settings(), field)
        assert str(pinned) == str(expected), (
            f"render.yaml pins {key}={pinned} but the code default is {expected}"
        )


class TestEnvExample:
    def test_it_names_every_required_credential(self) -> None:
        """The organiser preflight reads this file, and so does a new contributor."""
        assert set(Settings().missing()) <= example_keys()

    def test_it_carries_no_real_values(self) -> None:
        """Placeholders only, which the event rules require explicitly."""
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
            if line.startswith("RIME_API_KEY=") or line.startswith("DEEPGRAM_API_KEY="):
                value = line.split("=", 1)[1].strip()
                assert not value or value.startswith("your_"), f"{line.split('=')[0]} looks real"

    def test_the_sample_rates_it_ships_match_the_code(self) -> None:
        """.env.example shipped 22050 while the code said 48000, and .env won."""
        shipped = {}
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, _, value = line.partition("=")
                shipped[key.strip()] = value.strip()
        settings = Settings()
        if "RIME_SAMPLE_RATE" in shipped:
            assert int(shipped["RIME_SAMPLE_RATE"]) == settings.rime_sample_rate
