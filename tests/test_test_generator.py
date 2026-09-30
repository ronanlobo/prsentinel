"""Tests for the test generator.

Everything here uses a fake ask_llm, so no test touches the internet.
"""

import pytest

from prsentinel import test_generator as tg

# One real change taken from the round 2 example, so the test data matches
# what the extractor really produces.
MUTABLE_DEFAULT_CHANGE = {
    "name": "add_item_to_cart",
    "change_type": "modified",
    "old_code": ("def add_item_to_cart(item, cart=None):\n"
                 "    if cart is None:\n"
                 "        cart = []\n"
                 "    cart.append(item)\n"
                 "    return cart"),
    "new_code": ("def add_item_to_cart(item, cart=[]):\n"
                 "    cart.append(item)\n"
                 "    return cart"),
    "old_start_line": 8,
    "old_end_line": 13,
    "new_start_line": 8,
    "new_end_line": 10,
}


# ---------------------------------------------------------------------------
# Building the prompt
# ---------------------------------------------------------------------------

def test_prompt_contains_old_code():
    """The AI must be shown the old code, that is the specification."""
    prompt = tg.build_prompt(MUTABLE_DEFAULT_CHANGE)
    assert "cart=None" in prompt
    assert "if cart is None:" in prompt


def test_prompt_contains_new_code():
    """The AI must be shown the new code too."""
    prompt = tg.build_prompt(MUTABLE_DEFAULT_CHANGE)
    assert "cart=[]" in prompt


def test_prompt_contains_the_line_numbers():
    """The AI needs to know roughly where the code sits in each file."""
    prompt = tg.build_prompt(MUTABLE_DEFAULT_CHANGE)
    assert "old file lines 8 to 13" in prompt
    assert "new file lines 8 to 10" in prompt


def test_prompt_contains_the_function_name():
    """The prompt must name the function being tested."""
    assert "add_item_to_cart" in tg.build_prompt(MUTABLE_DEFAULT_CHANGE)


def test_prompt_does_not_say_which_version_is_wrong():
    """We must not tell the AI which version is right. We do not know."""
    prompt = tg.build_prompt(MUTABLE_DEFAULT_CHANGE).lower()
    for word in ["bug", "buggy", "broken", "regression", "correct version",
                 "wrong version", "bad code"]:
        assert word not in prompt, f"the prompt must not contain '{word}'"


def test_prompt_copes_with_a_brand_new_function():
    """An added function has no old code, so we must not print None."""
    change = dict(MUTABLE_DEFAULT_CHANGE, name="brand_new", change_type="added",
                  old_code="", old_start_line=None, old_end_line=None)
    prompt = tg.build_prompt(change)
    assert "None" not in prompt
    assert "no old version" in prompt


def test_prompt_asks_for_the_target_module():
    """The tests have to import from a module called target."""
    assert "from target import" in tg.build_prompt(MUTABLE_DEFAULT_CHANGE)


# ---------------------------------------------------------------------------
# Taking the code out of the AI's reply
# ---------------------------------------------------------------------------

def test_extract_code_takes_the_python_block():
    """Only the Python from inside the block is kept."""
    reply = "Here you go:\n```python\ndef test_a():\n    assert True\n```\nHope that helps!"
    assert tg.extract_code(reply) == "def test_a():\n    assert True\n"


def test_extract_code_ignores_the_chatty_text():
    """Words like 'bug' in the explanation must never reach the file."""
    reply = ("This might be buggy.\n```python\ndef test_a():\n    pass\n```\n"
             "Let me know.")
    code = tg.extract_code(reply)
    assert code == "def test_a():\n    pass\n"
    assert "buggy" not in code
    assert "Let me know" not in code


def test_extract_code_accepts_a_block_with_no_language():
    """Sometimes the AI forgets to write 'python' after the backticks."""
    reply = "```\ndef test_a():\n    pass\n```"
    assert tg.extract_code(reply) == "def test_a():\n    pass\n"


def test_extract_code_raises_a_clear_error_without_a_block():
    """No code block must be an error, not a file full of prose."""
    with pytest.raises(ValueError, match="no code block"):
        tg.extract_code("I am afraid I cannot help with that.")


def test_extract_code_raises_on_an_empty_reply():
    """An empty reply is also an error."""
    with pytest.raises(ValueError):
        tg.extract_code("   ")


# ---------------------------------------------------------------------------
# generate_tests and the file naming helper
# ---------------------------------------------------------------------------

def test_generate_tests_uses_a_fake_ask_llm(monkeypatch):
    """A fake AI reply is turned into just the test code."""
    sent = {}

    def fake_ask(prompt):
        sent["prompt"] = prompt
        return "sure\n```python\ndef test_x():\n    assert True\n```"

    monkeypatch.setattr(tg, "ask_llm", fake_ask)
    code = tg.generate_tests(MUTABLE_DEFAULT_CHANGE)

    assert code == "def test_x():\n    assert True\n"
    assert "add_item_to_cart" in sent["prompt"]


def test_safe_file_name_replaces_dots():
    """A method name like Cart.add must become a tidy file name."""
    assert tg.safe_file_name("Cart.add_item_to_cart") == "Cart_add_item_to_cart"
    assert tg.safe_file_name("add_item_to_cart") == "add_item_to_cart"
