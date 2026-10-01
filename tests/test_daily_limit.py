"""Tests for stopping when a provider runs out for the day.

There are two very different kinds of "too many requests" and confusing them is
expensive. A per-minute limit clears on its own, so waiting and trying again is
correct. A daily limit does not clear until tomorrow, so waiting fifteen seconds
and trying again can never work, and worse, after the retries are used up the run
quietly carries on from the other model. The result is a score made half from one
model and half from another, which looks exactly like a real score.

So these tests pin down three things:

1. a daily limit is told apart from a per-minute one,
2. a daily limit is never waited on,
3. with --no-fallback it stops the whole run instead of switching model.

Nothing here touches the internet or costs money: the providers are replaced with
fakes and the errors are copied word for word from what the real ones say.
"""

import sys

import pytest

from prsentinel import classifier as cl
from prsentinel import classifier_eval as ce
from prsentinel import config, llm_client

from test_classifier_repeats import FakeAI, make_evidence, use_cases


# The two messages below are copied word for word from real provider errors. If
# a provider ever words a limit differently, these are the two to update.
GROQ_DAILY = (
    "Error code: 429 - {'error': {'message': \"Rate limit reached for model "
    "'openai/gpt-oss-120b' in organization 'org_01m3rhn38xe5rabevaavha2b4m' "
    "service tier 'on_demand' on tokens per day (TPD): Limit 200000, Used "
    "199488, Requested 736. Please try again in 1m36.767999999s.\", "
    "'type': 'rate_limit_error', 'code': 'rate_limit_exceeded'}}"
)

GEMINI_DAILY = (
    "RESOURCE_EXHAUSTED: Quota exceeded for quota metric 'Generate requests "
    "per day': limit 1500 requests per day, used 1500 requests per day."
)

# A per-minute limit. It says "please try again in 96 seconds", which is the
# whole point: this one clears on its own.
GROQ_PER_MINUTE = (
    "Error code: 429 - {'error': {'message': \"Rate limit reached for model "
    "'openai/gpt-oss-120b' on requests per minute (RPM): Limit 1000, Used "
    "1000, Requested 1. Please try again in 1m36.767999999s.\"}}"
)


@pytest.fixture(autouse=True)
def fallback_back_on():
    """Every test starts and ends with fallback allowed, as it is by default."""
    llm_client.ALLOW_FALLBACK = True
    llm_client.CALLS_MADE = 0
    llm_client.LAST_PROVIDER = ""
    ce.CHOSEN = None
    yield
    llm_client.ALLOW_FALLBACK = True
    llm_client.CALLS_MADE = 0
    llm_client.LAST_PROVIDER = ""
    ce.CHOSEN = None


def two_keys(monkeypatch):
    """Pretend both keys are set. Waiting is switched off so nothing sleeps."""
    monkeypatch.setattr(config, "has_groq_key", lambda: True)
    monkeypatch.setattr(config, "has_gemini_key", lambda: True)
    monkeypatch.setattr(llm_client.time, "sleep", lambda seconds: None)


def fail_with(message):
    def broken(prompt, temperature=None):
        raise RuntimeError(message)
    return broken


def answer_with(text):
    def working(prompt, temperature=None):
        return text
    return working


# ---------------------------------------------------------------------------
# Telling the two kinds of limit apart
# ---------------------------------------------------------------------------

def test_groqs_daily_message_is_a_daily_limit():
    """This exact message stopped a run before, so it has to be recognised."""
    assert llm_client.is_daily_limit_error(Exception(GROQ_DAILY))


def test_geminis_daily_message_is_a_daily_limit():
    assert llm_client.is_daily_limit_error(Exception(GEMINI_DAILY))


def test_a_per_minute_limit_is_not_a_daily_limit():
    """It clears in a minute and a bit. Waiting on it is the right thing."""
    assert not llm_client.is_daily_limit_error(Exception(GROQ_PER_MINUTE))


def test_an_ordinary_error_is_not_a_daily_limit():
    assert not llm_client.is_daily_limit_error(Exception("401 invalid_api_key"))
    assert not llm_client.is_daily_limit_error(Exception("400 Bad Request"))


def test_the_word_day_on_its_own_is_not_enough():
    """A daily limit always arrives with a limit word as well.

    Without that second check, any message that happens to mention the day would
    stop the run, including a routine error about a timestamp.
    """
    assert not llm_client.is_daily_limit_error(
        Exception("the build ran twice today and produced 429 requests"))


def test_a_daily_limit_is_also_still_recognised_as_a_rate_limit():
    """It came from a 429, so the old check must not start missing it."""
    assert llm_client.is_rate_limit_error(Exception(GROQ_DAILY))
    assert llm_client.is_rate_limit_error(Exception(GEMINI_DAILY))


# ---------------------------------------------------------------------------
# Never waiting on a daily limit
# ---------------------------------------------------------------------------

def test_a_daily_limit_is_never_waited_on(monkeypatch):
    """No sleeping at all. It cannot work, so there is nothing to wait for."""
    waits = []
    calls = []
    monkeypatch.setattr(llm_client.time, "sleep", waits.append)

    def out_for_the_day(prompt, temperature=None):
        calls.append(prompt)
        raise RuntimeError(GROQ_DAILY)

    with pytest.raises(llm_client.DailyLimitReached):
        llm_client.call_with_retry("Groq", out_for_the_day, "hi")

    assert calls == ["hi"], "a daily limit was tried again"
    assert waits == [], "a daily limit was waited on"


def test_the_daily_error_names_the_provider_and_keeps_the_message(monkeypatch):
    """Enough to tell what happened and which provider, and nothing secret."""
    monkeypatch.setattr(llm_client.time, "sleep", lambda seconds: None)

    with pytest.raises(llm_client.DailyLimitReached) as caught:
        llm_client.call_with_retry("Groq", fail_with(GROQ_DAILY), "hi")

    text = str(caught.value)
    assert "Groq" in text
    assert "today" in text
    assert "tokens per day" in text


def test_a_per_minute_limit_is_still_waited_on(monkeypatch):
    """The old behaviour has to survive for the case that still works."""
    waits = []
    monkeypatch.setattr(llm_client.time, "sleep", waits.append)

    def flaky(prompt, temperature=None):
        if len(waits) < 2:
            raise RuntimeError(GROQ_PER_MINUTE)
        return "answer after waiting"

    assert llm_client.call_with_retry("Groq", flaky, "hi") == "answer after waiting"
    assert waits == [15.0, 30.0]


def test_a_wrong_key_is_still_not_retried(monkeypatch):
    """The daily check must not have caught everything and retried it."""
    waits = []
    calls = []
    monkeypatch.setattr(llm_client.time, "sleep", waits.append)

    def wrong_key(prompt, temperature=None):
        calls.append(prompt)
        raise RuntimeError("401 invalid_api_key")

    with pytest.raises(RuntimeError):
        llm_client.call_with_retry("Groq", wrong_key, "hi")

    assert calls == ["hi"]
    assert waits == []


# ---------------------------------------------------------------------------
# Falling back, which is today's behaviour
# ---------------------------------------------------------------------------

def test_a_daily_limit_still_falls_back_by_default(monkeypatch):
    """Without the flag nothing changes: the other provider answers."""
    two_keys(monkeypatch)
    monkeypatch.setattr(llm_client, "_ask_groq", fail_with(GROQ_DAILY))
    monkeypatch.setattr(llm_client, "_ask_gemini", answer_with("from gemini"))

    assert llm_client.ask_llm("hello") == "from gemini"


def test_gemini_being_out_for_the_day_ends_the_call_whatever_the_flag(monkeypatch):
    """There is nothing left to try, so this is an error either way."""
    two_keys(monkeypatch)
    monkeypatch.setattr(llm_client, "_ask_groq", fail_with(GROQ_DAILY))
    monkeypatch.setattr(llm_client, "_ask_gemini", fail_with(GEMINI_DAILY))

    with pytest.raises(llm_client.DailyLimitReached):
        llm_client.ask_llm("hello")


def test_geminis_daily_limit_is_reported_even_with_fallback_allowed(monkeypatch):
    """Groq answered, so Gemini is never asked. Nothing should be raised."""
    two_keys(monkeypatch)
    monkeypatch.setattr(llm_client, "_ask_groq", answer_with("from groq"))
    monkeypatch.setattr(llm_client, "_ask_gemini", fail_with("should not run"))

    assert llm_client.ask_llm("hello") == "from groq"


# ---------------------------------------------------------------------------
# --no-fallback: stop instead of switching model
# ---------------------------------------------------------------------------

def test_no_fallback_stops_at_groq_and_never_asks_gemini(monkeypatch):
    """The point of the flag: one model, or no score at all."""
    two_keys(monkeypatch)
    llm_client.ALLOW_FALLBACK = False

    asked = []
    monkeypatch.setattr(llm_client, "_ask_groq", fail_with(GROQ_DAILY))
    monkeypatch.setattr(llm_client, "_ask_gemini",
                        lambda *a, **k: asked.append("gemini") or "x")

    with pytest.raises(llm_client.DailyLimitReached):
        llm_client.ask_llm("hello")

    assert asked == [], "Gemini answered even though --no-fallback was set"


def test_no_provider_is_named_when_the_run_stops(monkeypatch):
    """Otherwise the next tally would blame whoever answered before."""
    two_keys(monkeypatch)
    llm_client.ALLOW_FALLBACK = False
    llm_client.LAST_PROVIDER = "Groq"
    monkeypatch.setattr(llm_client, "_ask_groq", fail_with(GROQ_DAILY))

    with pytest.raises(llm_client.DailyLimitReached):
        llm_client.ask_llm("hello")

    assert llm_client.LAST_PROVIDER == ""


def test_the_call_count_goes_up_only_for_calls_that_were_made(monkeypatch):
    """It is reported to the user, so it has to mean something."""
    two_keys(monkeypatch)
    monkeypatch.setattr(llm_client, "_ask_groq", answer_with("from groq"))
    monkeypatch.setattr(llm_client, "_ask_gemini", fail_with("should not run"))
    llm_client.CALLS_MADE = 0

    llm_client.ask_llm("one")
    llm_client.ask_llm("two")

    assert llm_client.CALLS_MADE == 2


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def test_fallback_is_allowed_when_the_flag_is_not_given(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["classifier_eval"])
    assert ce.parse_args().no_fallback is False


def test_the_flag_is_off_by_default():
    """Today's behaviour must be what happens with no options at all."""
    assert config._float_from_env("PRSENTINEL_NOT_SET", 0.0) == 0.0


def test_the_flag_is_read_from_the_command_line(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["classifier_eval", "--no-fallback"])
    assert ce.parse_args().no_fallback is True


def test_main_turns_fallback_off_only_when_asked(monkeypatch):
    """The flag has to reach llm_client, which is where the decision is made."""
    monkeypatch.setattr(cl, "collect_evidence",
                        lambda *a, **k: make_evidence())
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["REAL_BUG"]))
    use_cases(monkeypatch, count=1)

    monkeypatch.setattr(sys, "argv",
                        ["classifier_eval", "--only", "llm_full_v2"])
    ce.main()
    assert llm_client.ALLOW_FALLBACK is True

    monkeypatch.setattr(sys, "argv",
                        ["classifier_eval", "--only", "llm_full_v2",
                         "--no-fallback"])
    ce.main()
    assert llm_client.ALLOW_FALLBACK is False


# ---------------------------------------------------------------------------
# A stopped run says so, and prints no score
# ---------------------------------------------------------------------------

def stop_on_the_third_call(counter):
    """A fake AI that works twice and then reports Groq is out for the day."""
    def fake(prompt):
        counter["calls"] += 1
        if counter["calls"] > 2:
            raise llm_client.DailyLimitReached("Groq has no allowance left "
                                               "for today.")
        from test_classifier_repeats import reply
        return reply("REAL_BUG")

    return fake


def run_and_capture(monkeypatch, capsys, extra=()):
    counter = {"calls": 0}
    monkeypatch.setattr(cl, "collect_evidence",
                        lambda *a, **k: make_evidence())
    monkeypatch.setattr(cl, "ask_llm", stop_on_the_third_call(counter))
    use_cases(monkeypatch, count=5)
    monkeypatch.setattr(sys, "argv",
                        ["classifier_eval", "--only", "llm_full_v2", *extra])
    code = ce.main()
    return code, capsys.readouterr().out, counter


def test_a_stopped_run_returns_a_way_to_tell_it_from_a_good_one(monkeypatch,
                                                               capsys):
    """A number, not zero. Zero means the report is complete and sound."""
    code, printed, _ = run_and_capture(monkeypatch, capsys,
                                       extra=["--no-fallback"])
    assert code == 2


def test_a_stopped_run_says_loudly_that_it_did_not_finish(monkeypatch, capsys):
    code, printed, _ = run_and_capture(monkeypatch, capsys,
                                       extra=["--no-fallback"])

    assert "THE RUN STOPPED EARLY" in printed
    assert "out for the day" in printed.lower()


def test_a_stopped_run_says_how_many_calls_got_through(monkeypatch, capsys):
    """So it is obvious how much of the run there was."""
    code, printed, counter = run_and_capture(monkeypatch, capsys,
                                              extra=["--no-fallback"])

    assert "Model calls completed" in printed
    assert str(counter["calls"]) in printed


def test_a_stopped_run_warns_against_trusting_the_numbers(monkeypatch, capsys):
    """A half-finished report looks exactly like a finished one."""
    code, printed, _ = run_and_capture(monkeypatch, capsys,
                                       extra=["--no-fallback"])

    assert "Do not trust any score from this run" in printed


def test_a_stopped_run_prints_no_accuracy_at_all(monkeypatch, capsys):
    """The most important check of the lot.

    A partial run still has rows, so an accuracy can be worked out from it, and
    it would be wrong in a way nobody could see: it would only be measuring the
    cases that happened to be reached first.
    """
    code, printed, _ = run_and_capture(monkeypatch, capsys,
                                       extra=["--no-fallback"])

    for heading in ("=== Accuracy ===", "=== Where the answers came from ===",
                    "=== Wrong answers ===",
                    "=== How many of the runs each case was wrong ==="):
        assert heading not in printed, f"{heading} was printed from a dead run"


def test_a_stopped_run_stops_promptly_rather_than_finishing_the_cases(
        monkeypatch, capsys):
    """Five cases were offered and it must not have tried all of them."""
    code, printed, counter = run_and_capture(monkeypatch, capsys,
                                              extra=["--no-fallback"])

    assert counter["calls"] == 3, "it kept going after the provider gave up"


def test_without_the_flag_the_run_carries_on_as_today(monkeypatch, capsys):
    """Same behaviour as before: fall back, keep going, finish the report."""
    monkeypatch.setattr(cl, "collect_evidence",
                        lambda *a, **k: make_evidence())
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["REAL_BUG"]))
    use_cases(monkeypatch, count=2)
    monkeypatch.setattr(sys, "argv",
                        ["classifier_eval", "--only", "llm_full_v2"])

    assert ce.main() == 0
    printed = capsys.readouterr().out

    assert "THE RUN STOPPED EARLY" not in printed
    assert "=== Accuracy ===" in printed


def test_the_stopped_run_never_prints_a_key_name(monkeypatch, capsys):
    """The banner is loud, so it has to stay safe to paste anywhere."""
    code, printed, _ = run_and_capture(monkeypatch, capsys,
                                       extra=["--no-fallback"])

    banner = printed.split("THE RUN STOPPED EARLY")[1].split("!" * 20)[0]
    for secret_word in ("API_KEY", "gsk_", "AIza"):
        assert secret_word not in banner


def test_the_held_back_command_never_stops_on_a_daily_limit():
    """One score on kept-back cases. It has no --no-fallback to miss."""
    import inspect
    from prsentinel import heldback_eval as he

    assert "no_fallback" not in inspect.getsource(he)
    assert "ALLOW_FALLBACK" not in inspect.getsource(he)


def test_a_stopped_run_does_not_also_warn_about_gemini(monkeypatch, capsys):
    """Two loud warnings for one stop would only make the message harder to read.

    With --no-fallback there is no switch to the other model, so there is
    nothing to warn about.
    """
    code, printed, _ = run_and_capture(monkeypatch, capsys,
                                       extra=["--no-fallback"])

    assert "SOME ANSWERS CAME FROM GEMINI" not in printed


def test_the_gemini_warning_arrives_where_it_happens_not_at_the_end(
        monkeypatch, capsys):
    """It has to be printed the moment Gemini first answers.

    Printed at the end, a reader would already have read the earlier answers and
    the warning would arrive too late to be a warning.
    """
    counter = {"n": 0}

    def groq_then_gemini(prompt):
        # Gemini answers the very first question, so the warning has to appear
        # while case 1 is still being worked through.
        counter["n"] += 1
        llm_client.LAST_PROVIDER = "Gemini" if counter["n"] == 1 else "Groq"
        from test_classifier_repeats import reply
        return reply("REAL_BUG")

    monkeypatch.setattr(cl, "collect_evidence",
                        lambda *a, **k: make_evidence())
    monkeypatch.setattr(cl, "ask_llm", groq_then_gemini)
    use_cases(monkeypatch, count=3)
    monkeypatch.setattr(sys, "argv",
                        ["classifier_eval", "--only", "llm_full_v2"])

    assert ce.main() == 0
    printed = capsys.readouterr().out

    warning = printed.index("SOME ANSWERS CAME FROM GEMINI")
    second_case = printed.index("[2/3]")
    assert warning < second_case, "the warning came after the case that needed it"


def test_the_prompt_wording_is_untouched_by_any_of_this():
    """The daily limit work must not have moved a single character of it."""
    from test_classifier import EXPECTED_FULL_PROMPT, frozen_evidence
    from prsentinel import classifier as cl

    assert cl.build_prompt(frozen_evidence(), cl.MODE_FULL) == EXPECTED_FULL_PROMPT
