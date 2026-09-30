"""Tests for the failure classifier.

Nothing here calls a real AI or touches the internet. Where we need an answer
from a model we put a fake one in its place, so the tests always give the same
result and cost nothing.
"""

import ast
import inspect
import json
import textwrap
from pathlib import Path

import pytest

from prsentinel import classifier as cl
from prsentinel import test_runner as tr

# The file we are checking for answer-key reading.
CLASSIFIER_PATH = Path(cl.__file__)


def write(path, text):
    """Write dedented text to a file and give the path back."""
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return str(path)


def fake_evidence(**changes):
    """Build a small evidence dictionary, so tests need no real files."""
    evidence = {
        "test_name": "test_case::test_thing",
        "old_code": "def f(x):\n    return x\n",
        "new_code": "def f(x):\n    return x + 1\n",
        "diff": "--- before\n+++ after\n-x\n+x + 1",
        "test_code": "from target import f\n\ndef test_thing():\n    assert f(1) == 1\n",
        "failure_message": "assert 2 == 1",
        "before_result": tr.PASSED,
        "after_result": tr.FAILED,
        "rerun": {"passes": 0, "fails": 5, "verdict": tr.ALWAYS_FAILS},
    }
    evidence.update(changes)
    return evidence


@pytest.fixture
def answer_recorder(monkeypatch):
    """Replace ask_llm with a fake and collect the prompts it was given.

    We also collect the temperature, so a test can check the classifier never
    asks for one. The classifier must keep using whatever the provider picks,
    so the generation setting must not reach it.
    """
    prompts = []
    replies = []
    temperatures = []

    def install(*given_replies):
        """Make ask_llm reply with the given strings, one per call."""
        prompts.clear()
        replies.clear()
        temperatures.clear()
        replies.extend(given_replies)

        def fake_ask_llm(prompt, temperature=None):
            prompts.append(prompt)
            temperatures.append(temperature)
            if not replies:
                raise AssertionError("ask_llm was called more often than expected")
            return replies.pop(0)

        monkeypatch.setattr(cl, "ask_llm", fake_ask_llm)
        return prompts

    install.install = install
    install.temperatures = temperatures
    return install


# ---------------------------------------------------------------------------
# collect_evidence
# ---------------------------------------------------------------------------

def test_evidence_holds_what_it_should(tmp_path):
    """All the pieces we need are there, under the names we expect."""
    before = write(tmp_path / "before.py", """
        def add(a, b):
            return a + b
    """)
    after = write(tmp_path / "after.py", """
        def add(a, b):
            return a - b
    """)
    test = write(tmp_path / "test_case.py", """
        from target import add

        def test_add():
            assert add(2, 3) == 5
    """)

    evidence = cl.collect_evidence(before, after, test, rerun_times=2)

    assert set(evidence) == {
        "test_name", "old_code", "new_code", "diff", "test_code",
        "failure_message", "before_result", "after_result", "rerun",
        "description",
    }
    # This caller has no pull request text to give, so it gets an empty string.
    assert evidence["description"] == ""
    assert "return a + b" in evidence["old_code"]
    assert "return a - b" in evidence["new_code"]
    assert "return a + b" in evidence["diff"]
    assert "def test_add" in evidence["test_code"]
    assert evidence["failure_message"]
    assert evidence["before_result"] == tr.PASSED
    assert evidence["after_result"] == tr.FAILED
    assert evidence["rerun"]["passes"] == 0
    assert evidence["rerun"]["fails"] == 2


def test_evidence_holds_no_folder_name(tmp_path):
    """The folder name must not reach the model, or the name gives it away."""
    folder = tmp_path / "bad_test_invented_rule"
    folder.mkdir()
    before = write(folder / "before.py", "def add(a, b):\n    return a + b\n")
    after = write(folder / "after.py", "def add(a, b):\n    return a - b\n")
    test = write(folder / "test_case.py", """
        from target import add

        def test_add():
            assert add(2, 3) == 99
    """)

    evidence = cl.collect_evidence(before, after, test, rerun_times=2)

    for key, value in evidence.items():
        if isinstance(value, str):
            assert "bad_test_invented_rule" not in value, \
                f"the folder name leaked into {key}"
            assert "classifier_cases" not in value, \
                f"the parent folder name leaked into {key}"


def test_evidence_never_mentions_expected_json(tmp_path):
    """Nothing in the evidence may come from the answer key."""
    before = write(tmp_path / "before.py", "def add(a, b):\n    return a + b\n")
    after = write(tmp_path / "after.py", "def add(a, b):\n    return a - b\n")
    test = write(tmp_path / "test_case.py", """
        from target import add

        def test_add():
            assert add(2, 3) == 99
    """)

    evidence = cl.collect_evidence(before, after, test, rerun_times=2)

    for key, value in evidence.items():
        if isinstance(value, str):
            assert "expected" not in value.lower(), \
                f"the word 'expected' turned up in {key}"


def test_evidence_holds_no_file_paths(tmp_path):
    """A path can carry the folder name, so we scrub them out."""
    before = write(tmp_path / "before.py", "def add(a, b):\n    return a + b\n")
    after = write(tmp_path / "after.py", "def add(a, b):\n    return a - b\n")
    test = write(tmp_path / "test_case.py", """
        import nothing_at_all
    """)

    evidence = cl.collect_evidence(before, after, test, rerun_times=1)

    # This file cannot be imported, so the message is about the file itself and
    # pytest will have put its path in there.
    assert evidence["failure_message"]
    assert "prsentinel_run_" not in evidence["failure_message"]
    assert ".py" not in evidence["failure_message"]


def test_remove_paths_hides_a_windows_path():
    """A Windows path is swapped for a placeholder."""
    cleaned = cl.remove_paths(r"Error loading C:\Users\someone\stuff\test_x.py")
    assert "C:\\Users" not in cleaned
    assert cl.PATH_PLACEHOLDER in cleaned


def test_remove_paths_hides_a_posix_path():
    """A Linux path is swapped for a placeholder too."""
    cleaned = cl.remove_paths("Error loading /home/someone/stuff/test_x.py")
    assert "/home/someone" not in cleaned
    assert cl.PATH_PLACEHOLDER in cleaned


def test_remove_paths_leaves_ordinary_text_alone():
    """We only touch things that look like paths."""
    assert cl.remove_paths("assert [1, 2] == [2, 1]") == "assert [1, 2] == [2, 1]"


def test_the_test_name_can_be_chosen(tmp_path):
    """We can talk about one particular test when a file holds several."""
    before = write(tmp_path / "before.py", "def add(a, b):\n    return a + b\n")
    after = write(tmp_path / "after.py", "def add(a, b):\n    return a - b\n")
    test = write(tmp_path / "test_case.py", """
        from target import add

        def test_first():
            assert add(2, 3) == 99

        def test_second():
            assert add(4, 5) == 99
    """)

    chosen = "test_case::test_second"
    evidence = cl.collect_evidence(before, after, test,
                                   test_name=chosen, rerun_times=1)

    assert evidence["test_name"] == chosen


def test_the_failing_test_is_chosen_when_none_is_named(tmp_path):
    """With no name given we take the first test that failed."""
    before = write(tmp_path / "before.py", "def add(a, b):\n    return a + b\n")
    after = write(tmp_path / "after.py", "def add(a, b):\n    return a - b\n")
    test = write(tmp_path / "test_case.py", """
        from target import add

        def test_first():
            assert add(2, 3) == 99

        def test_second():
            assert add(4, 5) == 99
    """)

    evidence = cl.collect_evidence(before, after, test, rerun_times=1)

    # Both fail, so the first one in name order is the one we talk about.
    assert evidence["test_name"] == "test_case::test_first"


def test_the_diff_says_where_they_differ():
    """The diff is a normal one, with plain labels and no file names."""
    diff = cl.make_diff("a\nb\n", "a\nc\n")
    assert "--- before" in diff
    assert "+++ after" in diff
    assert "-b" in diff
    assert "+c" in diff


# ---------------------------------------------------------------------------
# rule_classify
# ---------------------------------------------------------------------------

def test_the_rule_calls_mixed_reruns_flaky():
    """A test that flips between passing and failing is flaky."""
    evidence = fake_evidence(
        before_result=tr.PASSED,
        after_result=tr.FAILED,
        rerun={"passes": 2, "fails": 3, "verdict": tr.FLAKY},
    )
    answer = cl.rule_classify(evidence)
    assert answer["label"] == cl.FLAKY
    assert answer["reason"]


def test_the_rule_calls_a_failure_on_before_a_bad_test():
    """Failing on code that already worked means the test is the problem."""
    evidence = fake_evidence(
        before_result=tr.FAILED,
        after_result=tr.FAILED,
        rerun={"passes": 0, "fails": 5, "verdict": tr.ALWAYS_FAILS},
    )
    answer = cl.rule_classify(evidence)
    assert answer["label"] == cl.BAD_TEST
    assert answer["reason"]


def test_the_rule_calls_a_new_failure_a_real_bug():
    """Passing before and failing after means the change did it."""
    evidence = fake_evidence(
        before_result=tr.PASSED,
        after_result=tr.FAILED,
        rerun={"passes": 0, "fails": 5, "verdict": tr.ALWAYS_FAILS},
    )
    answer = cl.rule_classify(evidence)
    assert answer["label"] == cl.REAL_BUG
    assert answer["reason"]


def test_flakiness_wins_over_a_failure_on_before():
    """A test that cannot be trusted is flaky, whatever else it does."""
    evidence = fake_evidence(
        before_result=tr.FAILED,
        after_result=tr.FAILED,
        rerun={"passes": 1, "fails": 4, "verdict": tr.FLAKY},
    )
    assert cl.rule_classify(evidence)["label"] == cl.FLAKY


def test_the_rule_says_something_in_every_case():
    """Whatever happens, we get a label and an explanation."""
    for before_result in (tr.PASSED, tr.FAILED, tr.TEST_ERROR):
        evidence = fake_evidence(before_result=before_result)
        answer = cl.rule_classify(evidence)
        assert answer["label"] in cl.ALL_LABELS
        assert answer["reason"].strip()


# ---------------------------------------------------------------------------
# llm_classify: reading the reply
# ---------------------------------------------------------------------------

def test_llm_reads_plain_json(answer_recorder):
    """A clean JSON answer is used as it is."""
    answer_recorder(json.dumps({
        "label": "REAL_BUG", "confidence": "high", "reason": "The slice is off."}))

    answer = cl.llm_classify(fake_evidence(), cl.MODE_FULL)

    assert answer["label"] == cl.REAL_BUG
    assert answer["confidence"] == "high"
    assert answer["reason"] == "The slice is off."


def test_llm_reads_json_inside_a_code_fence(answer_recorder):
    """A fenced answer is read from inside the fence."""
    answer_recorder(
        "Here you go:\n```json\n"
        '{"label": "BAD_TEST", "confidence": "medium", "reason": "Wrong rule."}\n'
        "```\nHope that helps!"
    )

    answer = cl.llm_classify(fake_evidence(), cl.MODE_FULL)

    assert answer["label"] == cl.BAD_TEST
    assert answer["confidence"] == "medium"


def test_llm_reads_a_fence_with_no_language_word(answer_recorder):
    """A plain triple backtick works too."""
    answer_recorder(
        '```\n{"label": "FLAKY", "confidence": "low", "reason": "Depends on the clock."}\n```'
    )

    assert cl.llm_classify(fake_evidence(), cl.MODE_FULL)["label"] == cl.FLAKY


def test_llm_retries_once_after_a_useless_reply(answer_recorder):
    """Garbage first, then a good answer, and we take the good one."""
    prompts = answer_recorder(
        "I am not sure what you mean.",
        json.dumps({"label": "REAL_BUG", "confidence": "high",
                    "reason": "Second try."}),
    )

    answer = cl.llm_classify(fake_evidence(), cl.MODE_FULL)

    assert answer["label"] == cl.REAL_BUG
    assert len(prompts) == 2, "we should have asked exactly twice"
    # The second ask says what was wrong with the first answer.
    assert cl.NUDGE.strip().splitlines()[0] in prompts[1]


def test_llm_gives_up_after_two_useless_replies(answer_recorder):
    """Two bad answers is enough, and we say so clearly."""
    answer_recorder("nope", "still nope")

    with pytest.raises(cl.ClassifierError) as problem:
        cl.llm_classify(fake_evidence(), cl.MODE_FULL)

    assert "two tries" in str(problem.value)


def test_llm_rejects_an_unknown_label(answer_recorder):
    """A label we do not know is no better than a broken reply."""
    prompts = answer_recorder(
        json.dumps({"label": "MAYBE", "confidence": "high", "reason": "?"}),
        json.dumps({"label": "MAYBE", "confidence": "high", "reason": "?"}),
    )

    with pytest.raises(cl.ClassifierError):
        cl.llm_classify(fake_evidence(), cl.MODE_FULL)

    assert len(prompts) == 2, "an unknown label should still get one retry"


def test_llm_retries_once_for_an_unknown_label_then_works(answer_recorder):
    """An unknown label gets the same single retry as broken JSON."""
    answer_recorder(
        json.dumps({"label": "PROBABLY_FINE", "confidence": "high", "reason": "?"}),
        json.dumps({"label": "BAD_TEST", "confidence": "low", "reason": "Nope."}),
    )

    assert cl.llm_classify(fake_evidence(), cl.MODE_FULL)["label"] == cl.BAD_TEST


def test_llm_rejects_an_empty_reply(answer_recorder):
    """Nothing back at all is not an answer."""
    answer_recorder("", "")

    with pytest.raises(cl.ClassifierError):
        cl.llm_classify(fake_evidence(), cl.MODE_FULL)


def test_llm_fills_in_a_missing_confidence(answer_recorder):
    """Confidence is not worth throwing an answer away for."""
    answer_recorder(json.dumps({"label": "REAL_BUG", "reason": "Broke it."}))

    answer = cl.llm_classify(fake_evidence(), cl.MODE_FULL)

    assert answer["label"] == cl.REAL_BUG
    assert answer["confidence"] == "medium"


def test_llm_rejects_a_json_list(answer_recorder):
    """Valid JSON that is not an object is not an answer."""
    answer_recorder('["REAL_BUG", "high"]', '["REAL_BUG", "high"]')

    with pytest.raises(cl.ClassifierError):
        cl.llm_classify(fake_evidence(), cl.MODE_FULL)


def test_llm_refuses_an_unknown_mode(answer_recorder):
    """Only the two modes we wrote exist."""
    answer_recorder()

    with pytest.raises(ValueError):
        cl.llm_classify(fake_evidence(), "psychic")


# ---------------------------------------------------------------------------
# What each mode is allowed to show
# ---------------------------------------------------------------------------

def test_the_full_prompt_shows_the_results():
    """In full mode the AI is told how the test behaved."""
    prompt = cl.build_prompt(fake_evidence(), cl.MODE_FULL)

    assert "Result on the code before the change: passed" in prompt
    assert "Result on the code after the change: failed" in prompt
    assert "0 pass and 5 fail" in prompt


def test_the_code_only_prompt_hides_the_results():
    """In code_only mode the AI sees no results at all."""
    prompt = cl.build_prompt(fake_evidence(), cl.MODE_CODE_ONLY)

    assert "Result on the code before the change" not in prompt
    assert "Result on the code after the change" not in prompt
    assert "pass and" not in prompt


def test_the_code_only_prompt_is_the_full_one_minus_the_results():
    """The two modes must be identical apart from the results block."""
    evidence = fake_evidence()
    full = cl.build_prompt(evidence, cl.MODE_FULL)
    code_only = cl.build_prompt(evidence, cl.MODE_CODE_ONLY)
    results_block = cl._results_text(evidence)

    def real_lines(text):
        """Every line with something on it, so blank lines do not matter."""
        return [line for line in text.splitlines() if line.strip()]

    code_only_lines = set(real_lines(code_only))
    results_lines = set(real_lines(results_block))

    assert results_block in full, "the full prompt must show the results"

    # Every results line is hidden from the code_only prompt.
    for line in results_lines:
        assert line not in code_only_lines, f"leaked into code_only: {line}"

    # And nothing else is different between the two prompts.
    for line in real_lines(full):
        assert line in code_only_lines or line in results_lines, \
            f"this line is in full mode only and is not a result: {line}"


def test_both_modes_show_the_code_the_diff_and_the_message():
    """The difference between the modes is only the results."""
    evidence = fake_evidence()
    full = cl.build_prompt(evidence, cl.MODE_FULL)
    code_only = cl.build_prompt(evidence, cl.MODE_CODE_ONLY)

    for prompt in (full, code_only):
        assert "return x + 1" in prompt        # the new code
        assert "--- before" in prompt          # the diff
        assert "def test_thing" in prompt      # the test
        assert "assert 2 == 1" in prompt       # the failure message


def test_the_prompt_explains_the_three_labels():
    """The AI has to be told what the words mean."""
    prompt = cl.build_prompt(fake_evidence(), cl.MODE_CODE_ONLY)

    for label in cl.ALL_LABELS:
        assert f"- {label}:" in prompt
    assert "never meant to do" in prompt
    assert "depends on chance" in prompt


def test_the_prompt_asks_for_json_only():
    """We say what shape we want back."""
    prompt = cl.build_prompt(fake_evidence(), cl.MODE_CODE_ONLY)
    assert "Reply with JSON only" in prompt
    assert '"confidence"' in prompt


def test_the_prompt_names_no_case_and_no_folder():
    """The prompt must not point at any one case or its answer."""
    prompt = cl.build_prompt(fake_evidence(), cl.MODE_FULL)

    for word in ("classifier_cases", "expected.json", "REAL_BUG case",
                 "answer key", "this test is meant to be"):
        assert word not in prompt


def test_the_prompt_does_not_hand_over_the_verdict():
    """We must not simply tell the AI what the reruns concluded.

    The word FLAKY is allowed to appear twice: once in the list of labels the
    AI may choose from, and once in the JSON shape we ask for. The verdict
    words the runner produces must never appear.
    """
    prompt = cl.build_prompt(fake_evidence(), cl.MODE_FULL)

    assert prompt.count("FLAKY") == 2, \
        "the label should only appear in the list of choices and the JSON shape"
    assert tr.ALWAYS_FAILS not in prompt
    assert tr.ALWAYS_PASSES not in prompt
    assert "verdict" not in prompt


def test_classifying_never_asks_for_a_temperature(answer_recorder):
    """The generation setting must not reach the classifier.

    Writing tests may use a set temperature, so the answers come out
    predictably. Classifying must keep whatever the provider normally chooses,
    so it must never ask for one.
    """
    answer_recorder.install('{"label": "REAL_BUG", "confidence": "high", '
                            '"reason": "because"}')
    cl.llm_classify(fake_evidence(), cl.MODE_FULL)

    assert answer_recorder.temperatures == [None], \
        "the classifier must not send a temperature"


def test_the_prompt_refuses_an_unknown_mode():
    """Only the two modes we wrote exist."""
    with pytest.raises(ValueError):
        cl.build_prompt(fake_evidence(), "psychic")

# ---------------------------------------------------------------------------
# The classifier must never read the answer key
# ---------------------------------------------------------------------------

def without_module_docstring(path):
    """Read a source file with its module docstring taken out.

    A file is allowed to warn about the answer key in its opening comment.
    What matters is that the code itself never reaches for it.
    """
    source = Path(path).read_text(encoding="utf-8")
    docstring = ast.get_docstring(ast.parse(source), clean=False)
    if not docstring:
        return source
    return source.replace(docstring, "", 1)


def test_the_classifier_never_names_expected_json():
    """classifier.py may not even mention the answer key file."""
    body = without_module_docstring(CLASSIFIER_PATH)
    assert "expected.json" not in body


def test_the_classifier_never_names_the_cases_folder():
    """It must not know where the answer key lives."""
    body = without_module_docstring(CLASSIFIER_PATH)
    assert "classifier_cases" not in body
    assert "CASES_FOLDER" not in body


def test_the_classifier_opens_no_files_besides_the_three_we_pass_in(tmp_path,
                                                                  monkeypatch):
    """Watching every file read: only the three we gave may be opened."""
    before = write(tmp_path / "before.py", "def add(a, b):\n    return a + b\n")
    after = write(tmp_path / "after.py", "def add(a, b):\n    return a - b\n")
    test = write(tmp_path / "test_case.py", """
        from target import add

        def test_add():
            assert add(2, 3) == 99
    """)
    allowed = {Path(before).resolve(), Path(after).resolve(),
               Path(test).resolve()}

    real_read_text = Path.read_text
    opened = []

    def watched_read_text(self, *args, **kwargs):
        opened.append(Path(self).resolve())
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", watched_read_text)

    cl.collect_evidence(before, after, test, rerun_times=1)

    assert opened, "the test did not watch anything, so it proves nothing"
    for path in opened:
        assert path in allowed, f"classifier.py opened an unexpected file: {path}"


def test_only_the_eval_file_knows_about_expected_json():
    """Only the two eval files may read an answer key.

    classifier_eval.py scores the tuning set. heldback_eval.py scores the cases
    we kept back, which have their own answer keys. Nothing else may look,
    because a classifier that can read the answer is not being measured.
    """
    src_folder = Path(__file__).resolve().parent.parent / "src" / "prsentinel"
    offenders = []

    for path in sorted(src_folder.glob("*.py")):
        # classifier.py only warns about the file in its opening comment, so we
        # look at the rest of the source for it.
        source = (without_module_docstring(path) if path.name == "classifier.py"
                  else path.read_text(encoding="utf-8"))
        if "expected.json" in source:
            offenders.append(path.name)

    assert sorted(offenders) == ["classifier_eval.py", "heldback_eval.py"], \
        f"only the two eval files may read expected.json, but so do: {offenders}"


def test_the_eval_points_at_the_answer_key_correctly():
    """The eval must find the case folders, and all fourteen of them.

    The path is worked out from this file's own location, so it is easy to get
    wrong. This catches it without needing a model.
    """
    from prsentinel import classifier_eval as ce

    assert ce.CASES_FOLDER.is_dir(), \
        f"the eval is looking in the wrong place: {ce.CASES_FOLDER}"

    folders = ce.case_folders()
    assert len(folders) == 14
    assert all(folder.is_dir() for folder in folders)
    # Sorted, so the order never changes between runs.
    assert folders == sorted(folders)


def test_only_the_heldback_eval_names_the_heldback_folder():
    """One command may score the cases we kept back, and it is not this one."""
    src_folder = Path(__file__).resolve().parent.parent / "src" / "prsentinel"
    offenders = []

    for path in sorted(src_folder.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "classifier_cases_heldback" in source:
            offenders.append(path.name)

    assert offenders == ["heldback_eval.py"], \
        (f"only heldback_eval.py may know about the kept-back cases, "
         f"but so do: {offenders}")


def test_nothing_but_the_two_eval_files_can_reach_an_answer_key():
    """The classifier, the generator and the pipeline must not even name it."""
    src_folder = Path(__file__).resolve().parent.parent / "src" / "prsentinel"
    allowed = {"classifier.py", "classifier_eval.py", "heldback_eval.py",
               "pipeline.py", "test_generator.py"}

    for name in sorted(allowed):
        source = (src_folder / name).read_text(encoding="utf-8")
        if name in ("classifier.py", "classifier_eval.py", "heldback_eval.py"):
            continue
        assert "expected.json" not in source, \
            f"{name} must not know about the answer key"
        assert "classifier_cases" not in source, \
            f"{name} must not know about the answer key folders"


def test_the_heldback_eval_points_at_the_right_folder():
    """The kept-back command must find the four kept-back cases."""
    from prsentinel import heldback_eval as he

    assert he.HELDBACK_FOLDER.is_dir(), \
        f"the held-back eval is looking in the wrong place: {he.HELDBACK_FOLDER}"

    folders = he.case_folders()
    assert len(folders) == 4
    assert folders == sorted(folders)
    # It must never point at the tuning folder by accident.
    assert he.HELDBACK_FOLDER != ce_caseless_folder()


def ce_caseless_folder():
    """Return the tuning folder, so the held-back one can be compared to it."""
    from prsentinel import classifier_eval as ce
    return ce.CASES_FOLDER


def test_the_heldback_eval_prints_nothing_per_case(capsys, monkeypatch):
    """Only totals, so a held-back run cannot be used to pick answers."""
    from prsentinel import classifier as cl
    from prsentinel import heldback_eval as he

    def fake_run_case(folder):
        # Deliberately wrong, so a per-case print would show up in the output.
        return {name: {"label": "WRONG_ANSWER", "confidence": "",
                       "reason": "this reason must never be printed"}
                for name in he.CLASSIFIERS}

    monkeypatch.setattr(he, "run_case", fake_run_case)
    monkeypatch.setattr(he, "add_to_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(cl, "classify", lambda *a, **k: {})

    assert he.main() == 0
    printed = capsys.readouterr().out

    assert "WRONG_ANSWER" not in printed
    assert "this reason must never be printed" not in printed
    assert "cases: 4" in printed
    assert f"reruns per case: {he.RERUN_TIMES}" in printed
    for name in he.CLASSIFIERS:
        assert name in printed


# ---------------------------------------------------------------------------
# The old prompts must not change
# ---------------------------------------------------------------------------

# The exact wording of the "full" prompt, captured from classifier.py as it stood
# at commit c5acfee, before the description section was added. It was produced by
# calling build_prompt with the same evidence frozen_evidence() gives below, so
# every field is filled in and the results section is present.
#
# If somebody edits a single character of the prompt, changes which sections are
# included, or adds a section to this mode, this no longer matches and the test
# below fails. The two already-measured scores depend on these staying unchanged.
EXPECTED_FULL_PROMPT = """You are looking at one failing test and trying to work out what is going on.

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


Choose exactly one label:
- REAL_BUG: the test is reasonable and the new code broke intended behavior
- BAD_TEST: the test expects something the code was never meant to do, or the change was intentional and the test is now outdated
- FLAKY: the test result depends on chance (randomness, time, ordering) rather than on the code

Base your answer on what the code is trying to do and what the test is checking. You cannot see any folder names or file paths, so do not try to guess from them.

Reply with JSON only, using exactly this shape:
{"label": "REAL_BUG" | "BAD_TEST" | "FLAKY", "confidence": "low" | "medium" | "high", "reason": "one or two plain sentences"}
No other text."""

# The exact wording of the "code_only" prompt, captured from classifier.py as it stood
# at commit c5acfee, before the description section was added. It was produced by
# calling build_prompt with the same evidence frozen_evidence() gives below, so
# every field is filled in and the results section is present.
#
# If somebody edits a single character of the prompt, changes which sections are
# included, or adds a section to this mode, this no longer matches and the test
# below fails. The two already-measured scores depend on these staying unchanged.
EXPECTED_CODE_ONLY_PROMPT = """You are looking at one failing test and trying to work out what is going on.

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

Choose exactly one label:
- REAL_BUG: the test is reasonable and the new code broke intended behavior
- BAD_TEST: the test expects something the code was never meant to do, or the change was intentional and the test is now outdated
- FLAKY: the test result depends on chance (randomness, time, ordering) rather than on the code

Base your answer on what the code is trying to do and what the test is checking. You cannot see any folder names or file paths, so do not try to guess from them.

Reply with JSON only, using exactly this shape:
{"label": "REAL_BUG" | "BAD_TEST" | "FLAKY", "confidence": "low" | "medium" | "high", "reason": "one or two plain sentences"}
No other text."""

def frozen_evidence():
    """Return evidence with every field filled in, so the prompt is complete."""
    return {
        "old_code": "def add(a, b):\n    return a + b\n",
        "new_code": "def add(a, b, c):\n    return a + b + c\n",
        "diff": ("--- before\n+++ after\n@@ -1,2 +1,2 @@\n def add(a, b):\n"
                 "-    return a + b\n+    return a + b + c\n"),
        "test_code": "def test_add():\n    assert add(2, 3) == 5\n",
        "failure_message": "assert 8 == 5\n",
        "before_result": tr.PASSED,
        "after_result": tr.FAILED,
        "rerun": {"passes": 1, "fails": 4, "verdict": "FLAKY"},
        "test_name": "test_case.py::test_add",
        "description": "This change was made on purpose.",
    }


def test_the_full_prompt_is_byte_identical_to_before():
    """The full prompt must not change by a single character.

    Its score has already been measured, and the description has to be measured
    against it. If this prompt moved, the two numbers would not be comparable.
    """
    prompt = cl.build_prompt(frozen_evidence(), cl.MODE_FULL)
    assert prompt == EXPECTED_FULL_PROMPT


def test_the_code_only_prompt_is_byte_identical_to_before():
    """Same again for code_only, which is the other already-measured prompt."""
    prompt = cl.build_prompt(frozen_evidence(), cl.MODE_CODE_ONLY)
    assert prompt == EXPECTED_CODE_ONLY_PROMPT


def test_the_old_prompts_ignore_a_description_entirely():
    """A description in the evidence must not reach the two old prompts."""
    with_text = frozen_evidence()
    without_text = frozen_evidence()
    without_text["description"] = ""

    for mode in (cl.MODE_FULL, cl.MODE_CODE_ONLY):
        assert (cl.build_prompt(with_text, mode)
                == cl.build_prompt(without_text, mode)), \
            f"{mode} must not show the description"


def test_the_intent_mode_shows_the_description():
    """The new mode is the only one that shows it."""
    evidence = frozen_evidence()

    prompt = cl.build_prompt(evidence, cl.MODE_FULL_WITH_INTENT)

    assert "This change was made on purpose." in prompt
    assert cl.DESCRIPTION_HEADING in prompt


def test_the_intent_mode_says_so_when_there_is_no_description():
    """An empty description is stated, not left out."""
    evidence = frozen_evidence()
    evidence["description"] = ""

    prompt = cl.build_prompt(evidence, cl.MODE_FULL_WITH_INTENT)

    assert cl.NO_DESCRIPTION in prompt
    assert cl.NO_DESCRIPTION == "No description was provided."


def test_the_intent_mode_is_the_full_prompt_plus_the_description():
    """It must be full, unchanged, with the description block slotted in.

    The block goes in after the results section and before the instructions, so
    the two halves of the prompt have to match exactly and only the middle is
    allowed to grow.
    """
    evidence = frozen_evidence()

    full = cl.build_prompt(evidence, cl.MODE_FULL)
    intent = cl.build_prompt(evidence, cl.MODE_FULL_WITH_INTENT)

    instructions = "Choose exactly one label:"
    full_head, full_tail = full.split(instructions, 1)
    intent_head, intent_tail = intent.split(instructions, 1)

    # Everything from the instructions onwards is word for word the same.
    assert intent_tail == full_tail, \
        "the instructions and the reply shape must not move"

    # Everything up to the description block is word for word the same.
    assert intent_head.startswith(full_head), \
        "the code, the test, the message and the results must not move"

    extra = intent_head[len(full_head):]
    assert cl.DESCRIPTION_HEADING in extra
    assert "This change was made on purpose." in extra


def test_the_three_modes_are_all_accepted():
    """The new mode is a real mode, not a special case that slips through."""
    assert cl.MODE_FULL_WITH_INTENT in cl.ALL_MODES
    for mode in ("full", "code_only", "full_with_intent"):
        assert mode in cl.ALL_MODES


def test_an_unknown_mode_is_still_refused():
    """Adding a mode must not open the door to anything else."""
    for mode in ("nonsense", "", "FULL", "intent"):
        try:
            cl.build_prompt(frozen_evidence(), mode)
        except ValueError:
            continue
        raise AssertionError(f"{mode!r} should not be a mode")


def test_classify_can_run_the_intent_mode(monkeypatch):
    """The new classifier name reaches the new mode."""
    asked = []

    def fake_ask(prompt):
        asked.append(prompt)
        return '{"label": "BAD_TEST", "confidence": "low", "reason": "x"}'

    monkeypatch.setattr(cl, "ask_llm", fake_ask)

    answer = cl.classify(frozen_evidence(), classifier="llm_full_with_intent")
    assert answer["label"] == "BAD_TEST"
    assert cl.DESCRIPTION_HEADING in asked[0]

    with pytest.raises(ValueError):
        cl.classify(frozen_evidence(), classifier="llm_intent")


def test_build_evidence_carries_a_description(tmp_path):
    """The description has to survive from the caller into the evidence."""
    before = write(tmp_path / "before.py", "def add(a, b):\n    return a + b\n")
    after = write(tmp_path / "after.py", "def add(a, b):\n    return a - b\n")
    test = write(tmp_path / "test_case.py",
                 "from target import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")

    evidence = cl.build_evidence(
        before_run={"tests": {"t": tr.PASSED}},
        after_run={"tests": {"t": tr.FAILED}, "failures_full": {"t": "boom"}},
        rerun_run={"tests": {"t": {"passes": 0, "fails": 1,
                                   "verdict": "ALWAYS_FAILS"}}},
        before_file=before, after_file=after, test_file=test,
        test_name="t",
        description="A short note about why.",
    )

    assert evidence["description"] == "A short note about why."


def test_build_evidence_defaults_to_no_description(tmp_path):
    """Callers that do not have one still work, and get an empty string."""
    before = write(tmp_path / "before.py", "def add(a, b):\n    return a + b\n")
    after = write(tmp_path / "after.py", "def add(a, b):\n    return a - b\n")
    test = write(tmp_path / "test_case.py",
                 "from target import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")

    evidence = cl.build_evidence(
        before_run={"tests": {"t": tr.PASSED}},
        after_run={"tests": {"t": tr.FAILED}, "failures_full": {"t": "boom"}},
        rerun_run={"tests": {"t": {"passes": 0, "fails": 1,
                                   "verdict": "ALWAYS_FAILS"}}},
        before_file=before, after_file=after, test_file=test,
        test_name="t",
    )

    assert evidence["description"] == ""


# ---------------------------------------------------------------------------
# The classify shortcut
# ---------------------------------------------------------------------------

def test_classify_runs_the_rule_by_default():
    """Without being told, classify uses the plain rule."""
    answer = cl.classify(fake_evidence())
    assert answer["label"] == cl.REAL_BUG


def test_classify_runs_either_ai_mode(answer_recorder, monkeypatch):
    """The two AI modes both come through the same shortcut."""
    evidence = fake_evidence()
    prompts = answer_recorder(
        json.dumps({"label": "BAD_TEST", "confidence": "low", "reason": "Nope."}),
        json.dumps({"label": "FLAKY", "confidence": "low", "reason": "Clock."}),
    )

    assert cl.classify(evidence, "llm_full")["label"] == cl.BAD_TEST
    assert cl.classify(evidence, "llm_code_only")["label"] == cl.FLAKY
    assert "Result on the code before" in prompts[0]
    assert "Result on the code before" not in prompts[1]


def test_classify_refuses_an_unknown_classifier():
    """Only the three we compare exist."""
    with pytest.raises(ValueError):
        cl.classify(fake_evidence(), "magic")


def test_classify_has_no_hidden_extra_arguments():
    """The shortcut must not have grown a way to reach the answer key."""
    parameters = list(inspect.signature(cl.classify).parameters)
    assert parameters == ["evidence", "classifier", "mode"]
