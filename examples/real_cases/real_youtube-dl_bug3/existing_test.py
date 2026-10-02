"""youtube-dl's own test for bug 3, flattened so pytest can run it.

Source: test/test_utils.py, method TestUtil.test_unescape_html, lines 276-284.
The byte-for-byte original is in existing_test_original.py and is never run.
source.md lists every change made here.

Only three things changed, and none of them is an expectation:

1. `def test_unescape_html(self)` became `def test_unescape_html()`. The method
   lives on the project's TestUtil class, which needs unittest, and here it is a
   plain pytest function instead.
2. `self.assertEqual(a, b)` became `assert a == b`. Same comparison.
3. `unescapeHTML(...)` became `unescapeHTML(...)` imported from `target`.

Every input and every expected value is the project's, character for character.
No case was added, removed or edited.
"""

from target import unescapeHTML


def test_unescape_html():
    assert unescapeHTML('%20;') == '%20;'
    assert unescapeHTML('&#x2F;') == '/'
    assert unescapeHTML('&#47;') == '/'
    assert unescapeHTML('&eacute;') == 'é'
    assert unescapeHTML('&#2013266066;') == '&#2013266066;'
    assert unescapeHTML('&a&quot;') == '&a"'
    # HTML5 entities
    assert unescapeHTML('&period;&apos;') == '.\''