"""youtube-dl bug 43. This is our "before": the CORRECT version.

BugsInPy calls the buggy commit "before the fix". Step 10A reverses that, so
this file is the FIXED commit, which works, and it is PRSentinel's "before".

The fix is one character class inside one regex:

    (?:[^?#]+/)?    correct -- a path segment may contain a '?'
    (?:[^/?#]+/)?   buggy   -- it may not, so a URL whose query string is in
                             the middle of the path loses its last segment

Zero helpers are copied in. url_basename uses only re from the standard library
and its own parameter. That is why this was the first candidate tried.
"""

import re


# --- CHANGED FUNCTION: youtube_dl/utils.py, lines 1089-1093 -------------

def url_basename(url):
    m = re.match(r'(?:https?:|)//[^/]+/(?:[^?#]+/)?([^/?#]+)/?(?:[?#]|$)', url)
    if not m:
        return u''
    return m.group(1)
