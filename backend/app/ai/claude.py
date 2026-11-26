"""Claude API access shared by the AI assistant and the AI invoice reader.

The API key (ANTHROPIC_API_KEY) is read on the server only; nothing here is ever sent to
the browser. Every call uses server-side fallbacks: if the configured model declines a
request, the API re-runs it on Anthropic's default fallback model inside the same call.
"""

import logging
from typing import Any

import anthropic

from app.core.config import get_settings

logger = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIUnavailable(Exception):
    """The AI service could not answer; the message is safe to show to staff."""


_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    s = get_settings()
    if not s.anthropic_api_key:
        raise AIUnavailable(
            "The AI features are not set up: add ANTHROPIC_API_KEY to the server's .env file."
        )
    if _client is None:
        _client = anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=180.0, max_retries=2)
    return _client


def set_client(client: anthropic.Anthropic | None) -> None:
    """Used by tests to plug in a client whose HTTP transport is a fake."""
    global _client
    _client = client


def create(*, output_config: dict[str, Any] | None = None, **kw: Any) -> Any:
    """beta.messages.create with the configured model and effort and fallbacks enabled.

    Raises AIUnavailable with a readable reason for every API or network failure.
    """
    s = get_settings()
    config = {"effort": s.assistant_effort, **(output_config or {})}
    try:
        response = get_client().beta.messages.create(
            model=s.assistant_model,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config=config,
            **kw,
        )
    except anthropic.AuthenticationError as exc:
        raise AIUnavailable("The Claude API refused the API key (ANTHROPIC_API_KEY).") from exc
    except anthropic.PermissionDeniedError as exc:
        raise AIUnavailable("This API key is not allowed to use the Claude model.") from exc
    except anthropic.RateLimitError as exc:
        raise AIUnavailable("The AI service is busy. Please try again in a minute.") from exc
    except anthropic.APITimeoutError as exc:
        raise AIUnavailable("The AI service took too long to answer. Please try again.") from exc
    except anthropic.APIConnectionError as exc:
        raise AIUnavailable(
            "The AI service could not be reached. Check the server's internet connection."
        ) from exc
    except anthropic.APIStatusError as exc:
        logger.warning("Claude API error %s: %s", exc.status_code, str(exc)[:300])
        if exc.status_code == 402 or "credit" in str(exc).lower():
            raise AIUnavailable(
                "The Claude account has no credit left (console.anthropic.com → Billing)."
            ) from exc
        raise AIUnavailable(
            f"The AI service answered with an error (HTTP {exc.status_code})."
        ) from exc
    if response.stop_reason == "refusal":
        raise AIUnavailable("The AI declined this request.")
    return response


def text_of(response: Any) -> str:
    return "".join(b.text for b in response.content if b.type == "text").strip()


def usage_of(response: Any) -> dict[str, int]:
    u = response.usage
    return {
        "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
    }
