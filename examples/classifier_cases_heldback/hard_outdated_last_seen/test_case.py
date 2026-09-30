"""An older test for the first step."""

from target import label_of


def test_label_of_starts_at_alpha():
    steps = [{"label": "alpha", "order": 1}, {"label": "beta", "order": 2}]
    assert label_of(steps) == "alpha"