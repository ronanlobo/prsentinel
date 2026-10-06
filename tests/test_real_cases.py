# The only places outside src/ that are allowed to name the real cases.
#
# Three, and all three are named here on purpose. If a fourth ever appears it has
# to be added to this tuple in the same commit that created it, so that widening
# the exception is something somebody chose rather than something that happened.
ALLOWED_ELSEWHERE = (
    "scripts/check_real_cases.py",
    "scripts/eval_real_cases.py",
    "scripts/baseline_single_prompt.py",
    "scripts/repeat_real_cases.py",
    "scripts/repeat_summary.py",
)