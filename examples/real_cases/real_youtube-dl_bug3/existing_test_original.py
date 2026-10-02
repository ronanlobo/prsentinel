"""youtube-dl's own test for this bug, byte for byte.

Copied from test/test_utils.py lines 276-284 at the fixed commit
95f3f7c20a05e7ac490e768b8470b20538ef8581. Not one character was changed.

This is a method on the project's TestUtil class, so it cannot run on its own:
it needs the class, the imports above it, and the whole youtube_dl package to
import. That is why there is a second file, existing_test.py, which is the same
test flattened into a standalone pytest function. source.md lists every change.

This file is kept for the record. Nothing runs it.
"""


    def test_unescape_html(self):
        self.assertEqual(unescapeHTML('%20;'), '%20;')
        self.assertEqual(unescapeHTML('&#x2F;'), '/')
        self.assertEqual(unescapeHTML('&#47;'), '/')
        self.assertEqual(unescapeHTML('&eacute;'), 'é')
        self.assertEqual(unescapeHTML('&#2013266066;'), '&#2013266066;')
        self.assertEqual(unescapeHTML('&a&quot;'), '&a"')
        # HTML5 entities
        self.assertEqual(unescapeHTML('&period;&apos;'), '.\'')
