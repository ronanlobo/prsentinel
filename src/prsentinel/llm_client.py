"""Ask an LLM a question and get an answer back as plain text.

The plan is simple: try Groq first because it is fast and cheap. If that
does not work, fall back to Gemini.

If a provider says we are going too fast (a rate limit), we wait and try that
same provider again before moving on. Real errors, such as a wrong API key,
are not retried because trying again would not help.

Why use the official Groq package and not plain urllib?
An earlier attempt used urllib and Cloudflare blocked it with error 1010
because urllib sends a strange User-Agent. The official package sends a
normal User-Agent, so it gets through. We also send our own User-Agent
just to be safe.
"""

import logging
import re
import time

from . import config

# We send this so the servers know which tool is calling them.
USER_AGENT = "prsentinel/0.1.0"

# The Gemini SDK sends this note through the logging system, which makes
# PowerShell paint a red error on stderr even though the call worked fine.
GEMINI_NOISY_TEXT = "automatic function calling"

# The exact logger name the SDK uses. Note the underscore in "google_genai".
GEMINI_LOGGER_NAME = "google_genai.models"

# Words that mean "you are going too fast, wait a moment".
RATE_LIMIT_WORDS = ("429", "rate limit", "rate_limit", "resource_exhausted")

# The provider sometimes says how long to wait. We look for these shapes,
# for example: 'Please retry in 42.8s' or '"retryDelay": "42s"'.
WAIT_HINT_PATTERNS = (
    re.compile(r"retry\s+in\s+([\d.]+)\s*s", re.IGNORECASE),
    re.compile(r"retrydelay['\"]?\s*[:=]\s*['\"]?\s*([\d.]+)", re.IGNORECASE),
)


def is_rate_limit_error(error) -> bool:
    """Return True if this error means "wait a moment", not "give up".

    Both providers use their own exception classes, so instead of importing
    them we look at what the error says. Real problems such as a wrong API
    key or a bad request are not rate limits, so they are never retried.
    """
    text = str(error).lower()
    return any(word in text for word in RATE_LIMIT_WORDS)


def seconds_to_wait(error, attempt: int) -> float:
    """Return how many seconds to wait before try number `attempt` again.

    If the provider told us how long to wait, we use its number, but never
    more than MAX_WAIT_SECONDS. If it said nothing, we double: 15, 30, 60.
    """
    text = str(error)
    for pattern in WAIT_HINT_PATTERNS:
        found = pattern.search(text)
        if found:
            try:
                suggested = float(found.group(1))
            except ValueError:
                continue
            if suggested > 0:
                return min(suggested, float(config.MAX_WAIT_SECONDS))

    return float(config.WAIT_SECONDS) * (2 ** attempt)


def call_with_retry(provider_name: str, provider_call, prompt: str) -> str:
    """Call a provider, and wait and try again if it says we are going too fast.

    A rate limit is waited out and retried. Anything else, such as a wrong
    key, is raised straight away so we do not waste time. If the retries run
    out, the last error is raised and ask_llm moves on to the next provider.
    """
    wait = float(config.WAIT_SECONDS)
    attempt = 0

    while True:
        try:
            return provider_call(prompt)
        except Exception as error:
            if not is_rate_limit_error(error):
                # Not a rate limit, so trying again will not help.
                raise

            if attempt >= config.MAX_RETRIES:
                print(f"[prsentinel] {provider_name}: still rate limited after "
                      f"{attempt} retries, so we stop trying it.")
                raise

            seconds = seconds_to_wait(error, attempt)
            print(f"[prsentinel] {provider_name} is rate limited. "
                  f"Waiting {seconds:g}s, then retry {attempt + 1} of "
                  f"{config.MAX_RETRIES}.")
            time.sleep(seconds)
            attempt += 1


class _DropGeminiAfcNote(logging.Filter):
    """Drops the SDK's automatic-function-calling note and nothing else."""

    def filter(self, record):
        # True means "let this record through". Only the note is removed.
        return GEMINI_NOISY_TEXT not in record.getMessage()


def quiet_gemini_afc_note() -> None:
    """Stop the SDK printing its automatic-function-calling note.

    We attach the filter to one named logger, so real warnings and real
    errors from Gemini are still shown. Nothing is hidden.
    """
    if config.GEMINI_FILTERS_ADDED:
        return  # Already done, so do not pile up copies of the same filter.

    logging.getLogger(GEMINI_LOGGER_NAME).addFilter(_DropGeminiAfcNote())
    config.GEMINI_FILTERS_ADDED += 1


def ask_llm(prompt: str) -> str:
    """Send a prompt to an LLM and return the answer as text.

    Tries Groq first. If Groq fails (no key, server error, rate limit) it
    automatically tries Gemini. Raises RuntimeError if both fail.
    """
    if not prompt or not prompt.strip():
        raise ValueError("The prompt is empty, so there is nothing to ask.")

    # --- Try Groq first -----------------------------------------------------
    if config.has_groq_key():
        try:
            answer = call_with_retry("Groq", _ask_groq, prompt)
            print(f"[prsentinel] answer came from Groq ({config.GROQ_MODEL})")
            return answer
        except Exception as error:
            print(f"[prsentinel] Groq did not work ({error}). Trying Gemini...")
    else:
        print("[prsentinel] GROQ_API_KEY is not set, so we skip Groq.")

    # --- Then fall back to Gemini ------------------------------------------
    if config.has_gemini_key():
        try:
            answer = call_with_retry("Gemini", _ask_gemini, prompt)
            print(f"[prsentinel] answer came from Gemini ({config.GEMINI_MODEL})")
            return answer
        except Exception as error:
            print(f"[prsentinel] Gemini did not work either ({error}).")
    else:
        print("[prsentinel] GEMINI_API_KEY is not set, so we cannot fall back.")

    raise RuntimeError(
        "No LLM could answer. Check GROQ_API_KEY and GEMINI_API_KEY."
    )


def _ask_groq(prompt: str) -> str:
    """Send the prompt to Groq and return the answer as text."""
    # Imported here, not at the top, so the project still works if this
    # package is not installed.
    from groq import Groq

    client = Groq(
        api_key=config.get_groq_api_key(),
        default_headers={"User-Agent": USER_AGENT},
    )
    response = client.chat.completions.create(
        model=config.GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


def _ask_gemini(prompt: str) -> str:
    """Send the prompt to Gemini and return the answer as text."""
    # Imported here so the project still works if this package is missing.
    from google import genai

    # Turn off the SDK's noisy note before it can print anything.
    quiet_gemini_afc_note()

    client = genai.Client(api_key=config.get_gemini_api_key())
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
    )
    return response.text or ""
