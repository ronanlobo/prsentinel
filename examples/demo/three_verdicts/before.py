"""Offer picker, before the change.

One function is about to be changed, and the change is wrong on purpose, so the
demo has something real to point at. The helper further down is not touched by
the change at all: it is here so the demo has a flaky test that is genuinely
unpredictable rather than one faked with a counter.
"""

OFFERS = {"gold": 40, "silver": 60, "bronze": 80, "trial": 100}

REWARD_WORDS = {"alpha", "bravo", "charlie"}


def best_offer(codes):
    """The code we were given that gives the smallest discount."""
    live = [code for code in codes if code in OFFERS]
    if not live:
        return None
    return min(live, key=lambda code: OFFERS[code])


def reward_word():
    """A word to show the user.

    Which word comes out depends on the order the set happens to be walked in,
    and that order is different in every process. This is the kind of thing that
    really happens when a set is used where a list was meant.
    """
    return next(iter(REWARD_WORDS))