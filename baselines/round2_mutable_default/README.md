# Saved baseline: round2_mutable_default

This is the saved baseline from a live run on 30 September 2026. It is a copy
of the test file the AI wrote for `add_item_to_cart`, taken straight from
`generated_tests/round2_mutable_default/` after the pipeline finished.

The pipeline writes a new set of tests every time it runs, and the count moves
from run to run, so this folder is the fixed version to compare against. To run
the pipeline again without asking the AI for new tests, use:

    python -m prsentinel.pipeline examples/round2_mutable_default/before.py examples/round2_mutable_default/after.py --reuse-tests

The file in `first_live_run/` is what this function's tests looked like on the
first live run, kept byte for byte as it was. It is here because it contains
`test_default_cart_not_shared_across_multiple_calls`, a test that fails on
both the old and the new code and is therefore correctly labelled `BAD_TEST`
rather than `REAL_BUG`. It is the clearest example of why PRSentinel cannot
just call every failing test a bug, and it is not the version used for the
results above.
