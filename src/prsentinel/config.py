"""All of the PRSentinel settings live in this one file.

Two rules for this file:

1. The model names are written once, at the top. If we want to try a different
   model later we only change them here.
2. API keys are NEVER written in the code. They are read from environment
   variables instead, so they stay out of version control.
"""

import os


def _int_from_env(name: str, default: int) -> int:
    """Read a whole number from the environment, or use the default."""
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw)
    except ValueError:
        return default


def _float_from_env(name: str, default: float) -> float:
    """Read a decimal number from the environment, or use the default."""
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Models. These are the only two places a model name is written down.
# ---------------------------------------------------------------------------

# The main model we use. It is tried first.
GROQ_MODEL = "openai/gpt-oss-120b"

# The backup model. It is only used if Groq fails or is rate limited.
GEMINI_MODEL = "gemini-3.5-flash"


# ---------------------------------------------------------------------------
# Retrying when a provider says "too many requests".
# ---------------------------------------------------------------------------

# How many extra tries we give a provider after a rate limit. So with this
# set to 3 we make 1 first try plus 3 retries, 4 calls at the very most.
MAX_RETRIES = _int_from_env("PRSENTINEL_MAX_RETRIES", 3)

# How long we wait before the first retry. Every wait after that is twice as
# long as the one before: 15, then 30, then 60 seconds.
WAIT_SECONDS = _int_from_env("PRSENTINEL_WAIT_SECONDS", 15)

# If the provider tells us in its message how long to wait, we use that number
# instead. This stops an odd or huge number from hanging the program.
MAX_WAIT_SECONDS = 120

# How many times we add the filter before giving up. If this function is
# called more than once we must not pile up copies of the same filter.
GEMINI_FILTERS_ADDED = 0


# ---------------------------------------------------------------------------
# Rerunning a test file to see if it is flaky.
# ---------------------------------------------------------------------------

# How many times we run a test file again to check whether it always gives the
# same answer. A test that passes once and fails once is flaky, so one run on
# its own is never enough to trust.
RERUN_TIMES = _int_from_env("PRSENTINEL_RERUN_TIMES", 5)


# ---------------------------------------------------------------------------
# Repairing a test the pipeline judged to be the wrong test.
# ---------------------------------------------------------------------------

# How many times we ask for the same test to be corrected before giving up. A
# test that still fails on the old code after this many tries is reported as
# unrepaired and left exactly as it was.
MAX_REPAIR_ATTEMPTS = _int_from_env("PRSENTINEL_MAX_REPAIR_ATTEMPTS", 2)

# The most repair calls one run may make altogether, across every test. One
# file can hold several wrong tests and every attempt is a call to the AI, so
# this stops a run with a lot of them from spending the whole day's allowance.
MAX_REPAIR_CALLS_PER_RUN = _int_from_env("PRSENTINEL_MAX_REPAIR_CALLS_PER_RUN",
                                         10)


# ---------------------------------------------------------------------------
# How creative the AI is allowed to be.
# ---------------------------------------------------------------------------

# This is used ONLY when the AI is writing new tests, and nowhere else. A
# temperature of 0 asks for the most predictable answer we can get, which is
# what we want when the job is to write tests that agree with the code.
#
# It does NOT make the AI perfectly repeatable. Even at 0, a hosted model can
# give a slightly different answer each time, so running the generator twice
# can still produce two different test files.
#
# The failure classifier does not use this setting. It keeps whatever
# temperature the provider chooses, so classifying is not affected by it.
GENERATION_TEMPERATURE = _float_from_env("PRSENTINEL_TEMPERATURE", 0.0)


# ---------------------------------------------------------------------------
# API keys. These come from the environment, never from the code.
# ---------------------------------------------------------------------------


def get_groq_api_key() -> str:
    """Return the Groq API key, or an empty string if it is not set."""
    return os.environ.get("GROQ_API_KEY", "").strip()


def get_gemini_api_key() -> str:
    """Return the Gemini API key, or an empty string if it is not set."""
    return os.environ.get("GEMINI_API_KEY", "").strip()


def has_groq_key() -> bool:
    """Return True if a Groq API key is available."""
    return bool(get_groq_api_key())


def has_gemini_key() -> bool:
    """Return True if a Gemini API key is available."""
    return bool(get_gemini_api_key())
