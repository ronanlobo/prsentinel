"""youtube-dl bug 3. This is our "after": the BUGGY version.

The only line that changed from before.py is the character class in the regex
inside unescapeHTML: [^&;]+ became [^;]+. That is the real fix, read backwards,
because BugsInPy records the fix and Step 10A wants "before" to be the correct
code.

With [^;] the first & of a run like "&amp;quot;" is swallowed as part of the
entity, so the entity after it is never decoded.

One project helper is copied in: _htmlentity_transform, from youtube_dl/utils.py
lines 562-590. Four one-line shims are copied from youtube_dl/compat.py, which is
where the project re-exports standard-library names. source.md has the list.

Every line above the CHANGED FUNCTION marker is byte-identical to before.py.
"""

import re

# --- copied verbatim from youtube_dl/compat.py, lines 63, 68, 2352 and 2492 --
# In compat.py each of these sits indented inside a try/except, one branch per
# Python version. Only the branch Python 3 takes is kept, dedented to column 0.

import html.entities as compat_html_entities
compat_html_entities_html5 = compat_html_entities.html5
compat_str = str
compat_chr = chr


# --- copied verbatim from youtube_dl/utils.py, lines 562-590 ------------

def _htmlentity_transform(entity_with_semicolon):
    """Transforms an HTML entity to a character."""
    entity = entity_with_semicolon[:-1]

    # Known non-numeric HTML entity
    if entity in compat_html_entities.name2codepoint:
        return compat_chr(compat_html_entities.name2codepoint[entity])

    # TODO: HTML5 allows entities without a semicolon. For example,
    # '&Eacuteric' should be decoded as 'Éric'.
    if entity_with_semicolon in compat_html_entities_html5:
        return compat_html_entities_html5[entity_with_semicolon]

    mobj = re.match(r'#(x[0-9a-fA-F]+|[0-9]+)', entity)
    if mobj is not None:
        numstr = mobj.group(1)
        if numstr.startswith('x'):
            base = 16
            numstr = '0%s' % numstr
        else:
            base = 10
        # See https://github.com/rg3/youtube-dl/issues/7518
        try:
            return compat_chr(int(numstr, base))
        except ValueError:
            pass

    # Unknown entity in name, return its literal representation
    return '&%s;' % entity


# --- CHANGED FUNCTION: youtube_dl/utils.py, lines 593-599 ----------------

def unescapeHTML(s):
    if s is None:
        return None
    assert type(s) == compat_str

    return re.sub(
        r'&([^;]+;)', lambda m: _htmlentity_transform(m.group(1)), s)
