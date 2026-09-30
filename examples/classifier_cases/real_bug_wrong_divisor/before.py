"""Answer key case: working out a discount price."""


def final_price(price, percent_off):
    """Work out the price after taking a percentage off."""
    return price - (price * percent_off / 100)
