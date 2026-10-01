"""The freeze: the prompts must not move again after the kept-back run.

This file exists for one moment in the project's life. The prompts have been
measured on the tuning set and recorded in PROMPT_LOG.md, and the kept-back
cases have never been looked at. From here on, the only thing worth knowing is
whether the frozen prompt does better on the kept-back cases than the prompt it
replaced. That question can only be answered if the prompt stays exactly as it
was when it was measured.

So the four things below are frozen. If any of them changes by a single
character, this test fails and the kept-back score stops meaning what it is
supposed to mean. That is deliberate. Changing a prompt after the kept-back run
has scored it turns an honest measurement into a second tuning pass over the
one set we promised not to tune against.

Nothing here calls an AI or runs a test. The prompts are built from
`frozen_evidence()`, the same fixed evidence used everywhere else, so these
tests are fast and offline.

The two older prompts are not copied into this file. Their expected text lives
next to the tests that introduced it, in test_classifier.py, and is imported
here rather than duplicated. Two copies of one prompt can drift apart, and a
frozen constant that nobody updates is worse than no constant at all.
"""

import re
from pathlib import Path

import pytest

from prsentinel import classifier as cl

from test_classifier import (EXPECTED_CODE_ONLY_PROMPT, EXPECTED_FULL_PROMPT,
                             frozen_evidence)

# ---------------------------------------------------------------------------
# Everything frozen, with the size it was frozen at
# ---------------------------------------------------------------------------

# Frozen before the held-back run. Do not edit.
EXPECTED_FULL_PROMPT_SIZE = 1451

# Frozen before the held-back run. Do not edit.
EXPECTED_CODE_ONLY_PROMPT_SIZE = 1226

# Frozen before the held-back run. Do not edit.
EXPECTED_FULL_V2_PROMPT_SIZE = 2145

# Frozen before the held-back run. Do not edit.
EXPECTED_RERUN_SECTION_SIZE = 692

# Frozen before the held-back run. Do not edit.
EXPECTED_RERUN_SECTION = """How to read the results above.

The last line above says how the same code and the same test behaved when the
test was run again. If that line reports both passes and fails, then the test
did not settle on one answer. The code was identical between those runs, and
what the test is asking for did not change either, so the only thing left that
could move the outcome is chance: something outside the code and outside what
the test is asking for is deciding the result from one run to the next.

When that happens the result cannot be trusted as evidence about the code or
about the test. An outcome that changes by chance is not showing a fault in
either one, so it should not be read as one."""

# The v2 prompt. Produced by calling build_prompt on frozen_evidence() at the
# commit recorded in PROMPT_LOG.md, not written out by hand, so it cannot have
# been typed wrong.
#
# Frozen before the held-back run. Do not edit.
EXPECTED_FULL_V2_PROMPT = """You are looking at one failing test and trying to work out what is going on.

Here is the code before the change.
```python
def add(a, b):
    return a + b

```

Here is the code after the change.
```python
def add(a, b, c):
    return a + b + c

```

Here is the difference between them.
```diff
--- before
+++ after
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a + b
+    return a + b + c

```

Here is the test.
```python
def test_add():
    assert add(2, 3) == 5

```

Here is what the test printed when it failed.
```text
assert 8 == 5

```

Here is how this test behaved when it was run.

Result on the code before the change: passed
Result on the code after the change: failed
When the test was run again several times on the new code, it gave 1 pass and 4 fail.


How to read the results above.

The last line above says how the same code and the same test behaved when the
test was run again. If that line reports both passes and fails, then the test
did not settle on one answer. The code was identical between those runs, and
what the test is asking for did not change either, so the only thing left that
could move the outcome is chance: something outside the code and outside what
the test is asking for is deciding the result from one run to the next.

When that happens the result cannot be trusted as evidence about the code or
about the test. An outcome that changes by chance is not showing a fault in
either one, so it should not be read as one.

Choose exactly one label:
- REAL_BUG: the test is reasonable and the new code broke intended behavior
- BAD_TEST: the test expects something the code was never meant to do, or the change was intentional and the test is now outdated
- FLAKY: the test result depends on chance (randomness, time, ordering) rather than on the code

Base your answer on what the code is trying to do and what the test is checking. You cannot see any folder names or file paths, so do not try to guess from them.

Reply with JSON only, using exactly this shape:
{"label": "REAL_BUG" | "BAD_TEST" | "FLAKY", "confidence": "low" | "medium" | "high", "reason": "one or two plain sentences"}
No other text."""


# Each frozen thing, as (what it is called, the value, the mode it is built for
# or None for something that is not a whole prompt).
FROZEN = (
    ("full", cl.MODE_FULL, EXPECTED_FULL_PROMPT, EXPECTED_FULL_PROMPT_SIZE),
    ("code_only", cl.MODE_CODE_ONLY, EXPECTED_CODE_ONLY_PROMPT,
     EXPECTED_CODE_ONLY_PROMPT_SIZE),
    ("full_v2", cl.MODE_FULL_V2, EXPECTED_FULL_V2_PROMPT,
     EXPECTED_FULL_V2_PROMPT_SIZE),
)


# ---------------------------------------------------------------------------
# The three prompts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,mode,expected,size", FROZEN)
def test_the_prompt_has_not_changed(name, mode, expected, size):
    """The prompt is frozen, character for character.

    A reworded instruction, a moved paragraph or one extra space all fail here,
    because that is the point: a kept-back score only means something against the
    exact prompt that was measured.
    """
    assert cl.build_prompt(frozen_evidence(), mode) == expected, (
        f"the {name} prompt changed. It is frozen until after the kept-back "
        f"run. If this change is meant, the kept-back score has to be thrown "
        f"away and the prompt measured again on the tuning set."
    )


@pytest.mark.parametrize("name,mode,expected,size", FROZEN)
def test_the_prompt_is_the_size_it_was_frozen_at(name, mode, expected, size):
    """The length is checked on its own, so a broken build says which one.

    Without this, a prompt that lost a section and one that gained a character
    would both fail the test above with the same message, and neither would say
    anything useful about what happened.
    """
    built = cl.build_prompt(frozen_evidence(), mode)

    assert len(built) == size, (
        f"the {name} prompt is {len(built)} characters. It was frozen at {size}."
    )
    assert len(expected) == size, (
        f"the frozen {name} constant in this file is {len(expected)} characters, "
        f"but it is supposed to be {size}. The constant was edited, not the "
        f"prompt."
    )


def test_the_full_prompt_is_still_1451_characters():
    """Written out on its own, because this is the number in PROMPT_LOG.md."""
    assert len(cl.build_prompt(frozen_evidence(), cl.MODE_FULL)) == 1451


def test_the_code_only_prompt_is_still_1226_characters():
    assert len(cl.build_prompt(frozen_evidence(), cl.MODE_CODE_ONLY)) == 1226


def test_the_full_v2_prompt_is_still_2145_characters():
    """The prompt behind the score recorded for v2 on 2026-10-01."""
    assert len(cl.build_prompt(frozen_evidence(), cl.MODE_FULL_V2)) == 2145


# ---------------------------------------------------------------------------
# The added section on its own
# ---------------------------------------------------------------------------

def test_the_added_section_has_not_changed():
    """RERUN_SECTION is frozen in its own right, not only as part of v2.

    Frozen before the held-back run. Do not edit.

    Testing it alone matters because it is also used by the code_only mode's
    sibling reasoning and it is the only part of v2 that is new. If somebody
    changed it and the v2 prompt test somehow still passed, this would catch it.
    """
    assert cl.RERUN_SECTION == EXPECTED_RERUN_SECTION


def test_the_added_section_is_still_692_characters():
    assert len(cl.RERUN_SECTION) == 692


def test_the_section_goes_into_v2_exactly_once():
    """The whole of v2's difference from v1 is one copy of this section.

    If it appeared twice, or not at all, v2 would not be the prompt that was
    measured even though the character count could still match by accident.
    """
    built = cl.build_prompt(frozen_evidence(), cl.MODE_FULL_V2)
    assert built.count(EXPECTED_RERUN_SECTION) == 1


def test_v2_is_v1_plus_that_one_section():
    """Taking the section out of v2 leaves v1 exactly.

    This is the claim PROMPT_LOG.md makes about v2, so it is checked rather than
    trusted.
    """
    built_v2 = cl.build_prompt(frozen_evidence(), cl.MODE_FULL_V2)
    stripped = built_v2.replace(cl.RERUN_SECTION + "\n\n", "", 1)

    assert stripped == EXPECTED_FULL_PROMPT
    assert stripped != built_v2, "nothing was removed, so the replace did nothing"


# ---------------------------------------------------------------------------
# The freeze has to be a real one
# ---------------------------------------------------------------------------

def test_the_frozen_constants_all_agree_with_each_other():
    """If a constant and a size disagree, one of them was edited."""
    assert len(EXPECTED_FULL_PROMPT) == EXPECTED_FULL_PROMPT_SIZE
    assert len(EXPECTED_CODE_ONLY_PROMPT) == EXPECTED_CODE_ONLY_PROMPT_SIZE
    assert len(EXPECTED_FULL_V2_PROMPT) == EXPECTED_FULL_V2_PROMPT_SIZE
    assert len(EXPECTED_RERUN_SECTION) == EXPECTED_RERUN_SECTION_SIZE


def test_the_freeze_would_notice_a_changed_character(monkeypatch):
    """Proof the tests can actually fail.

    A guard that cannot fail is not a guard. One character is swapped in a copy
    of the section, the build is pointed at it, and the tests are asked again.
    """
    changed = EXPECTED_RERUN_SECTION.replace("only thing left", "only thing")
    monkeypatch.setattr(cl, "RERUN_SECTION", changed)

    with pytest.raises(AssertionError):
        assert cl.RERUN_SECTION == EXPECTED_RERUN_SECTION

    with pytest.raises(AssertionError):
        assert len(cl.RERUN_SECTION) == EXPECTED_RERUN_SECTION_SIZE


def test_the_freeze_would_notice_a_reordered_prompt(monkeypatch):
    """Swapping two sentences is a prompt change, and has to be caught."""
    built = cl.build_prompt(frozen_evidence(), cl.MODE_FULL_V2)
    head, _, tail = built.partition(EXPECTED_RERUN_SECTION)
    monkeypatch.setattr(cl, "build_prompt",
                        lambda evidence, mode: tail + head)

    with pytest.raises(AssertionError):
        assert cl.build_prompt(frozen_evidence(), cl.MODE_FULL_V2) == \
            EXPECTED_FULL_V2_PROMPT


def test_the_freeze_covers_the_three_modes_that_were_measured():
    """Written out, so a new mode has to be a decision and not an oversight.

    full_with_intent is deliberately not frozen. It is not one of the three
    prompts scored on 2026-10-01, and it is not scored on the kept-back run
    either, so there is no measurement of it that a change could invalidate.
    The list is spelled out rather than taken from ALL_MODES so that adding a
    fourth mode to the project breaks this test and forces somebody to decide
    whether it is frozen too.
    """
    frozen = {mode for _, mode, _, _ in FROZEN}

    assert frozen == {cl.MODE_FULL, cl.MODE_CODE_ONLY, cl.MODE_FULL_V2}

    # Every frozen mode has to be a real mode, or a typo would freeze nothing.
    assert frozen <= set(cl.ALL_MODES)

    # And the ones we left out are left out on purpose, not by accident.
    assert cl.MODE_FULL_WITH_INTENT not in frozen
    assert cl.MODE_FULL_WITH_INTENT in cl.ALL_MODES


# ---------------------------------------------------------------------------
# Nothing frozen may leak a giveaway or a verdict
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,mode,expected,size", FROZEN)
def test_no_frozen_prompt_contains_the_giveaway(name, mode, expected, size):
    """The tuning cases have a giveaway in them and the prompts must not.

    The three old flaky cases work by mentioning an index in the failure. If a
    prompt ever named it, the scores would partly be measuring the AI noticing
    a word rather than reading the evidence.
    """
    built = cl.build_prompt(frozen_evidence(), mode)

    assert "RUN_INDEX" not in built
    assert "run_index" not in built.lower()


@pytest.mark.parametrize("name,mode,expected,size", FROZEN)
def test_no_frozen_prompt_tells_the_ai_what_to_choose(name, mode, expected,
                                                       size):
    """The labels may be named as the choices, but never as the answer.

    A prompt that says "this looks flaky" would score well and prove nothing, so
    the words that would steer the answer are checked for directly.
    """
    built = cl.build_prompt(frozen_evidence(), mode).lower()

    for steer in ("the answer is", "you should answer", "choose flaky",
                  "choose real_bug", "choose bad_test", "this is flaky",
                  "this is a real bug", "this is a bad test"):
        assert steer not in built, f"the {name} prompt steers the answer: {steer!r}"


def test_the_section_names_no_label_at_all():
    """The added section must let the AI work the label out itself."""
    for label in ("REAL_BUG", "BAD_TEST", "FLAKY"):
        assert label not in EXPECTED_RERUN_SECTION


def test_flaky_appears_only_in_the_label_list_of_the_whole_prompt():
    """Checked so a future edit cannot quietly start hinting at the answer."""
    built = cl.build_prompt(frozen_evidence(), cl.MODE_FULL_V2)

    # Once in the choices, and once in the JSON shape. Nowhere else.
    assert built.count("FLAKY") == 2


# ---------------------------------------------------------------------------
# The freeze is recorded, so it can be pointed at
# ---------------------------------------------------------------------------

def test_the_prompt_log_records_both_frozen_hashes():
    """The hashes are what make the freeze checkable after the fact."""
    import re
    from pathlib import Path

    log = Path(__file__).resolve().parents[1] / "PROMPT_LOG.md"
    text = log.read_text(encoding="utf-8")

    hashes = re.findall(r"\b[0-9a-f]{40}\b", text)
    assert len(hashes) >= 2, "PROMPT_LOG.md does not record two hashes"

    assert "HEAD" in text, "the HEAD hash is not labelled"
    assert "classifier.py" in text, "the classifier.py hash is not labelled"


def test_the_prompt_log_still_shows_v2_as_measured():
    """The refusal in heldback_eval keys off these two phrases.

    They have to be gone now that the tuning scores are in, or the kept-back
    run would refuse to start.
    """
    from pathlib import Path

    log = Path(__file__).resolve().parents[1] / "PROMPT_LOG.md"
    text = log.read_text(encoding="utf-8")

    assert "not measured yet" not in text
    assert "not yet run" not in text
    assert "13/14" in text, "v2's tuning score is not recorded"


def test_the_frozen_sizes_in_this_file_are_the_ones_named_in_the_step():
    """The four numbers were given as 1451, 1226, 2145 and the section.

    Read them from the file's own comments so an edit to a size has to be a
    deliberate change to a stated number rather than a quiet constant tweak.
    """
    source = Path(__file__).read_text(encoding="utf-8")

    for name, size in (("EXPECTED_FULL_PROMPT_SIZE", 1451),
                       ("EXPECTED_CODE_ONLY_PROMPT_SIZE", 1226),
                       ("EXPECTED_FULL_V2_PROMPT_SIZE", 2145),
                       ("EXPECTED_RERUN_SECTION_SIZE", 692)):
        pattern = rf"{name} = {size}\b"
        assert re.search(pattern, source), (
            f"{name} is not {size} in the source. The frozen size was changed."
        )


def test_no_key_can_be_written_into_this_file():
    """The frozen prompts are copied from the program, so guard them like the rest.

    Nothing here should ever print or hold a key, and this says so where a future
    editor would see it.
    """
    source = Path(__file__).read_text(encoding="utf-8")

    for secret_word in ("API_KEY", "gsk_", "AIza"):
        # The names may appear inside a guard that checks for them, and nowhere
        # else, so each one has to be inside an assertion about itself.
        for line in source.splitlines():
            if secret_word in line:
                assert "assert" in line or "for secret_word" in line, (
                    f"{secret_word!r} appears outside a guard: {line.strip()!r}"
                )
