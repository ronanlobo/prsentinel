# Saved baseline: round1_off_by_one

This is the saved baseline from a live run on 30 September 2026. It is a copy
of the test file the AI wrote for `get_recent_scores`, taken straight from
`generated_tests/round1_off_by_one/` after the pipeline finished.

The pipeline writes a new set of tests every time it runs, and the count moves
from run to run, so this folder is the fixed version to compare against. To run
the pipeline again without asking the AI for new tests, use:

    python -m prsentinel.pipeline examples/round1_off_by_one/before.py examples/round1_off_by_one/after.py --reuse-tests

The file in `first_live_run/` is what this function's tests looked like on the
first live run, kept byte for byte as it was. It is here as an example of what
the AI produces early on, and is not the version used for the results above.
