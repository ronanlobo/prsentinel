"""Offer picker, after the change.

The only difference from before.py is the sign in the key function. Negating the
discount makes min() pick the LARGEST discount instead of the smallest, which is
a real kind of bug and one that a passing test on the old code would have
caught.

reward_word() is byte for byte the same as it was before. It is not part of this
change and it is not meant to be.
"""

OFFERS = {"gold": 40, "silver": 60, "bronze": 80, "trial": 100}

REWARD_WORDS = {"alpha", "bravo", "charlie"}


def best_offer(codes):
    """The code we were given that gives the smallest discount."""
    live = [code for code in codes if code in OFFERS]
    if not live:
        return None
    return min(live, key=lambda code: -OFFERS[code])


def reward_word():
    """A word to show the user.

    Which word comes out depends on the order the set happens to be walked in,
    and that order is different in every process. This is the kind of thing that
    really happens when a set is used where a list was meant.
    """
    return next(iter(REWARD_WORDS))