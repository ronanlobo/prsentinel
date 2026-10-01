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

# Which provider gave the most recent answer. It starts empty and is set only
# on the way out of a successful call, so it always names the provider that
# actually produced the text we are holding.
#
# This exists so a run can report where its answers came from. It holds a
# provider name or nothing at all. No key, no header, no part of a key, and
# nothing else from the call, ever goes in here.
LAST_PROVIDER = ""

# Whether we may try the second provider when the first one will not answer.
# On by default, which is how the tool has always behaved. A run can turn it off
# with --no-fallback so that running out for the day stops everything instead of
# quietly switching models halfway through and mixing two sets of answers into
# one score.
ALLOW_FALLBACK = True

# How many calls have gone out, so a run that stops can say how far it got.
CALLS_MADE = 0


class DailyLimitReached(RuntimeError):
    """A provider said it has no allowance left for today.

    This is not the same as being too fast for a moment. A per-minute limit
    clears itself and waiting is the right thing to do. A daily limit does not,
    so retrying the same provider wastes time and can never work. This is
    raised instead of retrying, and a run that has forbidden fallback stops on
    it rather than quietly answering from a different model.
    """

# Words that mean "you are going too fast, wait a moment".
RATE_LIMIT_WORDS = ("429", "rate limit", "rate_limit", "resource_exhausted")

# Words that mean the allowance for the whole day is used up. Waiting does not
# help with these, so they must not be retried.
#
# We look for the day alongside a limit, because that is what tells them apart
# from a per-minute limit. Both providers say it plainly: Groq writes "tokens per
# day (TPD)", Gemini writes "requests per day" or "per day".
DAILY_LIMIT_WORDS = (
    "per day",
    "tokens per day",
    "requests per day",
    "daily limit",
    "daily rate limit",
    "daily quota",
    "quota exceeded",
    "exceeded your current quota",
    "resource_exhausted: daily",
)


def is_daily_limit_error(error) -> bool:
    """Return True if this error means "not again until tomorrow".

    A per-minute limit says nothing about the day and waiting clears it, so the
    two must never be confused. Getting this wrong either wastes minutes
    retrying a provider that will never answer again, or gives up on a provider
    that would have answered after a short wait.
    """
    text = str(error).lower()

    if not any(word in text for word in RATE_LIMIT_WORDS):
        # Not a limit at all, so it cannot be a daily one.
        return False

    return any(word in text for word in DAILY_LIMIT_WORDS)

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


def call_with_retry(provider_name: str, provider_call, prompt: str,
                    temperature=None) -> str:
    """Call a provider, and wait and try again if it says we are going too fast.

    A rate limit is waited out and retried. Anything else, such as a wrong
    key, is raised straight away so we do not waste time. If the retries run
    out, the last error is raised and ask_llm moves on to the next provider.

    temperature is passed on to the provider when it is not None. Leaving it
    out means we send nothing and the provider picks its own.
    """
    wait = float(config.WAIT_SECONDS)
    attempt = 0

    while True:
        try:
            return provider_call(prompt, temperature)
        except Exception as error:
            # Checked before the retry, because a daily limit must never be
            # waited on. Retrying it can only waste time and it can never work.
            if is_daily_limit_error(error):
                raise DailyLimitReached(
                    f"{provider_name} has no allowance left for today. "
                    f"{str(error)[:200]}"
                ) from error

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


def ask_llm(prompt: str, temperature=None) -> str:
    """Send a prompt to an LLM and return the answer as text.

    Tries Groq first. If Groq fails (no key, server error, rate limit) it
    automatically tries Gemini. Raises RuntimeError if both fail.

    temperature is optional. Leave it out and nothing is sent, so the provider
    uses its own default. That is what the failure classifier does. Pass a
    number when writing new tests, so they come out as predictable as we can
    make them.
    """
    if not prompt or not prompt.strip():
        raise ValueError("The prompt is empty, so there is nothing to ask.")

    global LAST_PROVIDER
    global CALLS_MADE

    # --- Try Groq first -----------------------------------------------------
    if config.has_groq_key():
        try:
            CALLS_MADE += 1
            answer = call_with_retry("Groq", _ask_groq, prompt, temperature)
            LAST_PROVIDER = "Groq"
            print(f"[prsentinel] answer came from Groq ({config.GROQ_MODEL})")
            return answer
        except DailyLimitReached as error:
            # Out for the day, not just for a moment. Whether that ends the run
            # or starts the other provider is up to the caller.
            LAST_PROVIDER = ""
            if not ALLOW_FALLBACK:
                raise
            print(f"[prsentinel] Groq is out for the day ({error}). "
                  f"Trying Gemini...")
        except Exception as error:
            print(f"[prsentinel] Groq did not work ({error}). Trying Gemini...")
    else:
        print("[prsentinel] GROQ_API_KEY is not set, so we skip Groq.")

    # --- Then fall back to Gemini ------------------------------------------
    if config.has_gemini_key():
        try:
            CALLS_MADE += 1
            answer = call_with_retry("Gemini", _ask_gemini, prompt, temperature)
            LAST_PROVIDER = "Gemini"
            print(f"[prsentinel] answer came from Gemini ({config.GEMINI_MODEL})")
            return answer
        except DailyLimitReached as error:
            # Both providers out for the day. There is nothing left to try, so
            # this ends the run whatever the caller asked for.
            LAST_PROVIDER = ""
            raise
        except Exception as error:
            print(f"[prsentinel] Gemini did not work either ({error}).")
    else:
        print("[prsentinel] GEMINI_API_KEY is not set, so we cannot fall back.")

    # Nobody answered, so there is no provider to name. Clearing it stops a
    # failed call from looking like it came from whoever answered last.
    LAST_PROVIDER = ""

    raise RuntimeError(
        "No LLM could answer. Check GROQ_API_KEY and GEMINI_API_KEY."
    )


def _ask_groq(prompt: str, temperature=None) -> str:
    """Send the prompt to Groq and return the answer as text.

    temperature is only sent when it is not None. Sending nothing leaves Groq
    to use its own default, which is what the classifier relies on.
    """
    # Imported here, not at the top, so the project still works if this
    # package is not installed.
    from groq import Groq

    client = Groq(
        api_key=config.get_groq_api_key(),
        default_headers={"User-Agent": USER_AGENT},
    )

    settings = {"model": config.GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}]}
    if temperature is not None:
        settings["temperature"] = temperature

    response = client.chat.completions.create(**settings)
    return response.choices[0].message.content or ""


def _ask_gemini(prompt: str, temperature=None) -> str:
    """Send the prompt to Gemini and return the answer as text.

    temperature is only sent when it is not None. Sending nothing leaves
    Gemini to use its own default, which is what the classifier relies on.
    """
    # Imported here so the project still works if this package is missing.
    from google import genai

    # Turn off the SDK's noisy note before it can print anything.
    quiet_gemini_afc_note()

    client = genai.Client(api_key=config.get_gemini_api_key())

    settings = {"model": config.GEMINI_MODEL, "contents": prompt}
    if temperature is not None:
        settings["config"] = {"temperature": temperature}

    response = client.models.generate_content(**settings)
    return response.text or ""
