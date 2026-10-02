"""youtube-dl's own test for this bug, byte for byte.

Copied from test/test_utils.py lines 185-193 at the fixed commit
d6c7a367e88096bb17e323954002c084477fe908. Not one character was changed.

This is a method on the project's TestUtil class, so it cannot run on its own:
it needs the class, the imports above it, and the whole youtube_dl package to
import. That is why there is a second file, existing_test.py, which is the same
test flattened into a standalone pytest function. source.md lists every change.

This file is kept for the record. Nothing runs it.
"""


    def test_url_basename(self):
        self.assertEqual(url_basename(u'http://foo.de/'), u'')
        self.assertEqual(url_basename(u'http://foo.de/bar/baz'), u'baz')
        self.assertEqual(url_basename(u'http://foo.de/bar/baz?x=y'), u'baz')
        self.assertEqual(url_basename(u'http://foo.de/bar/baz#x=y'), u'baz')
        self.assertEqual(url_basename(u'http://foo.de/bar/baz/'), u'baz')
        self.assertEqual(
            url_basename(u'http://media.w3.org/2010/05/sintel/trailer.mp4'),
            u'trailer.mp4')
