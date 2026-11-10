"""Provider-agnostic LLM gateway.

Models are configured as "provider:model" strings, per role:
    LLM_DEFAULT_MODEL=ollama:qwen2.5:7b
    LLM_MODELS={"answer": "groq:openai/gpt-oss-120b", "planner": "gemini:gemini-2.5-flash"}

Callers ask for a role (`get_chat_model("answer")`), never a provider, so swapping models is
configuration only. Every call site gets the model's identity back for logging/evaluation.
"""

from dataclasses import dataclass
from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from watchdog_backend.config import get_settings

PROVIDERS = ("ollama", "groq", "gemini")


class LLMConfigError(ValueError):
    pass


class LLMCallError(RuntimeError):
    """The provider failed (bad key, rate limit, timeout, unknown model, server down…)."""

    def __init__(self, model_id: str, cause: BaseException) -> None:
        self.model_id = model_id
        self.reason = describe_provider_error(cause)
        super().__init__(f"{model_id}: {self.reason}")


def describe_provider_error(exc: BaseException) -> str:
    """A short, user-facing reason. Provider SDK errors never include the API key."""
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    hints = {
        401: "the provider rejected the API key (check the key in .env)",
        403: "the API key is not allowed to use this model",
        404: "the model was not found (check the model name)",
        429: "rate limit or free-tier quota reached; try again shortly or switch model",
    }
    if status in hints:
        return hints[status]
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)) or "connect" in str(exc).lower():
        return f"could not reach the model server ({type(exc).__name__})"
    message = getattr(exc, "message", None) or str(exc)
    return f"{type(exc).__name__}: {message[:200]}"


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str

    @property
    def id(self) -> str:
        return f"{self.provider}:{self.model}"

    @classmethod
    def parse(cls, value: str) -> "ModelSpec":
        provider, sep, model = value.partition(":")
        if not sep or provider not in PROVIDERS or not model:
            raise LLMConfigError(
                f"Invalid model {value!r}: expected 'provider:model' with provider in {PROVIDERS}"
            )
        return cls(provider, model)


def model_for_role(role: str) -> ModelSpec:
    s = get_settings()
    return ModelSpec.parse(s.llm_models.get(role, s.llm_default_model))


def build_chat_model(spec: ModelSpec, temperature: float = 0.0) -> BaseChatModel:
    s = get_settings()
    if spec.provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=spec.model,
            base_url=s.ollama_base_url,
            temperature=temperature,
            num_ctx=8192,  # Ollama defaults to 4096, too small for investigation prompts
            client_kwargs={"timeout": s.llm_timeout_seconds},
        )
    if spec.provider == "groq":
        if not s.groq_api_key:
            raise LLMConfigError("GROQ_API_KEY is not set")
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=spec.model,
            api_key=s.groq_api_key,
            temperature=temperature,
            timeout=s.llm_timeout_seconds,
            max_retries=2,
        )
    if not s.gemini_api_key:
        raise LLMConfigError("GEMINI_API_KEY is not set")
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=spec.model,
        google_api_key=s.gemini_api_key,
        temperature=temperature,
        timeout=s.llm_timeout_seconds,
        max_retries=2,
    )


@lru_cache
def get_chat_model(role: str = "default") -> tuple[BaseChatModel, ModelSpec]:
    spec = model_for_role(role)
    return build_chat_model(spec), spec
