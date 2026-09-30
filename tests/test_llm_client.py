"""Tests for the LLM fallback.

Nothing here touches the internet. Both providers are replaced with fakes, so
these tests run anywhere and never cost money.
"""

import logging

import pytest

from prsentinel import config, llm_client


def fail_with(message):
    """Return a stand-in provider that always breaks."""
    def broken(prompt, temperature=None):
        raise RuntimeError(message)
    return broken


def answer_with(text):
    """Return a stand-in provider that always answers with the same text."""
    def working(prompt, temperature=None):
        return text
    return working


def set_up_two_keys(monkeypatch):
    """Pretend both API keys are set, so both providers are tried.

    This also switches off the real waiting. A fake provider whose message
    contains "rate limit" would otherwise really sleep for a minute.
    """
    monkeypatch.setattr(config, "has_groq_key", lambda: True)
    monkeypatch.setattr(config, "has_gemini_key", lambda: True)
    monkeypatch.setattr(llm_client.time, "sleep", lambda seconds: None)


def test_groq_is_used_when_it_works(monkeypatch):
    """If Groq answers, we use it and never bother Gemini."""
    set_up_two_keys(monkeypatch)
    monkeypatch.setattr(llm_client, "_ask_groq", answer_with("from groq"))
    monkeypatch.setattr(llm_client, "_ask_gemini", fail_with("should not run"))
    assert llm_client.ask_llm("hello") == "from groq"


def test_falls_back_to_gemini_when_groq_fails(monkeypatch):
    """A broken Groq must not stop us, Gemini answers instead."""
    set_up_two_keys(monkeypatch)
    monkeypatch.setattr(llm_client, "_ask_groq", fail_with("rate limited"))
    monkeypatch.setattr(llm_client, "_ask_gemini", answer_with("from gemini"))
    assert llm_client.ask_llm("hello") == "from gemini"


def test_a_given_temperature_reaches_the_provider(monkeypatch):
    """A temperature we ask for is handed on to the provider."""
    set_up_two_keys(monkeypatch)
    seen = []

    def recording(prompt, temperature=None):
        seen.append(temperature)
        return "answer"

    monkeypatch.setattr(llm_client, "_ask_groq", recording)
    llm_client.ask_llm("hello", 0.0)

    assert seen == [0.0]


def test_no_temperature_is_sent_unless_one_is_asked_for(monkeypatch):
    """Leaving it out means we send nothing, so the provider uses its own.

    This is the path the failure classifier takes, and it must stay untouched.
    """
    set_up_two_keys(monkeypatch)
    seen = []

    def recording(prompt, temperature=None):
        seen.append(temperature)
        return "answer"

    monkeypatch.setattr(llm_client, "_ask_groq", recording)
    llm_client.ask_llm("hello")

    assert seen == [None]


def test_a_temperature_survives_the_fallback_to_gemini(monkeypatch):
    """The backup provider must get the same temperature as the first one."""
    set_up_two_keys(monkeypatch)
    seen = []

    def groq_fails(prompt, temperature=None):
        raise RuntimeError("groq is down")

    def gemini_answers(prompt, temperature=None):
        seen.append(temperature)
        return "from gemini"

    monkeypatch.setattr(llm_client, "_ask_groq", groq_fails)
    monkeypatch.setattr(llm_client, "_ask_gemini", gemini_answers)

    assert llm_client.ask_llm("hello", 0.0) == "from gemini"
    assert seen == [0.0], "Gemini must get the temperature too"


def test_the_default_temperature_is_zero():
    """The setting starts at 0, which asks for the most predictable answer."""
    assert config._float_from_env("PRSENTINEL_A_NAME_THAT_IS_NOT_SET", 0.0) == 0.0


def test_both_failing_raises_a_clear_error(monkeypatch):
    """If neither provider works we must say so out loud, not fail quietly."""
    set_up_two_keys(monkeypatch)
    monkeypatch.setattr(llm_client, "_ask_groq", fail_with("groq is down"))
    monkeypatch.setattr(llm_client, "_ask_gemini", fail_with("gemini is down"))
    with pytest.raises(RuntimeError, match="No LLM could answer"):
        llm_client.ask_llm("hello")


def test_empty_prompt_is_rejected(monkeypatch):
    """There is no point spending an API call on an empty question."""
    set_up_two_keys(monkeypatch)
    with pytest.raises(ValueError):
        llm_client.ask_llm("   ")


def test_gemini_filter_drops_only_the_sdk_note():
    """The filter must hide the one noisy note and nothing else."""
    llm_client.quiet_gemini_afc_note()
    noisy = logging.LogRecord("x", logging.WARNING, "f", 1,
                              "Direct use of automatic function calling (AFC)",
                              None, None)
    real = logging.LogRecord("x", logging.WARNING, "f", 1,
                             "API key is invalid", None, None)

    installed = logging.getLogger(llm_client.GEMINI_LOGGER_NAME).filters
    assert installed, "the filter was never installed"
    assert installed[0].filter(noisy) is False
    assert installed[0].filter(real) is True


# ---------------------------------------------------------------------------
# Waiting and retrying when a provider says we are going too fast
# ---------------------------------------------------------------------------

def test_rate_limit_is_recognised():
    """The words the providers use for a rate limit must be spotted."""
    assert llm_client.is_rate_limit_error(Exception("Error code: 429"))
    assert llm_client.is_rate_limit_error(Exception("RESOURCE_EXHAUSTED"))
    assert llm_client.is_rate_limit_error(Exception("Rate limit reached"))
    assert not llm_client.is_rate_limit_error(Exception("Invalid API Key"))
    assert not llm_client.is_rate_limit_error(Exception("400 Bad Request"))


def test_wait_comes_from_the_message_when_it_says_so():
    """Gemini tells us how long to wait, so we use its number."""
    error = Exception('... "retryDelay": "42s" ...')
    assert llm_client.seconds_to_wait(error, 0) == 42.0


def test_wait_from_a_message_is_capped():
    """A silly long wait must not hang the program."""
    error = Exception("Please retry in 9999s.")
    assert llm_client.seconds_to_wait(error, 0) == float(config.MAX_WAIT_SECONDS)


def test_wait_doubles_when_the_message_says_nothing():
    """With no hint we wait 15, then 30, then 60."""
    error = Exception("Error code: 429")
    assert llm_client.seconds_to_wait(error, 0) == 15.0
    assert llm_client.seconds_to_wait(error, 1) == 30.0
    assert llm_client.seconds_to_wait(error, 2) == 60.0


def test_retries_then_succeeds(monkeypatch):
    """A rate limit that clears is waited out, and we still get the answer."""
    calls = []
    waits = []
    monkeypatch.setattr(llm_client.time, "sleep", waits.append)

    def flaky(prompt, temperature=None):
        calls.append(prompt)
        if len(calls) < 3:
            raise Exception("Error code: 429")
        return "answer after waiting"

    assert llm_client.call_with_retry("Fake", flaky, "hi") == "answer after waiting"
    assert len(calls) == 3          # failed twice, then worked
    assert waits == [15.0, 30.0]    # no hint in the message, so we doubled


def test_gives_up_after_max_retries_and_falls_back(monkeypatch):
    """When Groq stays rate limited we stop and Gemini answers."""
    monkeypatch.setattr(llm_client.time, "sleep", lambda seconds: None)
    set_up_two_keys(monkeypatch)

    def always_limited(prompt, temperature=None):
        raise Exception("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(llm_client, "_ask_groq", always_limited)
    monkeypatch.setattr(llm_client, "_ask_gemini", answer_with("from gemini"))

    assert llm_client.ask_llm("hello") == "from gemini"


def test_invalid_key_is_not_retried(monkeypatch):
    """A wrong key is not a rate limit, so we must not waste time on it."""
    waits = []
    calls = []
    monkeypatch.setattr(llm_client.time, "sleep", waits.append)
    set_up_two_keys(monkeypatch)

    def wrong_key(prompt, temperature=None):
        calls.append(prompt)
        raise Exception("401 invalid_api_key")

    monkeypatch.setattr(llm_client, "_ask_groq", wrong_key)
    monkeypatch.setattr(llm_client, "_ask_gemini", answer_with("from gemini"))

    assert llm_client.ask_llm("hello") == "from gemini"
    assert len(calls) == 1   # called once, then straight to Gemini
    assert waits == []       # no waiting at all
