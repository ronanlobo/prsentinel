from target import best_offer, reward_word


def test_best_offer_picks_the_smallest_discount():
    """Passes on the old code, fails on the new one. Real bug.

    gold gives 40 and silver gives 60, so the smallest is gold. The new code
    negates the number, so min() takes silver instead.
    """
    assert best_offer(["gold", "silver"]) == "gold"


def test_best_offer_of_an_unknown_code():
    """The wrong test. It fails on the old code as well, so it says nothing
    about this change either way.

    Written against a version of the code that returned something for an
    unknown code instead of None.
    """
    assert best_offer(["not-a-code"]) == "gold"


def test_reward_word_is_alpha():
    """Flaky, and not on purpose.

    reward_word walks a three item set and hands back whichever word comes
    first. Set order is different in every process, so this passes about one run
    in three and fails the rest. There is no counter and no seed anywhere in
    reach of it.
    """
    assert reward_word() == "alpha"