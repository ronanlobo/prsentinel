"""Answer key case: working out a discount price.

This file is the "after" version of the example.
"""


def final_price(price, percent_off):
    """Work out the price after taking a percentage off."""
    return price - (price * percent_off / 10)
