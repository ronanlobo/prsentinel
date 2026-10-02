"""youtube-dl's own test for bug 43, flattened so pytest can run it.

Source: test/test_utils.py, method TestUtil.test_url_basename, lines 185-193.
The byte-for-byte original is in existing_test_original.py and is never run.
source.md lists every change made here.

Only three things changed, and none of them is an expectation:

1. `def test_url_basename(self)` became `def test_url_basename()`. The method
   lives on the project's TestUtil class, which needs unittest, and here it is a
   plain pytest function instead.
2. `self.assertEqual(a, b)` became `assert a == b`. Same comparison.
3. `url_basename` is imported from `target`.

Every input and every expected value is the project's, character for character.
No case was added, removed or edited.
"""

from target import url_basename


def test_url_basename():
    assert url_basename(u'http://foo.de/') == u''
    assert url_basename(u'http://foo.de/bar/baz') == u'baz'
    assert url_basename(u'http://foo.de/bar/baz?x=y') == u'baz'
    assert url_basename(u'http://foo.de/bar/baz#x=y') == u'baz'
    assert url_basename(u'http://foo.de/bar/baz/') == u'baz'
    assert url_basename(
        u'http://media.w3.org/2010/05/sintel/trailer.mp4') == u'trailer.mp4'