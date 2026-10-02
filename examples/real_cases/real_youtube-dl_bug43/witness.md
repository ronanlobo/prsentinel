# Witness for youtube-dl bug 43

A witness is a few lines of code that behave **differently** on `before.py` and
on `after.py`. If a witness gives the same answer on both, the case is not
reproducing and `scripts/check_real_cases.py` rejects it rather than working
around it.

## What is being shown

`url_basename(url)` returns the last path segment of a URL: given
`http://host/a/b/c.mp4` it returns `c.mp4`. The regex it uses is the whole bug:

| | regex | meaning |
|---|---|---|
| `before.py` (correct) | `(?:[^?#]+/)?` | a path segment may contain a `?`, so the scan can still find the last real segment when the query string begins part-way through the path |
| `after.py` (buggy) | `(?:[^/?#]+/)?` | a segment may not contain a `?`, so once a `?` appears mid-path nothing matches and the function returns the empty string |

Two things have to be true for the difference to show: the path must have **more
than two** segments, and the query string must contain a `/`. With one segment
after the last `/`, or with a query that has no `/` in it, both versions agree.

## The witness

```python
import target

# The path ends at sintel_trailer-720p.mp4. Everything from '?' on is the query
# string. A '/' inside a query is legal, and it is what makes the two versions
# disagree.
INPUT = ('https://media.w3.org/2010/05/sintel/trailer.mp4'
         '?download=1/movies/other.mp4')

print('input:', INPUT)
print('result:', repr(target.url_basename(INPUT)))
```

## What each version prints

`before.py`, the correct version:

```
input: https://media.w3.org/2010/05/sintel/trailer.mp4?download=1/movies/other.mp4
result: 'trailer.mp4'
```

`after.py`, the buggy version:

```
input: https://media.w3.org/2010/05/sintel/trailer.mp4?download=1/movies/other.mp4
result: ''
```

The buggy version insists no segment can exist before a `?`, so it finds none and
returns the empty string. A file name silently becomes nothing, and the caller
has no way to tell that from a URL that genuinely had no file in it.

## Was this checked on Python 3.13?

Yes. BugsInPy pins this bug to Python 3.7.4. `scripts/check_real_cases.py`
re-runs the witness on whatever Python is running it and will not call the case
reproduced unless the two outputs actually differ. The output above was taken on
Python 3.13.9. The code is plain `re`, so the Python version does not affect it.

## A note on how this input was chosen

A shorter URL, `https://download.samplelib.com/mp4/sample-5s.mp4?download=1/x`,
was the first thing tried and it does **not** work: it has only one path segment
after the domain, so both versions return `sample-5s.mp4`. The check script
rejected the case and the input was replaced rather than the check being
relaxed. The input above is the shortest one with enough segments that the two
versions actually disagree.

## Note: this is the bug whose patch header names the wrong function

The real `bug_patch.txt` hunk header reads
`@@ -1087,7 +1087,7 @@ def remove_start(s, start):`. It says `remove_start`.
The line that actually changes is three lines below it, inside `url_basename`.

That is normal `diff` behaviour, not a mistake by youtube-dl. A hunk header names
the nearest function that **starts above** the changed line, so when a change
lands in the second function of a hunk the header still points at the first.
Anyone reading a real patch by its header alone extracts the wrong function here.
`source.md` has the numbers for how often that happens across BugsInPy.