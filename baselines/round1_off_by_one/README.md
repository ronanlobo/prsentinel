# Saved baseline: round1_off_by_one

This is the saved baseline from a live run on 30 September 2026. It is a copy
of the test file the AI wrote for `get_recent_scores`, taken straight from
`generated_tests/round1_off_by_one/` after the pipeline finished.

The pipeline writes a new set of tests every time it runs, and the count moves
from run to run, so this folder is the fixed version to compare against. To run
the pipeline again without asking the AI for new tests, use:

    python -m prsentinel.pipeline examples/round1_off_by_one/before.py examples/round1_off_by_one/after.py --reuse-tests
