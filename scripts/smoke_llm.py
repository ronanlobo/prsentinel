r"""Check that the real LLM providers still work.

Run it with:  .venv\Scripts\python.exe scripts\smoke_llm.py

This is the only place that uses the internet. It reads your API keys from the
environment, but it never prints a key and never writes one to a file.
"""

import sys
from pathlib import Path

# Make sure the prsentinel package can be found when run from the scripts folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from prsentinel import config, llm_client  # noqa: E402

QUESTION = "Reply with exactly: OK"

# A value that is deliberately not a real key, used to force a failure below.
# It is kept in memory only and is never written to disk.
BROKEN_KEY = "broken-on-purpose-for-smoke-test"


def check(label, function):
    """Run one provider and report whether it worked. Returns True or False."""
    print(f"\n--- {label} ---")
    try:
        answer = function(QUESTION)
    except Exception as error:
        print(f"  FAILED: {type(error).__name__}: {error}")
        return False
    print(f"  answered: {answer.strip()[:80]}")
    return True


def main():
    """Run three checks and print a summary. Returns 0 if all of them pass."""
    print("PRSentinel LLM smoke test")
    print(f"Groq model   : {config.GROQ_MODEL}")
    print(f"Gemini model : {config.GEMINI_MODEL}")
    print(f"Groq key set : {config.has_groq_key()}")
    print(f"Gemini key set: {config.has_gemini_key()}")

    results = {}

    # 1. Groq on its own.
    if config.has_groq_key():
        results["Groq alone"] = check("Groq alone", llm_client._ask_groq)
    else:
        print("\n--- Groq alone ---")
        print("  SKIPPED: GROQ_API_KEY is not set")
        results["Groq alone"] = None

    # 2. Gemini on its own.
    if config.has_gemini_key():
        results["Gemini alone"] = check("Gemini alone", llm_client._ask_gemini)
    else:
        print("\n--- Gemini alone ---")
        print("  SKIPPED: GEMINI_API_KEY is not set")
        results["Gemini alone"] = None

    # 3. The fallback, using a deliberately broken Groq key in memory only.
    #    We never touch your real key and never write this one anywhere.
    print("\n--- Fallback (Groq key broken on purpose) ---")
    real_key = config.get_groq_api_key()
    import os
    os.environ["GROQ_API_KEY"] = BROKEN_KEY
    try:
        answer = llm_client.ask_llm(QUESTION)
        print(f"  answered: {answer.strip()[:80]}")
        results["Fallback"] = True
    except Exception as error:
        print(f"  FAILED: {type(error).__name__}: {error}")
        results["Fallback"] = False
    finally:
        # Put your real key back exactly as it was.
        os.environ["GROQ_API_KEY"] = real_key

    print("\n=== Summary ===")
    for label, passed in results.items():
        if passed is None:
            print(f"  SKIPPED  {label}")
        elif passed:
            print(f"  PASSED   {label}")
        else:
            print(f"  FAILED   {label}")

    failed = [k for k, v in results.items() if v is False]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
