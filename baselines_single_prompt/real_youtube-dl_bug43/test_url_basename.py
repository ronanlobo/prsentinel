import re
import pytest
from target import url_basename

def old_url_basename(url):
    """Reference implementation using the original regex."""
    m = re.match(r'(?:https?:|)//[^/]+/(?:[^?#]+/)?([^/?#]+)/?(?:[?#]|$)', url)
    if not m:
        return u''
    return m.group(1)

@pytest.mark.parametrize(
    "url",
    [
        # basic cases
        "http://example.com/foo",
        "https://example.com/foo/",
        "http://example.com/foo?bar=baz",
        "https://example.com/foo#section",
        "http://example.com/foo/?query=1",
        "https://example.com/foo/#anchor",
        # trailing slash variations
        "http://example.com/foo/",
        "https://example.com/foo//",  # double slash after basename
        # multiple path segments before basename
        "http://example.com/a/b/c",
        "https://example.com/a/b/c/",
        "http://example.com/a/b/c?x=1",
        "https://example.com/a/b/c#frag",
        # path segment that includes a slash (old regex allowed it)
        "http://example.com/a/bc/d",
        # URLs with port numbers
        "http://example.com:8080/foo",
        "https://example.com:443/bar/baz",
        # URLs with authentication info
        "http://user:pass@example.com/foo",
        # URLs with query and fragment together
        "https://example.com/foo?x=1#y",
        # URLs that should not match (return empty string)
        "ftp://example.com/file",
        "example.com/foo",
        "/relative/path",
        "http:/example.com/missing-slash",
        "https//missing-colon.com",
        "",
        "   ",
    ],
)
def test_url_basename_behaviour(url):
    assert url_basename(url) == old_url_basename(url)
