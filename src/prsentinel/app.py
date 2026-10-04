r"""A small local web app for showing PRSentinel to somebody sitting next to you.

Start it with:

    python -m prsentinel.app

and open http://127.0.0.1:8000. It binds to the loopback address only, so
nothing on the network can reach it.

What it does
------------
You pick one of the built-in demo cases or paste your own before and after code,
you say whether to use the saved tests or ask Groq for new ones, and it runs the
real pipeline and shows you the real report. Nothing here decides anything: the
app calls pl.run_pipeline and formats whatever comes back. It has no opinions of
its own about what a verdict means.

How a run works
---------------
Each run is a separate Python process, not a thread. That is deliberate:

- A thread cannot be killed, so a run that hangs would keep the one-run-at-a-time
  lock and the app would be stuck for ever. A child process can be stopped.
- The pipeline prints its progress to standard output. Reading that from another
  process is a pipe, and a pipe is what server-sent events want anyway.

The child is this same file run with --run-once and a job file. It puts one
marker letter at the start of every line it writes, so the parent can tell a
progress line from the result from an error without guessing:

    P <text>   a line the pipeline printed, to show as it arrives
    R <json>   the report, which is the thing the page draws
    F <text>   the run stopped early and there is no result
    E <text>   something went wrong that we can say out loud

Why server-sent events rather than polling: the page only ever needs to read.
Polling would mean inventing an interval, checking a counter, and leaving a
timer running while somebody is talking. An event stream needs none of that, and
it starts arriving on the first line the pipeline prints.

Saved tests, and what "saved" means here
----------------------------------------
Saved-tests mode makes no call to any AI at all. It copies the demo case's test
file into the folder the pipeline looks in, then calls the pipeline with
reuse_tests set, which is the switch that skips writing tests. The page labels
those results "saved" and generated ones "generated", and never mixes the two
words, because the difference is the whole point of showing both.

Keys
----
The app never prints, returns or logs a key, and never reads one into a
response. The only thing it checks is whether the variable is set at all, so it
can say "you did not set the key" instead of crashing. The browser never sees a
key, because no key is ever on its way to the browser.
"""

import argparse
import ast
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import uuid
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from prsentinel import config
from prsentinel import pipeline as pl

# Where things are. Everything is worked out from this file's own location, so
# the app works from a checkout, from an editable install and from a real one.
HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent

DEMOS = PROJECT / "examples" / "demo"
SCRATCH = PROJECT / "demo_scratch"
GENERATED = PROJECT / "generated_tests"
REPORTS = PROJECT / "reports"

# Only folders this app made carry this file. It is how we tell our own
# leftovers from somebody's work, and the app refuses to touch a folder without
# it rather than guessing.
MARKER = ".prsentinel-demo-owned"

# Every run's name starts with this, and nothing is ever deleted again unless it
# does.
RUN_PREFIX = "demo_"

# The sentence the page shows under every result. It is the same wording the
# pull request comment uses and the same wording the tests hold, because it is
# the one thing that is true of every result this app can produce.
SAFETY_SENTENCE = ("Tests are AI-generated. "
                   "A catching test is a hint, not proof.")

# The plain-language answers for the two ways a run can produce nothing.
DAILY_LIMIT_MESSAGE = ("No result: the AI allowance is used up. "
                       "This is not a pass.")
TIMEOUT_MESSAGE = ("No result: the run took longer than 5 minutes and was "
                   "stopped. That says nothing about the code.")

# How many finished runs to keep around so a page that opens its stream a moment
# late still finds its run.
KEEP_RUNS = 8

# The switch that turns this same file into the child that does the work.
CHILD_FLAG = "--run-once"

# Serialises whole run requests, so two clicks landing at the same instant
# cannot both get as far as writing into the same generated_tests folder. The
# folder has to be named after the case, because that is the name the pipeline
# looks the saved test up by, so it cannot be made unique per run instead.
START_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# The demo cases on disk
# ---------------------------------------------------------------------------

def demo_cases() -> list:
    """The built-in cases, one entry per folder.

    A folder counts only when it has the old code, the new code and exactly one
    saved test file. A half folder is not a demo, and offering it would put a
    failure on screen that has nothing to do with the tool.
    """
    found = []
    if not DEMOS.is_dir():
        return found

    for folder in sorted(DEMOS.iterdir()):
        if not folder.is_dir():
            continue

        tests = sorted(folder.glob("test_*.py"))
        if not (folder / "before.py").is_file():
            continue
        if not (folder / "after.py").is_file():
            continue
        if len(tests) != 1:
            continue

        found.append({
            "name": folder.name,
            "title": folder.name.replace("_", " "),
            "test_file": tests[0].name,
            "note": demo_note(folder.name),
        })

    return found


def demo_note(name: str) -> str:
    """One line about a case, read from the README beside the folders.

    The README is a normal markdown table, so the names in it are written in
    backticks. Both sides are stripped before being compared, because a note
    that silently comes back empty looks exactly like a case with no
    description, which is not what is happening.
    """
    readme = DEMOS / "README.md"
    if not readme.is_file():
        return ""

    for line in readme.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip().strip("`").strip()
                 for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] == name:
            return cells[1]
    return ""


def pick_demo(name: str):
    """The folder for one case, or None if the name is not one of ours.

    The name is used to build a path, so anything with a separator in it is
    refused outright rather than tidied up. A name that arrived from a browser
    should never be able to reach outside the demo folder.
    """
    if not name or name != Path(name).name or name in (".", ".."):
        return None

    folder = DEMOS / name
    if not folder.is_dir():
        return None
    if not (folder / "before.py").is_file():
        return None
    if not (folder / "after.py").is_file():
        return None
    return folder


# ---------------------------------------------------------------------------
# Writing the files a run needs, and taking them away again
# ---------------------------------------------------------------------------

def claim_folder(folder: Path) -> str:
    """Take ownership of a generated_tests folder, or say why we cannot.

    Anything already there without our marker is somebody's work, so it is left
    alone and the run is refused. That refusal is the only thing standing
    between this and a demo that quietly overwrites a real saved test file.

    Returns an empty string when the folder is ours to write into, otherwise a
    sentence the page can show.
    """
    if folder.exists():
        if not (folder / MARKER).is_file():
            return (f"The folder {folder.name} already exists and was not made "
                    f"by this app, so it will not be touched. Move it aside or "
                    f"delete it and try again.")
    else:
        folder.mkdir(parents=True, exist_ok=True)

    (folder / MARKER).write_text("Made by the PRSentinel demo app.\n",
                                 encoding="utf-8")
    return ""


def clean_up(name: str, folder, scratch) -> None:
    """Take away exactly what one run put down, and nothing else.

    Three things, all named after the run: the scratch folder holding the pasted
    or copied code, the generated_tests folder if we claimed it, and the pair of
    report files the pipeline wrote. Each is checked to be ours before it is
    removed, so a name that does not look right is skipped rather than deleted.
    """
    if scratch is not None:
        try:
            if scratch.is_dir() and scratch.name.startswith("demo_"):
                shutil.rmtree(scratch, ignore_errors=True)
                # The parent goes too, but only when this run left it empty.
                # Somewhere else keeps its own folder under there.
                scratch.parent.rmdir()
        except OSError:
            pass

    if folder is not None:
        try:
            if folder.is_dir() and (folder / MARKER).is_file():
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass

    if not name.startswith(RUN_PREFIX):
        return

    for suffix in (".json", ".md"):
        path = REPORTS / f"{name}{suffix}"
        try:
            if path.is_file() and path.name.startswith(RUN_PREFIX):
                path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# The child process, which does the actual work
# ---------------------------------------------------------------------------

class LineWriter:
    """Stands in for standard output so that every line can be marked.

    print() calls write() twice, once for the text and once for the newline, so
    partial writes are held until a newline arrives. Without this the parent
    would read half a line and think it was a whole one.
    """

    def __init__(self, marker):
        self.marker = marker
        self.held = ""

    def write(self, text):
        self.held += text
        while "\n" in self.held:
            line, self.held = self.held.split("\n", 1)
            self._send(line)
        return len(text)

    def _send(self, line):
        sys.__stdout__.write(f"{self.marker} {line}\n")
        sys.__stdout__.flush()

    def flush(self):
        if self.held:
            self._send(self.held)
            self.held = ""


def emit(marker: str, text: str) -> None:
    sys.__stdout__.write(f"{marker} {text}\n")
    sys.__stdout__.flush()


def run_once(job: dict) -> int:
    """The whole child: read the job, run the pipeline, report what came back.

    The AI is only reached if the job says to reach it, and never through the
    second provider, so a result is either from one model or from none.
    """
    saved = job.get("mode") == "saved"

    sys.stdout = LineWriter("P")
    try:
        report = pl.run_pipeline(
            job["before"],
            job["after"],
            name=job["name"],
            reuse_tests=saved,
            repair_tests=False,
            ai_second_opinion=False,
            fallback_allowed=False,
            mutation=bool(job.get("mutation")),
        )
    except pl.DailyLimitStop:
        emit("F", DAILY_LIMIT_MESSAGE)
        return 0
    except Exception as error:                      # noqa: BLE001
        # Said out loud rather than swallowed. A demo showing a stack trace is
        # embarrassing; a demo showing nothing at all is worse.
        emit("E", f"{type(error).__name__}: {error}")
        return 0
    finally:
        sys.stdout.flush()
        sys.stdout = sys.__stdout__

    emit("R", json.dumps(tidy(report, saved)))
    return 0


def tidy(report: dict, saved: bool) -> dict:
    """The report as the page should see it.

    Two changes and no others. The two paths become file names, because a scratch
    folder inside the project is noise to a reader and has no use on a projector.
    The mode is added, so the page can say saved or generated from something it
    can trust rather than guessing from the numbers.
    """
    clean = dict(report)
    for key in ("before", "after"):
        if clean.get(key):
            clean[key] = Path(str(clean[key])).name

    clean["app_mode"] = "saved" if saved else "generated"
    return clean


# ---------------------------------------------------------------------------
# Running a job and streaming what comes out
# ---------------------------------------------------------------------------

class Job:
    """One run, and the queue its output arrives on."""

    def __init__(self, job_id, name, mode, folder, scratch):
        self.id = job_id
        self.name = name
        self.mode = mode
        self.folder = folder
        self.scratch = scratch
        self.events = queue.Queue()

    def put(self, event):
        self.events.put(event)

    def finish(self):
        self.events.put(None)


class Runner:
    """Keeps one run in flight at a time and owns the lock.

    A second click while a run is going is refused here rather than separately in
    each route, so there is one place that knows whether the app is busy.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.current = None
        self.finished = []

    def busy(self) -> bool:
        with self.lock:
            return self.current is not None

    def start(self, name, mode, folder, scratch, job_file) -> Job:
        with self.lock:
            if self.current is not None:
                raise HTTPException(
                    status_code=409,
                    detail=("A run is already going. Wait for it to finish, "
                            "then press Run again."))
            job = Job(uuid.uuid4().hex[:12], name, mode, folder, scratch)
            self.current = job

        # The child inherits this machine's environment so that tempfile and the
        # rest of the test runner work, but the second provider's key is emptied
        # on the way in. run_pipeline is also told not to fall back, so neither
        # switch alone is doing the work.
        child_env = dict(os.environ)
        child_env["GEMINI_API_KEY"] = ""
        child_env["PYTHONIOENCODING"] = "utf-8"

        child = subprocess.Popen(
            [sys.executable, "-m", "prsentinel.app", CHILD_FLAG, str(job_file)],
            cwd=str(PROJECT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            env=child_env,
        )

        threading.Thread(target=self._read, args=(job, child),
                         daemon=True).start()
        threading.Thread(target=self._watch, args=(job, child),
                         daemon=True).start()

        return job

    def _read(self, job, child):
        """Turn the child's marked lines into events for the page.

        This thread also takes the run's files away, and it does that before it
        says the run is done. Tidying up used to happen in the other thread,
        which is a race: that thread can still be working when this one has
        already announced the end, so a page that looked for its files the
        instant it saw done could find them still sitting there. Here, done means
        done.
        """
        for line in child.stdout:
            marker, _, text = line.rstrip("\n").partition(" ")
            if marker == "P":
                job.put({"type": "progress", "text": text})
            elif marker == "R":
                try:
                    job.put({"type": "result", "report": json.loads(text)})
                except ValueError:
                    job.put({"type": "error",
                             "message": ("The run finished but its result could "
                                         "not be read.")})
            elif marker == "F":
                job.put({"type": "stopped", "message": text})
            elif marker == "E":
                job.put({"type": "error", "message": text})
            else:
                job.put({"type": "progress", "text": line.rstrip("\n")})

        # This runs whether or not anybody is listening, so closing the tab
        # halfway through a run leaves nothing behind either.
        clean_up(job.name, job.folder, job.scratch)

        job.put({"type": "done"})
        job.finish()

    def _watch(self, job, child):
        """Stop the run if it outstays its welcome, then let go of the lock.

        The files are removed by _read, which is the only thread that knows the
        child's output has been drained. This one's job is the clock and the
        one-run-at-a-time lock.
        """
        try:
            child.wait(timeout=config.APP_RUN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            child.kill()
            job.put({"type": "stopped", "message": TIMEOUT_MESSAGE})

        with self.lock:
            if self.current is job:
                self.current = None
            self.finished.append(job)
            # Keep the list short. The page reads its run almost immediately, so
            # holding more than a handful back would only leak memory.
            while len(self.finished) > KEEP_RUNS:
                self.finished.pop(0)

    def find(self, job_id):
        """A run by id, whether it is going or has only just finished.

        A page that opens its stream a moment after the run ended must still find
        it, otherwise a fast run would look like a run that never happened.
        """
        with self.lock:
            if self.current is not None and self.current.id == job_id:
                return self.current
            for job in reversed(self.finished):
                if job.id == job_id:
                    return job
        return None


RUNNER = Runner()


# ---------------------------------------------------------------------------
# Checking what was asked for
# ---------------------------------------------------------------------------

def read_pasted(body: dict):
    """The two halves of a pasted change, or a sentence saying why not.

    Returns (before, after, complaint). complaint is empty when the pair is
    usable. Both halves have to be there, both have to be Python, and neither
    has to be enormous.
    """
    before = str(body.get("before") or "")
    after = str(body.get("after") or "")

    for label, text in (("before", before), ("after", after)):
        if not text.strip():
            return "", "", (f"There is no {label} code. Both halves are needed: "
                            f"the old code and the new code.")
        if len(text.encode("utf-8")) > config.APP_MAX_PASTED_BYTES:
            return "", "", (f"The {label} code is larger than "
                            f"{config.APP_MAX_PASTED_BYTES // 1000} KB, which is "
                            f"more than this app will hold. Paste one function "
                            f"rather than a whole file.")
        try:
            ast.parse(text)
        except SyntaxError as error:
            return "", "", (f"The {label} code is not valid Python. Line "
                            f"{error.lineno}: {error.msg}")

    if before == after:
        return "", "", ("The two halves are the same, so there is no change "
                        "to look at.")

    return before, after, ""


# ---------------------------------------------------------------------------
# The web app
# ---------------------------------------------------------------------------

app = FastAPI(title="PRSentinel demo", docs_url=None, redoc_url=None)


def page_text() -> str:
    """The HTML, found through the installed package.

    Not through a path relative to the current folder, because that works on the
    machine of whoever wrote the app and nowhere else. importlib.resources finds
    the file wherever pip put it, which is the whole point of shipping it as
    package data.
    """
    return (files("prsentinel") / "static" / "index.html").read_text(
        encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(page_text())


@app.get("/api/demos")
def list_demos():
    return {"demos": demo_cases(),
            "timeout_seconds": config.APP_RUN_TIMEOUT_SECONDS,
            "max_pasted_bytes": config.APP_MAX_PASTED_BYTES,
            "safety_sentence": SAFETY_SENTENCE,
            "model": config.GROQ_MODEL}


@app.post("/api/run")
def start_run(body: dict):
    """Write the files a run needs, start the child, hand back an id to watch.

    All the file writing happens here in the parent, so the child stays small and
    everything this run created is known to one place that can take it away
    again afterwards.

    The whole request is serialised on START_LOCK. Two clicks arriving at the
    same moment would otherwise both pass the busy check below, both write into
    the same generated_tests/demo_<case> folder, and the one that then lost the
    race would delete the files the winner was using. The work inside the lock is
    three small file copies, so holding it costs nothing worth measuring.
    """
    with START_LOCK:
        return _start_one_run(body)


def _start_one_run(body: dict):
    """Do the work of one run request. START_LOCK is already held."""
    mode = "fresh" if body.get("mode") == "fresh" else "saved"
    mutation = bool(body.get("mutation", True))
    wanted = str(body.get("demo") or "")

    # Checked before anything is written, and with START_LOCK held, so this
    # cannot go stale between here and Runner.start. If a second click were
    # refused only further down, the refusal would be the thing that tidied up
    # after the first job, and the running job would lose the files it is using.
    if RUNNER.busy():
        raise HTTPException(
            status_code=409,
            detail=("A run is already going. Wait for it to finish, then "
                    "press Run again."))

    # Fresh mode needs the key. Say so before anything is written, and say it
    # without putting the value anywhere.
    if mode == "fresh" and not os.environ.get("GROQ_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail=("No Groq key is set, so new tests cannot be written. Set "
                    "GROQ_API_KEY for your user account, open this page again, "
                    "or switch to Saved tests, which needs no key."))

    job_id = uuid.uuid4().hex[:12]
    demo = pick_demo(wanted) if wanted else None

    if wanted and demo is None:
        raise HTTPException(status_code=400,
                            detail="That is not one of the demo cases.")

    # Saved tests only exist for the built-in cases. Saying so up front is
    # clearer than letting the pipeline report a missing test file.
    if mode == "saved" and demo is None:
        raise HTTPException(
            status_code=400,
            detail=("Saved tests are the ones written earlier, and there are "
                    "none for pasted code. Pick a demo case, or switch to "
                    "Generate fresh tests."))

    name = RUN_PREFIX + (demo.name if demo else f"pasted_{job_id[:6]}")
    scratch = SCRATCH / f"demo_run_{job_id}"
    folder = None

    try:
        scratch.mkdir(parents=True, exist_ok=True)

        if demo is not None:
            # The saved test has to be in place before the pipeline looks for
            # it, so this copy happens first.
            folder = GENERATED / name
            refusal = claim_folder(folder)
            if refusal:
                raise HTTPException(status_code=409, detail=refusal)

            test_file = next(demo.glob("test_*.py"))
            shutil.copy2(demo / "before.py", scratch / "before.py")
            shutil.copy2(demo / "after.py", scratch / "after.py")
            shutil.copy2(test_file, folder / test_file.name)
        else:
            before, after, complaint = read_pasted(body)
            if complaint:
                raise HTTPException(status_code=400, detail=complaint)
            (scratch / "before.py").write_text(before, encoding="utf-8")
            (scratch / "after.py").write_text(after, encoding="utf-8")

        job_file = scratch / "job.json"
        job_file.write_text(json.dumps({
            "before": str(scratch / "before.py"),
            "after": str(scratch / "after.py"),
            "name": name,
            "mode": mode,
            "mutation": mutation,
        }), encoding="utf-8")

        job = RUNNER.start(name, mode, folder, scratch, job_file)
    except BaseException:
        clean_up(name, folder, scratch)
        raise

    return {"run_id": job.id, "name": name, "mode": mode, "mutation": mutation}


@app.get("/api/stream")
def stream(run_id: str):
    """Server-sent events: progress as it arrives, then the result, then done.

    Nothing is tidied up here. The run's files were taken away the moment its
    process ended, whether or not anybody was still listening.
    """
    job = RUNNER.find(run_id)
    if job is None:
        raise HTTPException(status_code=404,
                            detail="That run has already finished and its "
                                   "output is gone.")

    def events():
        while True:
            event = job.events.get()
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/api/state")
def state():
    """Whether the app is busy. The page asks on load and after every run."""
    return {"busy": RUNNER.busy()}


# ---------------------------------------------------------------------------
# Starting the app
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    """Work out what was asked for.

    Kept apart from main so it can be tested on its own. The child flag is a
    plain on/off switch on purpose: with it taking an optional value of its own,
    argparse eats the job file that follows it and the child starts with
    nothing at all to read.
    """
    parser = argparse.ArgumentParser(
        description="Run the PRSentinel demo app on your own machine.")
    parser.add_argument(CHILD_FLAG, action="store_true", default=False,
                        help=argparse.SUPPRESS)
    parser.add_argument("job_file", nargs="?", default=None,
                        help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    if args.run_once:
        if not args.job_file:
            print("A child run needs a job file.", file=sys.stderr)
            return 2
        spec = json.loads(Path(args.job_file).read_text(encoding="utf-8"))
        return run_once(spec)

    import uvicorn

    print(f"PRSentinel demo app on http://127.0.0.1:{args.port}")
    print("Press Ctrl+C to stop it.")

    # Loopback only, deliberately. This app reads local files and can spend a
    # Groq key, so it has no business being reachable from the network.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())