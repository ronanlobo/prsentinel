# Witness for youtube-dl bug 3

A witness is a few lines of code that behave **differently** on `before.py` and
on `after.py`. If a witness gives the same answer on both, the case is not
reproducing and `scripts/check_real_cases.py` rejects it rather than working
around it.

## What is being shown

`unescapeHTML` scans a string for HTML entities and decodes them. The regex it
uses to find one entity is the whole bug:

| | regex | meaning |
|---|---|---|
| `before.py` (correct) | `r'&([^&;]+;)'` | an entity may not contain `&`, so in `&a&quot;` the run `&a` cannot be an entity and the scan starts again at the second `&`, decoding `&quot;` to `"` |
| `after.py` (buggy) | `r'&([^;]+;)'` | `&` is allowed inside, so the whole run `&a&quot;` is taken as one entity, which is not a real entity, so it is handed back unchanged |

The difference shows up on input where a run of text that looks like an entity
starts with an `&` that is not really an entity start. `'&a&quot;'` is the
shortest such input.

## The witness

```python
import target

# 'a' is not the start of any entity, so '&a' is literal text. The entity that
# follows it is '&quot;', which should decode to a double quote.
INPUT = '&a&quot;'

print('input:', repr(INPUT))
print('result:', repr(target.unescapeHTML(INPUT)))
```

## What each version prints

`before.py`, the correct version:

```
input: '&a&quot;'
result: '&a"'
```

`after.py`, the buggy version:

```
input: '&a&quot;'
result: '&a&quot;'
```

## Was this checked on Python 3.13?

Yes. BugsInPy pins this bug to Python 3.7.0. `scripts/check_real_cases.py`
re-runs the witness on whatever Python is running it and will not call the case
reproduced unless the two outputs actually differ. The output above was taken on
Python 3.13.9. The code is plain `re`, so the Python version does not affect it.

## A note on how this input was chosen

A double-escaped input like `'&amp;quot;'` was the first thing tried, on the
reasoning that the buggy regex would swallow the whole thing. It does not work,
and the reason is worth writing down: `[^;]+` still cannot cross a `;`, so in
`&amp;quot;` both versions match `&amp;` and stop. Both return `'&quot;'`. That
input cannot tell the two versions apart on any Python.

`'&a&quot;'` was then found by searching inputs until the two versions actually
disagreed, and it is the shortest one that does. It is also, not by design, the
same input the project's own test uses. The check script is what caught the
first choice being wrong: it rejected the case, and the input was replaced rather
than the check being relaxed.

## The project's own test does catch this bug

`test_unescape_html` has a case `unescapeHTML('&a&quot;') == '&a"'`, which is
exactly this shape. So the test passes on `before.py` and fails on `after.py`,
and the check script reports `CATCHES_CHANGE`. This case and its witness agree.