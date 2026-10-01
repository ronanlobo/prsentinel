"""Tests for the provider tally in `classifier_eval`.

A score with no provenance is not much use. Groq and Gemini are different
models, so an answer that came from the fallback has to be visible in the
report. These tests check that the count is right, that it is per classifier,
and above all that nothing sensitive can reach the printed table.

Nothing here makes a real call. The provider name is set the same way the real
client sets it, without any network or key involved.
"""

import sys

import pytest

from prsentinel import classifier as cl
from prsentinel import classifier_eval as ce
from prsentinel import llm_client

from test_classifier_repeats import FakeAI, make_evidence, reply, use_cases


def answer_from(provider):
    """Build a fake ask_llm that says which provider answered.

    This mirrors what llm_client.ask_llm does on the way out: set the name, hand
    back the text. Nothing else is recorded, which is the point.
    """
    def fake_ask(prompt):
        llm_client.LAST_PROVIDER = provider
        return reply("REAL_BUG")

    return fake_ask


@pytest.fixture(autouse=True)
def clean_tally():
    """Every test starts and ends with nothing counted."""
    ce.reset_provider_tally()
    llm_client.LAST_PROVIDER = ""
    yield
    ce.reset_provider_tally()
    llm_client.LAST_PROVIDER = ""


@pytest.fixture
def offline(monkeypatch):
    """Take the real test runner out of the picture."""
    monkeypatch.setattr(cl, "collect_evidence",
                        lambda *args, **kwargs: make_evidence())


def run_main(monkeypatch, repeats=1):
    monkeypatch.setattr(sys, "argv", ["classifier_eval", "--repeats",
                                      str(repeats)])
    return ce.main()


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------

def test_an_answer_from_groq_is_counted(monkeypatch, offline):
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch) == 0

    assert ce.PROVIDER_TALLY["llm_full"] == {"Groq": 1}


def test_each_classifier_is_counted_on_its_own(monkeypatch, offline):
    """One row per classifier, not one lump total.

    If a score for one classifier came from the fallback and another did not,
    the reader has to be able to see which is which.
    """
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch) == 0

    counted = set(ce.PROVIDER_TALLY)
    assert counted == set(ce.AI_CLASSIFIERS)
    # The rule asks nobody, so it must not be in the tally at all.
    assert "rule" not in counted


def test_the_count_grows_with_every_case_and_every_run(monkeypatch, offline):
    """The count has to be a real count, not a yes/no."""
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch, 3) == 0

    # Two cases, three runs, one count each.
    assert ce.PROVIDER_TALLY["llm_full"] == {"Groq": 6}


def test_both_providers_are_counted_separately(monkeypatch, offline):
    """A mixed run has to show both columns, not just that there was a mix."""
    # Four AI classifiers, two cases, one run, so eight answers.
    providers = iter(["Groq", "Gemini", "Groq", "Gemini",
                      "Groq", "Groq", "Groq", "Gemini"])

    def fake_ask(prompt):
        llm_client.LAST_PROVIDER = next(providers)
        return reply("REAL_BUG")

    monkeypatch.setattr(cl, "ask_llm", fake_ask)
    use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch) == 0

    groq = sum(counts.get("Groq", 0) for counts in ce.PROVIDER_TALLY.values())
    gemini = sum(counts.get("Gemini", 0)
                 for counts in ce.PROVIDER_TALLY.values())
    assert groq == 5
    assert gemini == 3
    # The two land on different classifiers, so the split is visible per row and
    # not just in the total. Two cases, so each classifier is asked twice.
    assert ce.PROVIDER_TALLY["llm_full"] == {"Groq": 2}
    assert ce.PROVIDER_TALLY["llm_full_with_intent"] == {"Groq": 1, "Gemini": 1}
    assert ce.PROVIDER_TALLY["llm_full_v2"] == {"Groq": 2}
    assert ce.PROVIDER_TALLY["llm_code_only"] == {"Gemini": 2}


def test_the_rule_classifier_is_never_counted(monkeypatch, offline):
    """It never asks anyone, so counting it would be a lie."""
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch) == 0

    assert "rule" not in ce.PROVIDER_TALLY


def test_a_provider_name_we_do_not_know_is_not_counted(monkeypatch, offline):
    """Only the two providers we can actually use may go in the table."""
    monkeypatch.setattr(cl, "ask_llm", answer_from("SomeOtherServer"))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch) == 0

    assert ce.PROVIDER_TALLY == {}


def test_an_unreadable_answer_still_counts_where_it_can(monkeypatch, offline):
    """One bad reply must not stop the other classifiers being counted."""
    calls = {"n": 0}

    def flaky(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            llm_client.LAST_PROVIDER = "Groq"
            return "not json at all"
        llm_client.LAST_PROVIDER = "Groq"
        return reply("REAL_BUG")

    monkeypatch.setattr(cl, "ask_llm", flaky)
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch) == 0

    # Every AI classifier still has a count.
    assert set(ce.PROVIDER_TALLY) == set(ce.AI_CLASSIFIERS)


def test_the_tally_starts_over_on_every_run(monkeypatch, offline, capsys):
    """A second run in the same process must not add to the first one's numbers."""
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch) == 0
    assert run_main(monkeypatch) == 0

    assert ce.PROVIDER_TALLY["llm_full"] == {"Groq": 1}


# ---------------------------------------------------------------------------
# What gets printed
# ---------------------------------------------------------------------------

def test_the_table_shows_a_row_per_classifier_and_a_total(
        monkeypatch, offline, capsys):
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch) == 0
    printed = capsys.readouterr().out

    assert "=== Where the answers came from ===" in printed
    for name in ce.AI_CLASSIFIERS:
        assert name in printed
    for provider in ce.PROVIDERS:
        assert provider in printed
    assert "asks nobody" in printed
    assert "total" in printed


def test_the_table_prints_the_counts_it_recorded(monkeypatch, offline, capsys):
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch) == 0
    printed = capsys.readouterr().out

    table = printed.split("=== Where the answers came from ===")[1]
    row = [line for line in table.splitlines()
           if line.strip().startswith("llm_full")][0]
    # Two cases, so two answers from Groq for this classifier.
    assert "2" in row
    assert "Gemini" not in row


def test_gemini_being_used_is_announced_loudly_and_only_once(
        monkeypatch, offline, capsys):
    """A mixed score has to be impossible to scroll past without noticing."""
    monkeypatch.setattr(cl, "ask_llm", answer_from("Gemini"))
    use_cases(monkeypatch, count=3)

    assert run_main(monkeypatch) == 0
    printed = capsys.readouterr().out

    assert "SOME ANSWERS CAME FROM GEMINI" in printed
    assert "FALLBACK PROVIDER" in printed
    assert "two different models" in printed
    # Said once, not on every single answer.
    assert printed.count("SOME ANSWERS CAME FROM GEMINI") == 1


def test_a_groq_only_run_never_announces_anything(monkeypatch, offline, capsys):
    """The warning has to mean something, so it stays quiet when it is not true."""
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch) == 0
    printed = capsys.readouterr().out

    assert "SOME ANSWERS CAME FROM GEMINI" not in printed


def test_the_repeat_run_also_prints_the_counts(monkeypatch, offline, capsys):
    """This run is a repeat run, so the counts have to be in the report."""
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch, 2) == 0
    printed = capsys.readouterr().out

    assert "=== Where the answers came from ===" in printed


# ---------------------------------------------------------------------------
# Nothing sensitive can get in
# ---------------------------------------------------------------------------

def test_the_tally_can_only_hold_a_provider_name():
    """The only thing that ever goes in is a name from our own list.

    This is checked by reading the code rather than by running it, because the
    value cannot be anything else: the only writer is note_provider, and it
    ignores anything not in PROVIDERS.
    """
    source = open(ce.__file__, encoding="utf-8").read()

    assert "provider not in PROVIDERS" in source
    assert "return" in source.split("if provider not in PROVIDERS:")[1][:40]


def test_the_printed_table_never_prints_anything_but_names_and_counts(
        monkeypatch, offline, capsys):
    """Every row is read back and checked against the tally we recorded.

    Reading the numbers back out of the printed table is what makes this worth
    having. It cannot pass just because the table looks tidy: if a number were
    wrong, or a row were missing, or something extra had been printed, this
    would say so.
    """
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch) == 0
    printed = capsys.readouterr().out

    table = printed.split("=== Where the answers came from ===")[1]

    rows = {}
    for line in table.splitlines():
        stripped = line.strip()
        if not stripped or set(stripped) <= set("-| "):
            continue
        label = stripped.split()[0]
        rows[label] = stripped

    # One row per AI classifier, plus rule and the total. Nothing else at all.
    assert set(rows) == set(ce.AI_CLASSIFIERS) | {"classifier", "rule", "total"}

    for name in ce.AI_CLASSIFIERS:
        numbers = [word for word in rows[name].split()[1:] if word.isdigit()]
        counts = ce.PROVIDER_TALLY[name]
        assert numbers == [str(counts.get(provider, 0))
                           for provider in ce.PROVIDERS], \
            f"{name} printed the wrong counts: {numbers}"

    # The total row is the sum of the rows above it, so the two cannot drift.
    total = [int(word) for word in rows["total"].split()[1:] if word.isdigit()]
    expected_total = [
        sum(counts.get(provider, 0) for counts in ce.PROVIDER_TALLY.values())
        for provider in ce.PROVIDERS
    ]
    assert total == expected_total

    # The header names the two providers, so a reader can tell the columns apart.
    for provider in ce.PROVIDERS:
        assert provider in rows["classifier"]


def test_the_rule_row_says_it_asks_nobody(monkeypatch, offline, capsys):
    """A gap in the table would look like a missing count."""
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch) == 0
    printed = capsys.readouterr().out

    table = printed.split("=== Where the answers came from ===")[1]
    rule_row = [line for line in table.splitlines()
                if line.strip().startswith("rule")][0]
    assert "asks nobody" in rule_row
    assert not any(word.isdigit() for word in rule_row.split()[1:])


def test_no_key_ever_reaches_the_provider_table(monkeypatch, offline, capsys):
    """The two key names must not turn up in what we print."""
    monkeypatch.setattr(cl, "ask_llm", answer_from("Gemini"))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch) == 0
    printed = capsys.readouterr().out

    table = printed.split("=== Where the answers came from ===")[1]
    for secret_word in ("API_KEY", "gsk_", "AIza", "key"):
        assert secret_word not in table, f"{secret_word!r} leaked into the table"