import pytest
from target import unescapeHTML

# Helper to compare old and new behavior indirectly via expected results
@pytest.mark.parametrize(
    "input_str, expected",
    [
        # Basic known entities
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&quot;", '"'),
        ("&apos;", "'"),
        # Mixed text with entities
        ("Hello &amp; World", "Hello & World"),
        ("5 &lt; 10 &amp;&amp; 10 &gt; 5", "5 < 10 && 10 > 5"),
        # Entity followed by text that looks like an entity but contains an extra '&'
        ("&amp;foo;", "&foo;"),
        ("&foo&bar;", "&foo&bar;"),
        # Entity with a semicolon inside the name (should not happen, but test robustness)
        ("&amp;foo;bar;", "&foo;bar;"),
        # String without any entities
        ("plain text", "plain text"),
    ],
)
def test_unescapeHTML_expected_output(input_str, expected):
    assert unescapeHTML(input_str) == expected


def test_unescapeHTML_none_input():
    assert unescapeHTML(None) is None


def test_unescapeHTML_invalid_type():
    with pytest.raises(AssertionError):
        unescapeHTML(123)  # not a compat_str


def test_unescapeHTML_does_not_match_entity_with_internal_amp():
    # Old implementation would NOT treat this as a single entity
    # New implementation would incorrectly treat it as one entity
    input_str = "&foo&bar;"
    # Expected: unchanged because the pattern should reject internal '&'
    assert unescapeHTML(input_str) == input_str


def test_unescapeHTML_partial_entity_before_extra_amp():
    # Only the first valid entity should be transformed; the rest stays unchanged
    input_str = "&amp;foo&bar;"
    # Old behavior: &amp; -> &, leaving "foo&bar;"
    expected = "&foo&bar;"
    assert unescapeHTML(input_str) == expected
