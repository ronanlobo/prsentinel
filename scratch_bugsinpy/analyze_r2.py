#!/usr/bin/env python3
"""BugsInPy Stage-1 scan: R1 (which bugs fit), R2 (helper count), R3 (deps).

One project per invocation. Reads only metadata (bug_patch.txt, bug.info,
requirements.txt) plus the project's own git history, fetched shallowly by
commit SHA. Nothing is installed, nothing is executed from the project.

R1  Patch touches exactly one .py file; the AST of that file at the buggy
    commit and at the fixed commit differs in exactly one top-level function
    and in nothing else (imports, module-level constants/code, classes and
    every other top-level function must be identical).

R2  Project-defined helpers the changed function needs, copied verbatim:
      same-file   - top-level functions/classes in the same file, transitive;
      cross-module- names imported from other project modules (relative or
                    project-absolute) and used by the changed function or its
                    same-file helpers, plus those names' own helpers,
                    transitively across modules (decorators included).
    Module-level constants, stdlib imports, third-party imports, methods and
    class-hierarchy dependencies are not counted.

R3  Packages listed in the bug's requirements.txt, blocked only on the heavy
    list (numpy, scipy, pandas, tensorflow, keras, matplotlib, spacy and
    compiled-extension packages). FINAL freeze rule (2026-10-26), two dated
    refinements: (1) byte-identical in >=3 bugs AND >=10 packages imported
    nowhere in the project; (2) added after scanning fastapi, before any
    generation results: >=50 such packages even if the file is unique to one
    bug. When either holds, R3 is judged from run_test.sh and the test file's
    imports instead (module level plus lazy imports in the selected test).

Licence  Prints the licence file path and its first 8 lines, plus a GUESS
         that is only a suggestion. FINAL policy: GPL/AGPL excluded;
         MPL/LGPL excluded and recorded (tqdm ruled out 2026-10-26).

Usage:
    python analyze_r2.py <project> [--append] [--r1-only]
    python analyze_r2.py --funnel [--append]

--append writes the project section to notes/bugsinpy_scan.md (real newlines).
--r1-only scans R1 plus the R3-blocking package and skips R2 (used for the
projects that R3 blocks outright).
--funnel reads scratch_bugsinpy/results/*.json and writes the 501-bug funnel.
"""

import ast
import json
import re
import subprocess
import sys
import warnings
from pathlib import Path

# Old project sources (2019-era youtube-dl etc.) contain invalid escape
# sequences. Python 3.13 warns on every ast.parse; the warnings are noise here.
warnings.filterwarnings("ignore", category=SyntaxWarning)

SCRATCH = Path(__file__).parent
BUGSINPY_META = SCRATCH / "bugsinpy_meta"
PROJECT_REPOS = SCRATCH / "project_repos"
NOTES = SCRATCH.parent / "notes" / "bugsinpy_scan.md"
RESULTS = SCRATCH / "results"

ORDER = [
    "youtube-dl",
    "PySnooper",
    "tornado",
    "tqdm",
    "cookiecutter",
    "fastapi",
    "black",
    "scrapy",
    "thefuck",
    "pandas",
    "keras",
    "ansible",
    "matplotlib",
    "luigi",
    "sanic",
    "spacy",
    "httpie",
]

REPO_URLS = {
    "youtube-dl": "https://github.com/ytdl-org/youtube-dl",
    "PySnooper": "https://github.com/cool-RR/PySnooper",
    "tornado": "https://github.com/tornadoweb/tornado",
    "tqdm": "https://github.com/tqdm/tqdm",
    "cookiecutter": "https://github.com/cookiecutter/cookiecutter",
    "fastapi": "https://github.com/tiangolo/fastapi",
    "black": "https://github.com/psf/black",
    "scrapy": "https://github.com/scrapy/scrapy",
    "thefuck": "https://github.com/nvbn/thefuck",
    "pandas": "https://github.com/pandas-dev/pandas",
    "keras": "https://github.com/keras-team/keras",
    "matplotlib": "https://github.com/matplotlib/matplotlib",
    "scipy": "https://github.com/scipy/scipy",
    "ansible": "https://github.com/ansible/ansible",
    "luigi": "https://github.com/spotify/luigi",
    "sanic": "https://github.com/sanic-org/sanic",
    "spacy": "https://github.com/explosion/spaCy",
    "httpie": "https://github.com/httpie/httpie",
}

# ---------------------------------------------------------------------------
# R3 configuration
# ---------------------------------------------------------------------------

HEAVY = {
    "numpy": "numpy",
    "scipy": "scipy",
    "pandas": "pandas",
    "tensorflow": "tensorflow",
    "tensorflow-gpu": "tensorflow",
    "keras": "keras",
    "matplotlib": "matplotlib",
    "spacy": "spacy",
}

COMPILED_EXTENSION = {
    "lxml": "lxml",
    "cryptography": "cryptography (C ext)",
    "cffi": "cffi (C ext)",
    "gevent": "gevent (C ext)",
    "greenlet": "greenlet (C ext)",
    "psycopg2": "psycopg2 (C ext)",
    "psycopg2-binary": "psycopg2 (C ext)",
    "mysqlclient": "mysqlclient (C ext)",
    "mysqldb": "MySQL-python (C ext)",
    "pymssql": "pymssql (C ext)",
    "pycurl": "pycurl (C ext)",
    "ujson": "ujson (C ext)",
    "orjson": "orjson (C ext)",
    "uvloop": "uvloop (C ext)",
    "httptools": "httptools (C ext)",
    "pyzmq": "pyzmq (C ext)",
    "h5py": "h5py (C ext)",
    "tables": "tables (C ext)",
    "numba": "numba (C ext)",
    "llvmlite": "llvmlite (C ext)",
    "pyarrow": "pyarrow (C ext)",
    "scikit-learn": "scikit-learn (C ext)",
    "sklearn": "scikit-learn (C ext)",
    "scikit-image": "scikit-image (C ext)",
    "opencv-python": "opencv-python (C ext)",
    "opencv-contrib-python": "opencv-python (C ext)",
    "pillow": "Pillow (C ext)",
    "shapely": "shapely (C ext)",
    "geopandas": "geopandas (C ext)",
    "rasterio": "rasterio (C ext)",
    "pyproj": "pyproj (C ext)",
    "cartopy": "cartopy (C ext)",
    "netcdf4": "netCDF4 (C ext)",
    "torch": "torch (C ext)",
    "torchvision": "torchvision (C ext)",
    "jax": "jax (C ext)",
    "jaxlib": "jaxlib (C ext)",
    "mxnet": "mxnet (C ext)",
    "theano": "Theano (C ext)",
    "onnx": "onnx (C ext)",
    "onnxruntime": "onnxruntime (C ext)",
    "openvino": "openvino (C ext)",
    "ta-lib": "TA-Lib (C ext)",
    "pycrypto": "pycrypto (C ext)",
    "pycryptodome": "pycryptodome (C ext)",
}

# The frozen wording also names scrapy. The current decision puts scrapy in the
# main order, so scrapy is NOT in HEAVY here. Flagged in the output instead.
SCROXY_NOTE = "scrapy"

HEAVY_ALL = {}
HEAVY_ALL.update(HEAVY)
HEAVY_ALL.update(COMPILED_EXTENSION)

LICENCE_NAMES = {
    "LICENSE",
    "LICENCE",
    "COPYING",
    "LICENSE.TXT",
    "LICENCE.TXT",
    "COPYING.TXT",
    "LICENSE.MD",
    "LICENCE.MD",
    "COPYING.MD",
}

# FINAL licence policy (owner ruling, 2026-10-26): these families are excluded.
# tqdm keeps an explicit dated ruling because its file is dual MIT + MPL-2.0.
LICENCE_POLICY = {
    "GPL": "GPL",
    "AGPL": "AGPL",
    "MPL": "MPL/LGPL",
    "LGPL": "MPL/LGPL",
}

LICENCE_RULINGS = {
    "tqdm": {
        "date": "2026-10-26",
        "licence": "MPL-2.0, dual-licensed with MIT",
        "verdict": "excluded",
        "reason": (
            "Owner ruled MPL-2.0 unacceptable for this scan, "
            "despite the MIT option"
        ),
    },
}


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------


def read_text_any(path):
    """Read a metadata/licence file whatever encoding PowerShell wrote it in."""
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def run(cmd, cwd=None):
    try:
        res = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return res.returncode, res.stdout, res.stderr
    except Exception as exc:  # pragma: no cover
        return -1, "", str(exc)


def git(repo, *args):
    return run(["git"] + list(args), cwd=str(repo))


def have_commit(repo, sha):
    code, _out, _err = git(repo, "cat-file", "-e", sha + "^{commit}")
    return code == 0


def ensure_commits(repo, shas):
    missing = [s for s in dict.fromkeys(shas) if s and not have_commit(repo, s)]
    if not missing:
        return
    code, _out, err = git(repo, "fetch", "--depth", "1", "origin", *missing)
    if code == 0:
        return
    for sha in missing:
        code, _out, err = git(repo, "fetch", "--depth", "1", "origin", sha)
        if code != 0:
            sys.exit("git fetch of " + sha + " failed: " + err.strip())


def resolve_short_sha(repo, sha, fixed_sha):
    """Resolve an abbreviated buggy SHA from the fixed commit's history.

    pandas' bug.info stores 7-character buggy SHAs. The buggy commit is the
    fixed commit's parent in the sampled bugs, so deepen the fixed commit
    until git can resolve the abbreviation.
    """
    if len(sha) >= 40:
        return sha
    code, out, _err = git(repo, "rev-parse", sha + "^{commit}")
    if code == 0:
        return out.strip()
    for depth in (2, 50, 500):
        git(repo, "fetch", "--depth", str(depth), "origin", fixed_sha)
        code, out, _err = git(repo, "rev-parse", sha + "^{commit}")
        if code == 0:
            return out.strip()
    sys.exit(
        "cannot resolve abbreviated commit "
        + sha
        + " near fixed commit "
        + fixed_sha
    )


def show_file(repo, sha, path):
    code, out, _err = git(repo, "show", sha + ":" + path)
    if code != 0:
        return None
    return out


def ensure_meta():
    if (BUGSINPY_META / "projects").exists():
        return
    code, _out, err = run(
        ["git", "clone", "--depth", "1", "https://github.com/soarsmu/bugsinpy", str(BUGSINPY_META)]
    )
    if code != 0:
        sys.exit("failed to clone bugsinpy metadata: " + err.strip())


def ensure_repo(project):
    repo = PROJECT_REPOS / project
    if repo.exists():
        return repo
    url = REPO_URLS.get(project)
    if url is None:
        sys.exit("no repository url known for " + project)
    code, _out, err = run(["git", "clone", "--depth", "1", url, str(repo)])
    if code != 0:
        sys.exit("failed to clone " + project + ": " + err.strip())
    return repo


def bug_info(text):
    out = {}
    for key in ("python_version", "buggy_commit_id", "fixed_commit_id", "test_file"):
        match = re.search(key + r"\s*=\s*\"([^\"]*)\"", text)
        if match:
            out[key] = match.group(1)
    return out


# ---------------------------------------------------------------------------
# patch parsing
# ---------------------------------------------------------------------------


def patch_py_files(patch):
    """Every .py path the patch touches (both sides of a rename)."""
    paths = []
    for match in re.finditer(r"^diff --git a/(\S+) b/(\S+)$", patch, re.M):
        a, b = match.group(1), match.group(2)
        for side in (b, a):
            if side.endswith(".py") and side != "/dev/null":
                if side not in paths:
                    paths.append(side)
    return paths


def patch_changed_path(patch):
    """The single .py path a patch changes, or None."""
    files = patch_py_files(patch)
    return files[0] if len(files) == 1 else None


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def top_level_maps(tree):
    funcs = {}
    classes = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs[node.name] = node
        elif isinstance(node, ast.ClassDef):
            classes[node.name] = node
    return funcs, classes


def import_signature(tree):
    """Canonical, ordered signature of the module's import statements."""
    sig = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            sig.append(("import", tuple((a.name, a.asname) for a in node.names)))
        elif isinstance(node, ast.ImportFrom):
            sig.append(
                ("from", node.level, node.module, tuple((a.name, a.asname) for a in node.names))
            )
    return sig


def module_level_other(tree):
    """Canonical AST dump of module-level statements that are not imports/defs."""
    out = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        out.append(ast.dump(node))
    return out


def r1_check(buggy_src, fixed_src):
    """Return (verdict, changed_function_names, reasons_list)."""
    try:
        buggy = ast.parse(buggy_src)
    except SyntaxError as exc:
        return False, [], ["buggy parse error: " + str(exc)]
    try:
        fixed = ast.parse(fixed_src)
    except SyntaxError as exc:
        return False, [], ["fixed parse error: " + str(exc)]

    reasons = []

    if import_signature(buggy) != import_signature(fixed):
        reasons.append("imports changed")

    if module_level_other(buggy) != module_level_other(fixed):
        reasons.append("module-level code changed")

    bfuncs, bclasses = top_level_maps(buggy)
    ffuncs, fclasses = top_level_maps(fixed)

    class_names = set(bclasses) | set(fclasses)
    changed_classes = []
    for name in sorted(class_names):
        if name not in bclasses or name not in fclasses:
            changed_classes.append(name)
        elif ast.dump(bclasses[name]) != ast.dump(fclasses[name]):
            changed_classes.append(name)
    if changed_classes:
        reasons.append("class body changed (" + ", ".join(changed_classes) + ")")

    func_names = set(bfuncs) | set(ffuncs)
    changed_funcs = []
    for name in sorted(func_names):
        if name not in bfuncs or name not in ffuncs:
            changed_funcs.append(name)
        elif ast.dump(bfuncs[name]) != ast.dump(ffuncs[name]):
            changed_funcs.append(name)
    if len(changed_funcs) != 1:
        reasons.append(str(len(changed_funcs)) + " functions changed (" + ", ".join(changed_funcs) + ")")

    if reasons:
        return False, changed_funcs, reasons
    return True, changed_funcs, []


def local_names(node):
    bound = set()
    for sub in ast.walk(node):
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(sub.name)
        elif isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
            bound.add(sub.id)
        elif isinstance(sub, ast.arg):
            bound.add(sub.arg)
        elif isinstance(sub, ast.ExceptHandler) and sub.name:
            bound.add(sub.name)
        elif isinstance(sub, ast.Import):
            for alias in sub.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(sub, ast.ImportFrom):
            for alias in sub.names:
                bound.add(alias.asname or alias.name)
    return bound


def referenced_names(node):
    bound = local_names(node)
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            if sub.id not in bound:
                names.add(sub.id)
    return names


def module_constants(tree):
    constants = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            constants.add(node.target.id)
    return constants


def same_file_helpers(tree, start_name):
    funcs, classes = top_level_maps(tree)
    constants = module_constants(tree)
    helpers = set()
    seen = set()
    queue = [start_name]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        node = funcs.get(current)
        if node is None:
            continue
        for name in referenced_names(node):
            if name == start_name or name in constants:
                continue
            if name in funcs and name not in seen:
                helpers.add(name)
                queue.append(name)
            elif name in classes:
                helpers.add(name)
    return sorted(helpers)


def module_import_map(tree):
    """local name -> (level, module, original name)."""
    imports = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    imports[alias.asname] = (0, alias.name, alias.name.split(".")[-1])
                else:
                    top = alias.name.split(".")[0]
                    imports[top] = (0, top, top)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports[alias.asname or alias.name] = (
                    node.level,
                    node.module or "",
                    alias.name,
                )
    return imports


def resolve_project_module(file_path, level, module):
    """Repo-relative module path for a project import, or None."""
    parts = list(Path(file_path).with_suffix("").parts)
    pkg = parts[:-1]
    if level == 0:
        if not module:
            return None
        mod_parts = module.split(".")
        if pkg and mod_parts[0] == pkg[0]:
            return "/".join(mod_parts)
        if not pkg:
            return "/".join(mod_parts)
        return None
    base = list(pkg)
    for _ in range(level - 1):
        if not base:
            return None
        base.pop()
    if module:
        base.extend(module.split("."))
    return "/".join(base)


def module_candidates(modpath):
    return [modpath + ".py", modpath + "/__init__.py"]


def cross_module_helpers(repo, fixed_sha, file_path, fixed_tree, start_name, same_helpers):
    """Names imported from other project modules and used by the function."""
    imports = module_import_map(fixed_tree)
    funcs, _classes = top_level_maps(fixed_tree)
    used = set()
    for name in [start_name] + list(same_helpers):
        node = funcs.get(name)
        if node is not None:
            used |= referenced_names(node)
    found = []
    not_counted = []
    for name in sorted(used):
        if name not in imports:
            continue
        level, module, original = imports[name]
        modpath = resolve_project_module(file_path, level, module)
        if modpath is None:
            continue
        target_path = None
        target_src = None
        for cand in module_candidates(modpath):
            src = show_file(repo, fixed_sha, cand)
            if src is not None:
                target_path = cand
                target_src = src
                break
        if target_src is None:
            continue
        try:
            target_tree = ast.parse(target_src)
        except SyntaxError:
            continue
        tfuncs, tclasses = top_level_maps(target_tree)
        if original in tfuncs or original in tclasses:
            found.append(name + " <- " + target_path + ":" + original)
        else:
            constants = module_constants(target_tree)
            if original in constants:
                not_counted.append(name + " <- " + target_path + " (module-level constant/alias)")
            else:
                not_counted.append(name + " <- " + target_path + " (not a project function/class)")
    return sorted(found), sorted(not_counted)


def collect_helpers(repo, sha, file_path, tree, start_name):
    """Transitive closure of project-defined helpers across modules.

    Same-file helpers are those defined in the changed file; every other
    helper is cross-module. Decorators are children of the function node, so
    decorator names (including decorator factories such as for_app and
    git_support) are followed like any other reference, and a helper's own
    helpers are followed transitively, module to module.
    """
    module_cache = {}

    def get_module(path):
        if path in module_cache:
            return module_cache[path]
        if path == file_path:
            src_tree = tree
        else:
            src = show_file(repo, sha, path)
            if src is None:
                module_cache[path] = None
                return None
            try:
                src_tree = ast.parse(src)
            except SyntaxError:
                module_cache[path] = None
                return None
        funcs, classes = top_level_maps(src_tree)
        module_cache[path] = {
            "funcs": funcs,
            "classes": classes,
            "constants": module_constants(src_tree),
            "imports": module_import_map(src_tree),
        }
        return module_cache[path]

    def resolve(path, name):
        mod = get_module(path)
        if mod is None or name not in mod["imports"]:
            return None
        level, module, original = mod["imports"][name]
        modpath = resolve_project_module(path, level, module)
        if modpath is None:
            return None
        for candidate in module_candidates(modpath):
            target = get_module(candidate)
            if target is None:
                continue
            if original in target["funcs"]:
                return candidate, original, "function"
            if original in target["classes"]:
                return candidate, original, "class"
            if original in target["constants"]:
                return candidate, original, "constant"
            return candidate, original, "other"
        return None

    same = set()
    cross = {}
    not_counted = set()
    seen = set()
    queue = [(file_path, start_name)]
    while queue:
        path, name = queue.pop(0)
        if (path, name) in seen:
            continue
        seen.add((path, name))
        mod = get_module(path)
        if mod is None:
            continue
        node = mod["funcs"].get(name)
        if node is None:
            # A class helper is copied as one unit; methods are not counted.
            continue
        for ref in sorted(referenced_names(node)):
            if (path, ref) == (file_path, start_name):
                continue
            if ref in mod["constants"]:
                continue
            if ref in mod["funcs"] or ref in mod["classes"]:
                kind = "function" if ref in mod["funcs"] else "class"
                if path == file_path:
                    same.add(ref)
                else:
                    cross[(path, ref)] = ref + " <- " + path + ":" + ref
                if kind == "function":
                    queue.append((path, ref))
                continue
            resolved = resolve(path, ref)
            if resolved is None:
                continue
            target_path, original, kind = resolved
            if kind == "constant":
                not_counted.add(
                    ref + " <- " + target_path + " (module-level constant/alias)"
                )
                continue
            if kind == "other":
                not_counted.add(
                    ref + " <- " + target_path + " (not a project function/class)"
                )
                continue
            if target_path == file_path:
                same.add(original)
            else:
                cross[(target_path, original)] = (
                    ref + " <- " + target_path + ":" + original
                )
            if kind == "function":
                queue.append((target_path, original))
    return sorted(same), sorted(cross.values()), sorted(not_counted)


# ---------------------------------------------------------------------------
# requirements / licence
# ---------------------------------------------------------------------------


def parse_requirements(text):
    names = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        line = line.split(";", 1)[0].strip()
        match = re.match(r"([A-Za-z0-9][A-Za-z0-9_.\-]*)", line)
        if not match:
            continue
        name = match.group(1)
        if name and name not in names:
            names.append(name)
    return names


def normalize_pkg(name):
    return name.lower().replace("_", "-")


def heavy_hits(packages):
    hits = []
    for pkg in packages:
        norm = normalize_pkg(pkg)
        if norm in HEAVY_ALL:
            hits.append(pkg + " (" + HEAVY_ALL[norm] + ")")
    return hits


# ---------------------------------------------------------------------------
# R3 amendment (2026-10-26): environment-freeze detection
#
# Some BugsInPy bug directories ship a byte-identical `pip freeze` of a whole
# container image instead of the project's own dependencies. Such a file is
# identified by (a) being byte-identical in at least 3 bugs of the project and
# (b) listing at least 10 packages that no Python file in the project imports.
# For those bugs R3 is judged from run_test.sh and the test file's imports.
# ---------------------------------------------------------------------------

_IMPORT_CACHE = {}
_TOPNAME_CACHE = {}


def module_imports_from_src(src):
    """Top-level module names imported by a source text (any nesting)."""
    names = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return names
    return import_names_in_node(tree)


def import_names_in_node(node):
    """Top-level module names imported anywhere under an AST node."""
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Import):
            for alias in sub.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(sub, ast.ImportFrom):
            if sub.level == 0 and sub.module:
                names.add(sub.module.split(".")[0])
    return names


def module_level_import_names(tree):
    """Imports that run when the module is imported (not inside functions)."""
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def test_target_names(cmd):
    """Test function names named in run_test.sh."""
    names = [m.group(1) for m in re.finditer(r"::([A-Za-z_]\w*)", cmd)]
    if not names and cmd:
        match = re.search(r"\.([A-Za-z_]\w*)\s*$", cmd.strip().splitlines()[-1])
        if match:
            names.append(match.group(1))
    return names


def is_project_local(repo, sha, test_file, name, project_top):
    if normalize_pkg(name) in project_top:
        return True
    parent = Path(test_file).parent.as_posix()
    base = "" if parent == "." else parent
    for candidate in (name + ".py", name + "/__init__.py"):
        path = (base + "/" + candidate) if base else candidate
        if show_file(repo, sha, path) is not None:
            return True
    return False


def project_imported_modules(repo, sha):
    """Every top-level module imported anywhere in the project at a commit."""
    if sha in _IMPORT_CACHE:
        return _IMPORT_CACHE[sha]
    code, out, _err = git(
        repo, "grep", "-h", "-E", r"^[ \t]*(from|import)[ \t]+", sha, "--", "*.py"
    )
    names = set()
    if code == 0:
        for line in out.splitlines():
            line = line.strip()
            match = re.match(r"from\s+([A-Za-z_][A-Za-z0-9_.]*)\s+import\b", line)
            if match:
                names.add(match.group(1).split(".")[0])
                continue
            match = re.match(r"import\s+([A-Za-z_][A-Za-z0-9_., ]*)", line)
            if match:
                for part in match.group(1).split(","):
                    part = part.strip().split(" ")[0]
                    if part:
                        names.add(part.split(".")[0])
    _IMPORT_CACHE[sha] = names
    return names


def project_top_names(repo, sha):
    """Top-level directory names and single-file module names at a commit."""
    if sha in _TOPNAME_CACHE:
        return _TOPNAME_CACHE[sha]
    code, out, _err = git(repo, "ls-tree", "--name-only", sha)
    names = set()
    if code == 0:
        for line in out.splitlines():
            name = line.strip().rstrip("/")
            if not name:
                continue
            if name.endswith(".py"):
                name = name[:-3]
            names.add(normalize_pkg(name))
    _TOPNAME_CACHE[sha] = names
    return names


def requirement_groups(bug_dirs):
    """Stripped requirements.txt text -> list of bug ids sharing it."""
    groups = {}
    for bugdir in bug_dirs:
        req = bugdir / "requirements.txt"
        if not req.exists():
            continue
        text = read_text_any(req).strip()
        if not text:
            continue
        groups.setdefault(text, []).append(bugdir.name)
    return groups


def freeze_evidence(repo, sha, packages, group):
    """Evidence that a requirements file is an environment freeze, or None."""
    if not packages:
        return None
    imported = project_imported_modules(repo, sha)
    norm_imported = {normalize_pkg(name) for name in imported}
    unrelated = [pkg for pkg in packages if normalize_pkg(pkg) not in norm_imported]
    shared = len(group) >= 3 and len(unrelated) >= 10
    unmistakable = len(unrelated) >= 50
    if not (shared or unmistakable):
        return None
    return {
        "group": list(group),
        "unrelated": unrelated,
        "total": len(packages),
        "shared": shared,
    }


def r3_from_tests(repo, sha, info, cmd):
    """Judge R3 from the bug's test file(s). Returns (evaluated, hits, imports, files)."""
    raw_files = info.get("test_file", "")
    test_files = [part.strip() for part in re.split(r"[;,]", raw_files) if part.strip()]
    targets = set(test_target_names(cmd))
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    names = set()
    readable = []
    used_sha = sha
    for test_file in test_files:
        src = None
        for candidate_sha in (sha, info.get("buggy_commit_id", "")):
            if candidate_sha:
                src = show_file(repo, candidate_sha, test_file)
                if src is not None:
                    used_sha = candidate_sha
                    break
        if src is None:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        readable.append(test_file)
        # Only imports that actually run: module level, plus lazy imports
        # inside the test function(s) named in run_test.sh.
        names |= module_level_import_names(tree)
        if targets:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in targets:
                    names |= import_names_in_node(node)
    if not readable:
        return False, [], [], raw_files
    project = project_top_names(repo, used_sha)
    third_party = []
    for name in sorted(names):
        if name in stdlib:
            continue
        if any(is_project_local(repo, used_sha, test_file, name, project) for test_file in readable):
            continue
        third_party.append(name)
    return True, heavy_hits(third_party), third_party, ";".join(readable)


def find_licence(repo):
    try:
        entries = list(repo.iterdir())
    except Exception:
        return None
    for path in sorted(entries, key=lambda p: p.name):
        if path.is_file() and path.name.upper() in LICENCE_NAMES:
            return path
    # Some projects keep the text in a LICENSE/ directory.
    for path in sorted(entries, key=lambda p: p.name):
        if path.is_dir() and path.name.upper() in LICENCE_NAMES:
            try:
                children = sorted(path.iterdir(), key=lambda p: p.name)
            except Exception:
                continue
            for child in children:
                if child.is_file() and (
                    child.name.upper() in LICENCE_NAMES
                    or child.name.upper().startswith("LICENSE")
                    or child.name.upper().startswith("COPYING")
                ):
                    return child
    return None


def licence_guess(text):
    low = text.lower()
    head = "\n".join(text.splitlines()[:20]).lower()
    if "affero" in head:
        return "AGPL", "exclude"
    if "gnu lesser general public license" in low or "gnu library general public license" in low:
        return "LGPL", "flag"
    if "gnu general public license" in head or re.search(r"\bgpl\b", head):
        return "GPL", "exclude"
    if "mozilla public license" in low:
        return "MPL", "flag"
    if "apache license" in low:
        return "Apache-2.0", "ok"
    if "mit license" in low or "permission is hereby granted, free of charge" in low:
        return "MIT", "ok"
    if "redistribution and use in source and binary forms" in low:
        return "BSD", "ok"
    if "public domain" in low or "unlicense" in low:
        return "Public domain (Unlicense)", "ok"
    if "python software foundation" in low:
        return "PSF", "ok"
    if "license agreement for matplotlib" in head or "matplotlib development team" in low:
        return "Matplotlib (PSF-based)", "ok"
    return "unknown", "flag"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def save_result(project, mode, licence_path, guess, licence_excluded, bug_records):
    """Persist one project's per-bug record for the 501-bug funnel."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    stage = None
    if licence_excluded is not None:
        stage = (
            "pre"
            if licence_excluded.get("date") == "standing policy"
            else "post"
        )
    payload = {
        "project": project,
        "mode": mode,
        "licence": {
            "path": str(licence_path) if licence_path is not None else None,
            "guess": guess,
            "excluded": licence_excluded is not None,
            "stage": stage,
            "detail": licence_excluded,
        },
        "bugs": bug_records,
    }
    (RESULTS / (project + ".json")).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def r1_reason_group(reason):
    """First failing R1 check, as a stable funnel category."""
    if reason.startswith("no .py file"):
        return "patch touches no .py file"
    if reason.startswith("multi-file"):
        return "multi-file patch"
    if reason.startswith("imports changed"):
        return "imports changed"
    if reason.startswith("module-level code changed"):
        return "module-level code changed"
    if reason.startswith("class body changed"):
        return "class body changed"
    if "functions changed (" in reason:
        return "not exactly one function changed"
    if "parse error" in reason:
        return "parse error"
    if "missing" in reason:
        return "missing file/commit metadata"
    return reason


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = list(sys.argv[1:])
    append = "--append" in args
    r1_only = "--r1-only" in args
    funnel = "--funnel" in args
    clarifications = "--clarifications" in args
    args = [
        a
        for a in args
        if a not in ("--append", "--r1-only", "--funnel", "--clarifications")
    ]
    if funnel:
        write_funnel(append)
        return
    if clarifications:
        write_clarifications(append)
        return
    if len(args) != 1:
        sys.exit(
            "usage: analyze_r2.py <project> [--append] [--r1-only] | --funnel [--append] | --clarifications [--append]"
        )
    project = args[0]

    ensure_meta()
    meta_project = BUGSINPY_META / "projects" / project
    if not meta_project.exists():
        sys.exit("no metadata for " + project)
    repo = ensure_repo(project)

    bug_dirs = sorted(
        [d for d in (meta_project / "bugs").iterdir() if d.is_dir() and d.name.isdigit()],
        key=lambda d: int(d.name),
    )

    head_code, head_sha, _ = git(repo, "rev-parse", "HEAD")
    head_sha = head_sha.strip() if head_code == 0 else "unknown"

    print("=== PROJECT: " + project + " ===")
    print("repo: " + str(repo))
    print("licence source commit (HEAD): " + head_sha)
    licence_path = find_licence(repo)
    guess = "unknown"
    action = "flag"
    if licence_path is None:
        print("licence file: NONE FOUND")
        print("licence guess (suggestion only): unknown")
    else:
        text = read_text_any(licence_path)
        guess, action = licence_guess(text)
        print("licence file: " + str(licence_path))
        print("licence first 8 lines:")
        for line in text.splitlines()[:8]:
            print("    " + line)
        shown_action = (
            "excluded"
            if (guess in LICENCE_POLICY or project in LICENCE_RULINGS)
            else action
        )
        print(
            "licence guess (suggestion only): "
            + guess
            + "  [action: "
            + shown_action
            + "]"
        )

    ruling = LICENCE_RULINGS.get(project)
    licence_excluded = None
    if ruling is not None and ruling["verdict"] == "excluded":
        licence_excluded = ruling
        print(
            "licence ruling ("
            + ruling["date"]
            + "): EXCLUDED - "
            + ruling["licence"]
            + "; "
            + ruling["reason"]
        )
    elif guess in LICENCE_POLICY:
        licence_excluded = {
            "date": "standing policy",
            "licence": guess,
            "verdict": "excluded",
            "reason": "excluded by the final licence policy ("
            + LICENCE_POLICY[guess]
            + ")",
        }
        print(
            "licence policy: EXCLUDED - "
            + guess
            + " ("
            + LICENCE_POLICY[guess]
            + ")"
        )
    print("bugs in metadata: " + str(len(bug_dirs)))
    print("")

    # ---------------- R1 over every bug ----------------
    print("--- R1: all bugs (one .py file; exactly one top-level function; rest identical) ---")
    r1_rows = []
    skipped = []
    for bugdir in bug_dirs:
        bid = bugdir.name
        patch_path = bugdir / "bug_patch.txt"
        info_path = bugdir / "bug.info"
        if not patch_path.exists() or not info_path.exists():
            skipped.append((bid, "missing bug_patch.txt or bug.info"))
            print("bug " + bid + ": SKIPPED (missing bug_patch.txt or bug.info)")
            continue
        patch = read_text_any(patch_path)
        info = bug_info(read_text_any(info_path))

        files = patch_py_files(patch)
        if len(files) != 1:
            reason = (
                "no .py file in patch"
                if len(files) == 0
                else "multi-file (" + str(len(files)) + " .py files: " + ", ".join(files) + ")"
            )
            print("bug " + bid + ": EXCLUDED  " + reason)
            r1_rows.append((bid, False, None, reason, info))
            continue

        path = files[0]
        if "buggy_commit_id" not in info or "fixed_commit_id" not in info:
            reason = "bug.info missing commit ids"
            print("bug " + bid + ": EXCLUDED  " + reason)
            r1_rows.append((bid, False, None, reason, info))
            continue

        buggy_sha = info["buggy_commit_id"]
        fixed_sha = info["fixed_commit_id"]
        buggy_sha = resolve_short_sha(repo, buggy_sha, fixed_sha)
        ensure_commits(repo, [buggy_sha, fixed_sha])

        buggy_src = show_file(repo, buggy_sha, path)
        if buggy_src is None:
            reason = "file " + path + " missing at buggy commit"
            print("bug " + bid + ": EXCLUDED  " + reason)
            r1_rows.append((bid, False, None, reason, info))
            continue
        fixed_src = show_file(repo, fixed_sha, path)
        if fixed_src is None:
            reason = "file " + path + " missing at fixed commit"
            print("bug " + bid + ": EXCLUDED  " + reason)
            r1_rows.append((bid, False, None, reason, info))
            continue

        ok, changed_funcs, reasons = r1_check(buggy_src, fixed_src)
        func = changed_funcs[0] if len(changed_funcs) == 1 else ""
        if ok:
            print("bug " + bid + ": PASS  function=" + func + "  file=" + path)
            r1_rows.append((bid, True, func, "", info))
        else:
            reason = "; ".join(reasons)
            shown = ("  function=" + func) if func else ""
            print("bug " + bid + ": EXCLUDED  " + reason + shown + "  file=" + path)
            r1_rows.append((bid, False, func, reason, info))

    passed = [r for r in r1_rows if r[1]]
    excluded = [r for r in r1_rows if not r[1]]
    print("")
    print("R1 counts for " + project + ": total=" + str(len(bug_dirs)) + " pass=" + str(len(passed)) + " excluded=" + str(len(excluded)) + " skipped=" + str(len(skipped)))
    reason_counts = {}
    for row in excluded:
        key = row[3]
        if key.startswith("multi-file"):
            key = "multi-file"
        elif key.startswith("class body"):
            key = "class body"
        elif key.endswith("functions changed ("):
            key = "function count"
        reason_counts[key] = reason_counts.get(key, 0) + 1
    for key in sorted(reason_counts):
        print("    " + key + ": " + str(reason_counts[key]))
    print("")

    # ---------------- R1-only: R3 rule; R2 only if R3 does not block ----------------
    if r1_only:
        print("--- R3 (frozen rule) for R1 survivors; R2 only where R3 does not block ---")
        req_groups = requirement_groups(bug_dirs)
        r3_rows = []
        for bid, _ok, func, _reason, info in passed:
            bugdir = meta_project / "bugs" / bid
            patch = read_text_any(bugdir / "bug_patch.txt")
            path = patch_changed_path(patch)
            fixed_sha = info["fixed_commit_id"]
            req_path = bugdir / "requirements.txt"
            req_text = read_text_any(req_path) if req_path.exists() else ""
            packages = parse_requirements(req_text)
            group = req_groups.get(req_text.strip(), [bid]) if req_text.strip() else []
            freeze = freeze_evidence(repo, fixed_sha, packages, group)

            test_cmd = ""
            test_imports = []
            test_file = ""
            basis = "requirements.txt"
            fallback_note = ""
            if not packages:
                # Metadata gap: an empty requirements.txt is not evidence of no
                # heavy dependencies. Use the same evidence source as the freeze
                # amendment (the selected test's imports) instead of a free pass.
                basis = "run_test.sh (requirements.txt empty)"
                cmd_path = bugdir / "run_test.sh"
                if cmd_path.exists():
                    test_cmd = read_text_any(cmd_path).strip()
                evaluated, hits, test_imports, test_file = r3_from_tests(
                    repo, fixed_sha, info, test_cmd
                )
                if not evaluated:
                    basis = "requirements.txt (empty)"
                    hits = []
                    fallback_note = (
                        "requirements.txt empty and test file(s) unreadable; R3 cannot block"
                    )
            elif freeze is not None:
                basis = "run_test.sh"
                cmd_path = bugdir / "run_test.sh"
                if cmd_path.exists():
                    test_cmd = read_text_any(cmd_path).strip()
                evaluated, hits, test_imports, test_file = r3_from_tests(
                    repo, fixed_sha, info, test_cmd
                )
                if not evaluated:
                    basis = "requirements.txt"
                    freeze = None
                    hits = heavy_hits(packages)
                    fallback_note = (
                        "test file(s) unreadable; fell back to requirements.txt"
                    )
            else:
                hits = heavy_hits(packages)

            row = {
                "bug": bid,
                "function": func,
                "path": path,
                "packages": packages,
                "hits": hits,
                "basis": basis,
                "freeze": freeze,
                "test_cmd": test_cmd,
                "test_imports": test_imports,
                "test_file": test_file,
                "same": [],
                "cross": [],
                "not_counted": [],
                "r2": None,
                "r2_total": None,
            }
            if not hits:
                fixed_src = show_file(repo, fixed_sha, path)
                fixed_tree = ast.parse(fixed_src)
                same_helpers, cross_helpers, not_counted = collect_helpers(
                    repo, fixed_sha, path, fixed_tree, func
                )
                total = len(same_helpers) + len(cross_helpers)
                row["same"] = same_helpers
                row["cross"] = cross_helpers
                row["not_counted"] = not_counted
                row["r2"] = total <= 3
                row["r2_total"] = total
            r3_rows.append(row)

            print("")
            print("bug " + bid + " | function=" + func + " | file=" + path)
            if freeze is not None:
                if freeze["shared"]:
                    head = (
                        "identical in "
                        + str(len(freeze["group"]))
                        + " bugs ("
                        + ", ".join(sorted(freeze["group"], key=int))
                        + ")"
                    )
                else:
                    head = "unique to this bug, but unmistakable"
                print(
                    "    requirements.txt is an ENVIRONMENT FREEZE: "
                    + head
                    + "; "
                    + str(len(freeze["unrelated"]))
                    + " of "
                    + str(freeze["total"])
                    + " packages are imported nowhere in the project"
                )
                print("    run_test.sh: " + (test_cmd if test_cmd else "(missing)"))
                print(
                    "    test file imports (third-party only): "
                    + str(test_imports)
                    + "  files="
                    + test_file
                )
            elif basis.startswith("run_test.sh"):
                print("    requirements.txt: EMPTY (0 bytes / missing)")
                print("    run_test.sh: " + (test_cmd if test_cmd else "(missing)"))
                print(
                    "    test file imports (third-party only): "
                    + str(test_imports)
                    + "  files="
                    + test_file
                )
            else:
                print(
                    "    requirements.txt: "
                    + (str(packages) if packages else "[] (file missing or empty)")
                )
            if fallback_note:
                print("    note: " + fallback_note)
            print("    R3 basis: " + basis)
            if hits:
                print("    R3: EXCLUDED  blocked by: " + "; ".join(hits))
            else:
                print("    R3: PASS  (no heavy packages)")
                print(
                    "    R2 (evaluated because R3 does not block): same-file="
                    + str(len(row["same"]))
                    + " cross-module="
                    + str(len(row["cross"]))
                    + " total="
                    + str(row["r2_total"])
                    + "  -> "
                    + ("PASS R2 (<=3)" if row["r2"] else "EXCLUDED R2 (>3)")
                )
                if row["same"]:
                    print("        same-file helpers: " + str(row["same"]))
                if row["cross"]:
                    print("        cross-module helpers: " + str(row["cross"]))

        print("")
        blocked = [r for r in r3_rows if r["hits"]]
        r2_evaluated = [r for r in r3_rows if r["r2"] is not None]
        r2_pass = [r for r in r2_evaluated if r["r2"]]
        usable = [
            r
            for r in r2_pass
            if licence_excluded is None
        ]
        print(
            "R1 survivors="
            + str(len(r3_rows))
            + " blocked by R3="
            + str(len(blocked))
            + " R3 pass="
            + str(len(r2_evaluated))
            + " R2 pass="
            + str(len(r2_pass))
        )
        print(
            "usable bugs: "
            + (", ".join(r["bug"] for r in usable) if usable else "none")
            + (" (licence excluded)" if licence_excluded is not None else "")
        )
        print("=== DONE " + project + " (R1-only) ===")

        bug_records = []
        for bid, ok, func, reason, _info in r1_rows:
            rec = {
                "bug": bid,
                "r1": ok,
                "function": func,
                "reason": reason,
                "path": "",
                "r2": None,
                "r3": None,
                "r2_total": None,
                "hits": [],
                "packages": [],
            }
            if ok:
                row = next(r for r in r3_rows if r["bug"] == bid)
                rec["path"] = row["path"]
                rec["packages"] = row["packages"]
                rec["hits"] = row["hits"]
                rec["basis"] = row["basis"]
                rec["r3"] = not bool(row["hits"])
                rec["r2"] = row["r2"]
                rec["r2_total"] = row["r2_total"]
            bug_records.append(rec)
        for bid, reason in skipped:
            bug_records.append(
                {
                    "bug": bid,
                    "r1": False,
                    "function": "",
                    "reason": "skipped: " + reason,
                    "path": "",
                    "r2": None,
                    "r3": None,
                    "r2_total": None,
                    "hits": [],
                    "packages": [],
                }
            )
        save_result(project, "r1", licence_path, guess, licence_excluded, bug_records)
        if append:
            write_notes_r1_only(
                project,
                licence_path,
                licence_guess,
                bug_dirs,
                r1_rows,
                r3_rows,
                licence_excluded,
            )
        return

    # ---------------- R2 / R3 on R1 survivors ----------------
    req_groups = requirement_groups(bug_dirs)
    print("--- R2/R3: R1 survivors ---")
    detail_rows = []
    for bid, _ok, func, _reason, info in passed:
        bugdir = meta_project / "bugs" / bid
        patch = read_text_any(bugdir / "bug_patch.txt")
        path = patch_changed_path(patch)
        fixed_sha = info["fixed_commit_id"]
        fixed_src = show_file(repo, fixed_sha, path)
        fixed_tree = ast.parse(fixed_src)

        same_helpers, cross_helpers, cross_not_counted = collect_helpers(
            repo, fixed_sha, path, fixed_tree, func
        )
        total = len(same_helpers) + len(cross_helpers)

        req_path = bugdir / "requirements.txt"
        req_text = read_text_any(req_path) if req_path.exists() else ""
        packages = parse_requirements(req_text)
        group = req_groups.get(req_text.strip(), [bid]) if req_text.strip() else []
        freeze = freeze_evidence(repo, fixed_sha, packages, group)

        test_cmd = ""
        test_imports = []
        test_file = ""
        fallback_note = ""
        if not packages:
            # Metadata gap: an empty requirements.txt is not evidence of no
            # heavy dependencies. Use the same evidence source as the freeze
            # amendment (the selected test's imports) instead of a free pass.
            basis = "run_test.sh (requirements.txt empty)"
            cmd_path = bugdir / "run_test.sh"
            if cmd_path.exists():
                test_cmd = read_text_any(cmd_path).strip()
            evaluated, hits, test_imports, test_file = r3_from_tests(
                repo, fixed_sha, info, test_cmd
            )
            if not evaluated:
                basis = "requirements.txt (empty)"
                hits = []
                fallback_note = "requirements.txt empty and test file(s) unreadable; R3 cannot block"
        elif freeze is not None:
            basis = "run_test.sh"
            cmd_path = bugdir / "run_test.sh"
            if cmd_path.exists():
                test_cmd = read_text_any(cmd_path).strip()
            evaluated, hits, test_imports, test_file = r3_from_tests(
                repo, fixed_sha, info, test_cmd
            )
            if not evaluated:
                basis = "requirements.txt"
                freeze = None
                hits = heavy_hits(packages)
                fallback_note = "test file(s) unreadable at the fixed/buggy commit; fell back to requirements.txt"
        else:
            basis = "requirements.txt"
            hits = heavy_hits(packages)
        r3_ok = not hits

        print("")
        print("bug " + bid + " | function=" + func + " | file=" + path)
        print("    same-file helpers (" + str(len(same_helpers)) + "): " + str(same_helpers))
        print("    cross-module helpers (" + str(len(cross_helpers)) + "): " + str(cross_helpers))
        for item in cross_not_counted:
            print("        not counted: " + item)
        print("    R2 total helpers: " + str(total) + "  -> " + ("PASS R2 (<=3)" if total <= 3 else "EXCLUDED R2 (>3)"))
        if freeze is not None:
            if freeze["shared"]:
                head = (
                    "identical in "
                    + str(len(freeze["group"]))
                    + " bugs ("
                    + ", ".join(sorted(freeze["group"], key=int))
                    + ")"
                )
            else:
                head = "unique to this bug, but unmistakable"
            print(
                "    requirements.txt is an ENVIRONMENT FREEZE: "
                + head
                + "; "
                + str(len(freeze["unrelated"]))
                + " of "
                + str(freeze["total"])
                + " packages are imported nowhere in the project"
            )
            print("        e.g. " + ", ".join(freeze["unrelated"][:8]))
            print("    run_test.sh: " + (test_cmd if test_cmd else "(missing)"))
            print("    test file imports (third-party only): " + str(test_imports) + "   files=" + str(test_file))
        elif basis.startswith("run_test.sh"):
            print("    requirements.txt: EMPTY (0 bytes / missing)")
            print("    run_test.sh: " + (test_cmd if test_cmd else "(missing)"))
            print("    test file imports (third-party only): " + str(test_imports) + "   files=" + str(test_file))
        else:
            print("    requirements.txt packages: " + (str(packages) if packages else "[] (file missing or empty)"))
        if fallback_note:
            print("    note: " + fallback_note)
        print("    R3 basis: " + basis)
        if hits:
            print("    R3: EXCLUDED  blocked by: " + "; ".join(hits))
        else:
            print("    R3: PASS  (no heavy packages)")
        if any(normalize_pkg(p) == SCROXY_NOTE for p in packages):
            print("    note: requirements.txt lists scrapy; treated as allowed per current decision")

        detail_rows.append(
            {
                "bug": bid,
                "function": func,
                "path": path,
                "same": same_helpers,
                "cross": cross_helpers,
                "not_counted": cross_not_counted,
                "total": total,
                "packages": packages,
                "hits": hits,
                "basis": basis,
                "freeze": freeze,
                "test_cmd": test_cmd,
                "test_imports": test_imports,
                "r2": total <= 3,
                "r3": r3_ok,
                "python_version": info.get("python_version", ""),
                "test_file": info.get("test_file", ""),
            }
        )

    usable = [r for r in detail_rows if r["r2"] and r["r3"]]
    if licence_excluded is not None:
        usable = []
    print("")
    print("R2/R3 counts for " + project + ": R1 survivors=" + str(len(detail_rows)) + " R2 pass=" + str(len([r for r in detail_rows if r['r2']])) + " R3 pass=" + str(len([r for r in detail_rows if r['r3']])) + " usable=" + str(len(usable)) + (" (licence excluded)" if licence_excluded is not None else ""))
    print("usable bugs: " + (", ".join(r["bug"] for r in usable) if usable else "none") + (" (licence excluded)" if licence_excluded is not None else ""))
    print("=== DONE " + project + " ===")

    detail_by_bug = {r["bug"]: r for r in detail_rows}
    bug_records = []
    for bid, ok, func, reason, _info in r1_rows:
        rec = {
            "bug": bid,
            "r1": ok,
            "function": func,
            "reason": reason,
            "path": "",
            "r2": None,
            "r3": None,
            "r2_total": None,
            "hits": [],
            "packages": [],
        }
        if ok:
            row = detail_by_bug[bid]
            rec.update(
                {
                    "path": row["path"],
                    "r2": row["r2"],
                    "r3": row["r3"],
                    "r2_total": row["total"],
                    "hits": row["hits"],
                    "packages": row["packages"],
                    "basis": row["basis"],
                }
            )
        bug_records.append(rec)
    for bid, reason in skipped:
        bug_records.append(
            {
                "bug": bid,
                "r1": False,
                "function": "",
                "reason": "skipped: " + reason,
                "path": "",
                "r2": None,
                "r3": None,
                "r2_total": None,
                "hits": [],
                "packages": [],
            }
        )
    save_result(project, "full", licence_path, guess, licence_excluded, bug_records)

    if append:
        write_notes(project, licence_path, licence_guess, bug_dirs, r1_rows, detail_rows, usable, licence_excluded)


def write_notes_header(handle):
    handle.write("# BugsInPy scan for PRSentinel\n")
    handle.write("\n")
    handle.write("Generated by `scratch_bugsinpy/analyze_r2.py`. Every row below comes from\n")
    handle.write("script output; nothing is hand-written.\n")
    handle.write("\n")
    handle.write("## Rules applied\n")
    handle.write("\n")
    handle.write("- **R1**: the fix patch touches exactly one `.py` file; the AST of that file\n")
    handle.write("  at the buggy commit and at the fixed commit differs in exactly one\n")
    handle.write("  top-level function and in nothing else (imports, module-level code,\n")
    handle.write("  classes and every other top-level function must be identical).\n")
    handle.write("- **R2**: project-defined helpers needed by the changed function, copied\n")
    handle.write("  verbatim: same-file functions/classes (transitive), plus names imported\n")
    handle.write("  from other project modules that the function or its same-file helpers\n")
    handle.write("  use, and those names' own helpers, transitively across modules.\n")
    handle.write("  Decorators and decorator factories count as helpers. Module-level\n")
    handle.write("  constants, stdlib/third-party imports, methods and class-hierarchy\n")
    handle.write("  dependencies are not counted. Limit: 3.\n")
    handle.write("- **R3**: packages in the bug's `requirements.txt`. Blocked only on the\n")
    handle.write("  heavy list: numpy, scipy, pandas, tensorflow, keras, matplotlib, spacy,\n")
    handle.write("  and compiled-extension packages.\n")
    handle.write("- **R3 amendment 1 (2026-10-26, recorded before any generation\n")
    handle.write("  results)**: if a project's `requirements.txt` is an environment\n")
    handle.write("  freeze (byte-identical in at least 3 bugs of the project *and*\n")
    handle.write("  listing at least 10 packages that no Python file in the project\n")
    handle.write("  imports), R3 is judged from the bug's `run_test.sh` and the test\n")
    handle.write("  file's imports instead. Applied the same way to every project.\n")
    handle.write("  The `r3_basis` column records which source was used.\n")
    handle.write("- **R3 amendment 2 (2026-10-26, added after scanning fastapi,\n")
    handle.write("  before any generation results)**: a `requirements.txt` that is\n")
    handle.write("  unique to a bug but lists at least 50 packages imported nowhere in\n")
    handle.write("  the project is also treated as an environment freeze, because the\n")
    handle.write("  content alone is unmistakable.\n")
    handle.write("- **The R3 freeze rule is FINAL**: identical in at least 3 bugs and\n")
    handle.write("  at least 10 unused packages, OR at least 50 unused packages. R1, R2\n")
    handle.write("  and R3 are frozen; no further changes.\n")
    handle.write("- **Compat aliases** of builtins/stdlib (e.g. `compat_str = str`) are\n")
    handle.write("  module-level constants, not helpers.\n")
    handle.write("- **Licence (final, 2026-10-26)**: GPL/AGPL excluded. MPL/LGPL\n")
    handle.write("  excluded and recorded; tqdm (MPL-2.0, dual-licensed with MIT) was\n")
    handle.write("  ruled out on 2026-10-26.\n")
    handle.write("- **R4** is not checked here (needs execution on Python 3.13).\n")
    handle.write("\n")


def write_licence_section(handle, licence_path, guess_fn, licence_excluded):
    if licence_path is None:
        handle.write("Licence file: **none found**\n")
        return
    text = read_text_any(licence_path)
    guess, action = guess_fn(text)
    handle.write("Licence file: `" + str(licence_path) + "`\n")
    handle.write("\n")
    handle.write("```\n")
    for line in text.splitlines()[:8]:
        handle.write(line + "\n")
    handle.write("```\n")
    handle.write("\n")
    handle.write(
        "Licence guess (suggestion only): **"
        + guess
        + "** [action: "
        + ("excluded" if licence_excluded is not None else action)
        + "]\n"
    )
    if licence_excluded is not None:
        if licence_excluded["date"] == "standing policy":
            handle.write("\n")
            handle.write(
                "**Licence policy (final, 2026-10-26)**: excluded - "
                + licence_excluded["licence"]
                + ". GPL/AGPL are excluded; MPL/LGPL are excluded and recorded.\n"
            )
        else:
            handle.write("\n")
            handle.write(
                "**Licence ruling ("
                + licence_excluded["date"]
                + ")**: excluded - "
                + licence_excluded["licence"]
                + ". "
                + licence_excluded["reason"]
                + ".\n"
            )


def write_notes(project, licence_path, guess_fn, bug_dirs, r1_rows, detail_rows, usable, licence_excluded):
    NOTES.parent.mkdir(parents=True, exist_ok=True)
    new_file = not NOTES.exists()
    with NOTES.open("a", encoding="utf-8", newline="\n") as handle:
        if new_file:
            write_notes_header(handle)

        handle.write("\n## " + project + "\n")
        handle.write("\n")
        write_licence_section(handle, licence_path, guess_fn, licence_excluded)

        handle.write("\n")
        handle.write("### R1 (all " + str(len(bug_dirs)) + " bugs)\n")
        handle.write("\n")
        handle.write("| bug | function | verdict | reason |\n")
        handle.write("|---|---|---|---|\n")
        for bid, ok, func, reason, _info in r1_rows:
            handle.write(
                "| "
                + bid
                + " | "
                + (func if func else "")
                + " | "
                + ("pass" if ok else "excluded")
                + " | "
                + (reason.replace("|", "/") if reason else "")
                + " |\n"
            )
        handle.write("\n")
        handle.write(
            "R1: pass="
            + str(len([r for r in r1_rows if r[1]]))
            + " excluded="
            + str(len([r for r in r1_rows if not r[1]]))
            + "\n"
        )

        handle.write("\n")
        handle.write("### R2/R3 (R1 survivors)\n")
        handle.write("\n")
        freeze_rows = [r for r in detail_rows if r["basis"] == "run_test.sh"]
        if freeze_rows:
            handle.write("R3 judged from `run_test.sh` under the environment-freeze amendment:\n")
            handle.write("\n")
            for row in freeze_rows:
                evidence = row["freeze"]
                if evidence["shared"]:
                    head = (
                        "`requirements.txt` byte-identical in bugs "
                        + ", ".join(sorted(evidence["group"], key=int))
                    )
                else:
                    head = "`requirements.txt` unique to this bug but unmistakably a freeze"
                handle.write(
                    "- bug "
                    + row["bug"]
                    + ": "
                    + head
                    + "; "
                    + str(len(evidence["unrelated"]))
                    + " of "
                    + str(evidence["total"])
                    + " packages imported nowhere in the project; test: `"
                    + row["test_cmd"]
                    + "`; test-file third-party imports: "
                    + (str(row["test_imports"]) if row["test_imports"] else "[]")
                    + "\n"
                )
            handle.write("\n")
        handle.write("| bug | function | same-file helpers | cross-module helpers | R2 total | r3_basis | requirements.txt | heavy blockers | python | R2 | R3 |\n")
        handle.write("|---|---|---|---|---|---|---|---|---|---|---|\n")
        for row in detail_rows:
            handle.write(
                "| "
                + row["bug"]
                + " | "
                + row["function"]
                + " | "
                + str(len(row["same"]))
                + " "
                + str(row["same"])
                + " | "
                + str(len(row["cross"]))
                + " "
                + str(row["cross"])
                + " | "
                + str(row["total"])
                + " | "
                + row["basis"]
                + " | "
                + (", ".join(row["packages"]) if row["packages"] else "[]")
                + " | "
                + ("; ".join(row["hits"]) if row["hits"] else "none")
                + " | "
                + row["python_version"]
                + " | "
                + ("pass" if row["r2"] else "excluded")
                + " | "
                + ("pass" if row["r3"] else "excluded")
                + " |\n"
            )
        handle.write("\n")
        if licence_excluded is None:
            licence_suffix = ""
        elif licence_excluded["date"] == "standing policy":
            licence_suffix = " (licence excluded)"
        else:
            licence_suffix = " (licence excluded on " + licence_excluded["date"] + ")"
        handle.write("Usable for " + project + ": " + (", ".join(r["bug"] for r in usable) if usable else "none") + licence_suffix + "\n")


def write_notes_r1_only(project, licence_path, guess_fn, bug_dirs, r1_rows, r3_rows, licence_excluded):
    NOTES.parent.mkdir(parents=True, exist_ok=True)
    new_file = not NOTES.exists()
    with NOTES.open("a", encoding="utf-8", newline="\n") as handle:
        if new_file:
            write_notes_header(handle)

        handle.write("\n## " + project + "\n")
        handle.write("\n")
        write_licence_section(handle, licence_path, guess_fn, licence_excluded)

        handle.write("\n")
        handle.write("### R1 (all " + str(len(bug_dirs)) + " bugs)\n")
        handle.write("\n")
        handle.write("| bug | function | verdict | reason |\n")
        handle.write("|---|---|---|---|\n")
        for bid, ok, func, reason, _info in r1_rows:
            handle.write(
                "| "
                + bid
                + " | "
                + (func if func else "")
                + " | "
                + ("pass" if ok else "excluded")
                + " | "
                + (reason.replace("|", "/") if reason else "")
                + " |\n"
            )
        handle.write("\n")
        handle.write(
            "R1: pass="
            + str(len([r for r in r1_rows if r[1]]))
            + " excluded="
            + str(len([r for r in r1_rows if not r[1]]))
            + "\n"
        )

        handle.write("\n")
        handle.write("### R3 / R2 (R1 survivors)\n")
        handle.write("\n")
        handle.write("| bug | function | file | r3_basis | blockers | R2 | R3 |\n")
        handle.write("|---|---|---|---|---|---|---|\n")
        for row in r3_rows:
            if row["r2"] is None:
                r2_cell = "not evaluated"
            else:
                r2_cell = (
                    str(row["r2_total"])
                    + " -> "
                    + ("pass" if row["r2"] else "excluded")
                )
            handle.write(
                "| "
                + row["bug"]
                + " | "
                + row["function"]
                + " | "
                + row["path"]
                + " | "
                + row["basis"]
                + " | "
                + ("; ".join(row["hits"]) if row["hits"] else "none")
                + " | "
                + r2_cell
                + " | "
                + ("excluded" if row["hits"] else "pass")
                + " |\n"
            )
        handle.write("\n")
        blocked = [r for r in r3_rows if r["hits"]]
        r2_evaluated = [r for r in r3_rows if r["r2"] is not None]
        r2_pass = [r for r in r2_evaluated if r["r2"]]
        handle.write(
            "R1 survivors="
            + str(len(r3_rows))
            + " blocked by R3="
            + str(len(blocked))
            + " R3 pass="
            + str(len(r2_evaluated))
            + " R2 pass="
            + str(len(r2_pass))
            + "\n"
        )
        if r2_evaluated:
            handle.write(
                "\nR2 was evaluated only for the R1 survivors that R3 does not block: "
                + ", ".join(r["bug"] for r in r2_evaluated)
                + ".\n"
            )
        else:
            handle.write(
                "\nR2 was not evaluated: every R1 survivor is blocked by R3.\n"
            )

        if licence_excluded is not None:
            handle.write(
                "\nUsable for " + project + ": none (licence excluded)\n"
            )
        else:
            handle.write(
                "\nUsable for "
                + project
                + ": "
                + (", ".join(r["bug"] for r in r2_pass) if r2_pass else "none")
                + "\n"
            )


def write_clarifications(append):
    """Dated clarifications and spot checks; no rule changes."""
    lines = []
    lines.append("## Clarifications and spot checks (2026-10-26)")
    lines.append("")
    lines.append("These are dated clarifications and evidence records. They do not change the frozen R1/R2/R3 rules or the heavy-package list.")
    lines.append("")
    lines.append("### matplotlib R3 evidence (2026-10-26)")
    lines.append("")
    lines.append("All 30 matplotlib bugs have a 0-byte `requirements.txt`. R3 is judged from the selected test's imports (the same evidence source as the frozen freeze amendment), not from the empty file. The 5 R1 survivors (16, 17, 24, 26, 30) all import `matplotlib` and `numpy`, so they are R3-blocked. This is an input-gap clarification, not a change to the heavy list. The total remains 58.")
    lines.append("")
    lines.append("### Keras 9 / luigi 21 (2026-10-26)")
    lines.append("")
    lines.append("Keras bug 9 and luigi bug 21 are usable. Both pass R3 under the frozen freeze amendment, which uses the selected test's imports: keras 9's test imports `markdown` and `pytest`; luigi 21's test imports `mock`. R2: keras 9 = 0 helpers; luigi 21 = 2 helpers.")
    lines.append("")
    lines.append("### R2 implementation fix (2026-10-26)")
    lines.append("")
    lines.append("The script now follows helpers of cross-module helpers and decorator helpers. This is an implementation correction to the frozen R2 rule, not a rule change. Re-running the nine earlier projects moved thefuck 9, 11 and 19 from R2-pass to R2-excluded (count-only increases: thefuck 4, 5, 15, 21 and scrapy 15, 17). Thefuck usable went 17 -> 14; the nine-project subtotal went 59 -> 56. Keras 9 and luigi 21 add 2, so the all-501 total is 58.")
    lines.append("")
    lines.append("### Pandas short-SHA spot checks (2026-10-26)")
    lines.append("")
    lines.append("Pandas buggy commit IDs are abbreviated. For these 8 bugs, `git rev-parse <short>` resolves to the fixed commit's parent, confirming the R1 comparison uses the intended buggy tree.")
    lines.append("")
    lines.append("| bug | buggy short | resolved buggy | fixed short | fixed parent | match |")
    lines.append("|---|---|---|---|---|---|")
    repo = PROJECT_REPOS / "pandas"
    meta = BUGSINPY_META / "projects" / "pandas" / "bugs"
    for bid in ["1", "2", "3", "10", "50", "100", "150", "169"]:
        info = bug_info(read_text_any(meta / bid / "bug.info"))
        buggy = info["buggy_commit_id"]
        fixed = info["fixed_commit_id"]
        code, parent, _err = git(repo, "rev-parse", fixed + "^")
        if code != 0:
            git(repo, "fetch", "--depth", "2", "origin", fixed)
            code, parent, _err = git(repo, "rev-parse", fixed + "^")
        code2, resolved, _err2 = git(repo, "rev-parse", buggy)
        parent = parent.strip() if code == 0 else "?"
        resolved = resolved.strip() if code2 == 0 else "NO"
        match = (
            "yes"
            if parent != "?" and resolved != "NO" and parent == resolved
            else "NO"
        )
        lines.append(
            "| "
            + bid
            + " | "
            + buggy
            + " | "
            + resolved
            + " | "
            + fixed[:12]
            + " | "
            + parent
            + " | "
            + match
            + " |"
        )
    lines.append("")
    text = "\n".join(lines) + "\n"
    print(text, end="")
    if append:
        NOTES.parent.mkdir(parents=True, exist_ok=True)
        with NOTES.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(text)


def write_funnel(append):
    """Aggregate the per-project JSON records into the all-501 funnel."""
    files = {path.stem: path for path in RESULTS.glob("*.json")}
    funnel_order = [
        "youtube-dl",
        "PySnooper",
        "tornado",
        "tqdm",
        "cookiecutter",
        "fastapi",
        "black",
        "scrapy",
        "thefuck",
        "pandas",
        "keras",
        "ansible",
        "matplotlib",
        "luigi",
        "sanic",
        "spacy",
        "httpie",
    ]
    missing = [project for project in funnel_order if project not in files]
    if missing:
        sys.exit("missing results for: " + ", ".join(missing))

    rows = []
    reason_counts = {}
    totals = {
        "bugs": 0,
        "r1": 0,
        "r2": 0,
        "r3": 0,
        "licence": 0,
        "usable": 0,
        "pending": 0,
    }
    for project in funnel_order:
        data = json.loads(files[project].read_text(encoding="utf-8"))
        counts = {
            "bugs": 0,
            "r1": 0,
            "r2": 0,
            "r3": 0,
            "licence": 0,
            "usable": 0,
            "pending": 0,
        }
        for bug in data["bugs"]:
            counts["bugs"] += 1
            pre_licence = (
                data["licence"]["excluded"]
                and data["licence"]["stage"] == "pre"
            )
            if pre_licence:
                counts["licence"] += 1
                continue
            if not bug["r1"]:
                counts["r1"] += 1
                group = r1_reason_group(bug.get("reason", ""))
                reason_counts[group] = reason_counts.get(group, 0) + 1
                continue
            if data["mode"] == "r1":
                if bug.get("r3") is False:
                    counts["r3"] += 1
                elif bug.get("r2") is False:
                    counts["r2"] += 1
                elif bug.get("r2") is True:
                    if data["licence"]["excluded"]:
                        counts["licence"] += 1
                    else:
                        counts["usable"] += 1
                else:
                    counts["pending"] += 1
                continue
            if bug.get("r2") is False:
                counts["r2"] += 1
                continue
            if bug.get("r3") is False:
                counts["r3"] += 1
                continue
            if data["licence"]["excluded"]:
                counts["licence"] += 1
                continue
            counts["usable"] += 1
        rows.append((project, data["mode"], data["licence"]["guess"], counts))
        for key in totals:
            totals[key] += counts[key]

    print("=== FUNNEL: ALL 501 BUGS ===")
    print("Gate order: licence (GPL/AGPL projects, pre) -> R1 -> R2 -> R3 -> licence (MPL/LGPL rulings, post).")
    print("R1-only projects are gated R1 -> R3; R2 is evaluated there only when the freeze amendment lets R3 pass.")
    print("")
    print("| project | mode | licence | bugs | R1 excluded | R2 excluded | R3 excluded | licence excluded | usable | pending |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for project, mode, guess, counts in rows:
        r2_cell = str(counts["r2"])
        print(
            "| "
            + project
            + " | "
            + mode
            + " | "
            + guess
            + " | "
            + str(counts["bugs"])
            + " | "
            + str(counts["r1"])
            + " | "
            + r2_cell
            + " | "
            + str(counts["r3"])
            + " | "
            + str(counts["licence"])
            + " | "
            + str(counts["usable"])
            + " | "
            + str(counts["pending"])
            + " |"
        )
    print(
        "| **TOTAL** | | | "
        + str(totals["bugs"])
        + " | "
        + str(totals["r1"])
        + " | "
        + str(totals["r2"])
        + " | "
        + str(totals["r3"])
        + " | "
        + str(totals["licence"])
        + " | "
        + str(totals["usable"])
        + " | "
        + str(totals["pending"])
        + " |"
    )
    print("")
    print("For mode r1 projects, R2 was evaluated only on R1 survivors that passed R3; the R2 column counts exclusions from that pass.")
    print("Ansible (GPL-3.0) is excluded at the licence gate before R1; its 18 bugs are counted under licence and its R1 detail is informational.")
    print("")
    print("R1 exclusions by reason (first failing check):")
    for reason in sorted(reason_counts):
        print("    " + reason + ": " + str(reason_counts[reason]))
    print("")
    print(
        "Totals: bugs="
        + str(totals["bugs"])
        + "  R1 excluded="
        + str(totals["r1"])
        + "  R2 excluded="
        + str(totals["r2"])
        + "  R3 excluded="
        + str(totals["r3"])
        + "  licence excluded="
        + str(totals["licence"])
        + "  usable="
        + str(totals["usable"])
        + "  pending="
        + str(totals["pending"])
    )
    print(
        "Check: "
        + str(totals["bugs"])
        + " = "
        + str(totals["r1"])
        + " + "
        + str(totals["r2"])
        + " + "
        + str(totals["r3"])
        + " + "
        + str(totals["licence"])
        + " + "
        + str(totals["usable"])
        + " + "
        + str(totals["pending"])
    )

    if append:
        NOTES.parent.mkdir(parents=True, exist_ok=True)
        with NOTES.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n## Funnel (all " + str(totals["bugs"]) + " bugs)\n")
            handle.write("\n")
            handle.write("Gate order: licence (GPL/AGPL projects, pre) -> R1 -> R2 -> R3 -> licence (MPL/LGPL rulings, post). R1-only projects are gated R1 -> R3; R2 is evaluated there only when the freeze amendment lets R3 pass.\n")
            handle.write("\n")
            handle.write("| project | mode | licence | bugs | R1 excluded | R2 excluded | R3 excluded | licence excluded | usable | pending |\n")
            handle.write("|---|---|---|---|---|---|---|---|---|---|\n")
            for project, mode, guess, counts in rows:
                r2_cell = str(counts["r2"])
                handle.write(
                    "| "
                    + project
                    + " | "
                    + mode
                    + " | "
                    + guess
                    + " | "
                    + str(counts["bugs"])
                    + " | "
                    + str(counts["r1"])
                    + " | "
                    + r2_cell
                    + " | "
                    + str(counts["r3"])
                    + " | "
                    + str(counts["licence"])
                    + " | "
                    + str(counts["usable"])
                    + " | "
                    + str(counts["pending"])
                    + " |\n"
                )
            handle.write(
                "| **TOTAL** | | | "
                + str(totals["bugs"])
                + " | "
                + str(totals["r1"])
                + " | "
                + str(totals["r2"])
                + " | "
                + str(totals["r3"])
                + " | "
                + str(totals["licence"])
                + " | "
                + str(totals["usable"])
                + " | "
                + str(totals["pending"])
                + " |\n"
            )
            handle.write("\nFor mode r1 projects, R2 was evaluated only on R1 survivors that passed R3; the R2 column counts exclusions from that pass.\n")
            handle.write("Ansible (GPL-3.0) is excluded at the licence gate before R1; its 18 bugs are counted under licence and its R1 detail is informational.\n")
            handle.write("\nR1 exclusions by reason (first failing check):\n")
            handle.write("\n")
            for reason in sorted(reason_counts):
                handle.write("- " + reason + ": " + str(reason_counts[reason]) + "\n")
            handle.write("\n")
            handle.write(
                "Totals: bugs="
                + str(totals["bugs"])
                + "  R1 excluded="
                + str(totals["r1"])
                + "  R2 excluded="
                + str(totals["r2"])
                + "  R3 excluded="
                + str(totals["r3"])
                + "  licence excluded="
                + str(totals["licence"])
                + "  usable="
                + str(totals["usable"])
                + "  pending="
                + str(totals["pending"])
                + "\n"
            )
            handle.write(
                "Check: "
                + str(totals["bugs"])
                + " = "
                + str(totals["r1"])
                + " + "
                + str(totals["r2"])
                + " + "
                + str(totals["r3"])
                + " + "
                + str(totals["licence"])
                + " + "
                + str(totals["usable"])
                + " + "
                + str(totals["pending"])
                + "\n"
            )


if __name__ == "__main__":
    main()
