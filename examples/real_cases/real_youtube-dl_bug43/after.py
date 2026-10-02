"""youtube-dl bug 43. This is our "after": the BUGGY version.

The only line that changed from before.py is the character class in the regex
inside url_basename: [^?#]+ became [^/?#]+. That is the real fix, read
backwards, because BugsInPy records the fix and Step 10A wants "before" to be
the correct code.

Zero helpers are copied in. url_basename uses only re from the standard library
and its own parameter.

Worth knowing: the real bug_patch.txt hunk header says "def remove_start(s,
start)", which is the function BEFORE the changed one. The change is actually in
url_basename. A real diff's header is a hint, not a promise. source.md says more.
"""

import re


# --- CHANGED FUNCTION: youtube_dl/utils.py, lines 1089-1093 -------------

def url_basename(url):
    m = re.match(r'(?:https?:|)//[^/]+/(?:[^/?#]+/)?([^/?#]+)/?(?:[?#]|$)', url)
    if not m:
        return u''
    return m.group(1)
