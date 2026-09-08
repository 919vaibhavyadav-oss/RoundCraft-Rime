"""Configuration, read from the environment only.

Every credential stays server-side. `.env` is gitignored and `.env.example`
carries placeholders alone, which the event rules require and which the
organiser preflight checks.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Rime: the primary spoken output ---------------------------------
    # These exact values are documented in README.md and must match what the
    # demo runs. The speaker list is checked against the live catalogue by
    # app.panel.voices.verify_speakers before recording.
    rime_api_key: str = ""
    rime_model: str = "coda"
    rime_lang: str = "eng"
    # 48kHz because that is what LiveKit rooms carry. Asking Rime for anything
    # else makes the pipeline resample every frame, and that resampler (soxr)
    # aborts the whole process with "LSX_FFT_BR == NULL" when its FFT cache is
    # touched from more than one thread. Verified against the live service:
    # Rime synthesises 48000 natively, so the resampler is simply not needed.
    rime_sample_rate: int = 48000
    # Websocket streaming gives word-level timestamps, which is what lets the
    # floor guard place an interruption exactly rather than estimate it.
    rime_use_websocket: bool = True

    # --- Realtime transport ----------------------------------------------
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # --- Speech recognition ----------------------------------------------
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-3"

    # --- The model that writes each interviewer's question ----------------
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    # Groq's free tier caps output tokens per minute, and it rejects a request
    # outright when the model's default output budget exceeds that cap - not
    # when the answer actually would. Sending no ceiling asked for 1089 tokens
    # against a limit of 1000 and got a 429 before generating a word. An
    # interview question is around 30 tokens.
    llm_max_tokens: int = 150
    # Qwen and gpt-oss spend output tokens on thinking that the candidate never
    # hears, against that same cap. Asking one question needs no deliberation,
    # and turning it off roughly halved the tokens per turn in testing.
    llm_reasoning_effort: str = "none"

    # --- The tool call the candidate is meant to interrupt ----------------
    # The brief's proof procedure asks for a fixed delay in a tool call, so
    # there is a real window to cut across work that is genuinely in flight.
    # Lengthen it when recording if the window is tight to hit by hand.
    lookup_delay_seconds: float = 3.0

    def missing(self) -> list[str]:
        """Which credentials are absent, so startup can fail with a useful message."""
        required = {
            "RIME_API_KEY": self.rime_api_key,
            "LIVEKIT_URL": self.livekit_url,
            "LIVEKIT_API_KEY": self.livekit_api_key,
            "LIVEKIT_API_SECRET": self.livekit_api_secret,
            "DEEPGRAM_API_KEY": self.deepgram_api_key,
            "LLM_API_KEY": self.llm_api_key,
        }
        return sorted(name for name, value in required.items() if not value.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
