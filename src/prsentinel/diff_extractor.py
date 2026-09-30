"""Work out which functions changed between the old and new version of a file.

How it works, in plain English:
1. Python's built-in `ast` module reads a .py file and turns it into a tree
   that shows the functions, classes and lines.
2. We walk that tree and remember every function we find, using its full name
   (for a method inside a class the name is "Cart.add_item").
3. We compare the old list of functions with the new list.
   - in old but not new  -> "removed"
   - in new but not old  -> "added"
   - in both, and ast.dump() says the two trees are different -> "modified"
   - in both and the trees are the same -> not reported. That covers edits
     that only touch comments or spacing, because neither is in the tree.

Reading real `git diff` input comes in a later step. For now this module
compares two whole files, which is easier to test.
"""

import argparse
import ast
import json
from pathlib import Path

# The keys we put in every dictionary we return.
NAME = "name"
CHANGE_TYPE = "change_type"
OLD_CODE = "old_code"
NEW_CODE = "new_code"
OLD_START = "old_start_line"
OLD_END = "old_end_line"
NEW_START = "new_start_line"
NEW_END = "new_end_line"

ADDED = "added"
REMOVED = "removed"
MODIFIED = "modified"


def _collect_functions(source: str, filename: str = "<code>") -> dict:
    """Return {full_function_name: ast_node} for every function in the code.

    Nested functions get a longer name, for example "outer.inner".
    """
    tree = ast.parse(source, filename=filename)
    found = {}

    def walk(node, prefix: str = "") -> None:
        """Look through everything inside `node` and save the functions."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                full_name = prefix + child.name
                found[full_name] = child
                # A function can contain another function, so keep going.
                walk(child, full_name + ".")
            elif isinstance(child, ast.ClassDef):
                # Methods inside a class get the class name in front.
                walk(child, prefix + child.name + ".")

    walk(tree)
    return found


def _same_code(old_node: ast.AST, new_node: ast.AST) -> bool:
    """Return True if the two functions mean exactly the same thing.

    ast.dump() turns a function into a text tree of its structure. Comments
    and spacing are NOT part of that tree, so editing only those does not
    count as a change. Everything else does count: a different default value,
    a different docstring, or any different line of code.
    """
    return ast.dump(old_node) == ast.dump(new_node)


def _get_source(lines: list, node: ast.AST) -> str:
    """Return the source code of one function, decorators included."""
    start = node.lineno - 1
    # Any decorator sits on the lines above the "def" line, so start there.
    if node.decorator_list:
        start = min(item.lineno for item in node.decorator_list) - 1
    end = node.end_lineno
    return "\n".join(lines[start:end])


def _make_change(name, change_type, old_node, new_node, old_lines, new_lines) -> dict:
    """Build one dictionary describing one changed function."""
    return {
        NAME: name,
        CHANGE_TYPE: change_type,
        OLD_CODE: _get_source(old_lines, old_node) if old_node else "",
        NEW_CODE: _get_source(new_lines, new_node) if new_node else "",
        OLD_START: old_node.lineno if old_node else None,
        OLD_END: old_node.end_lineno if old_node else None,
        NEW_START: new_node.lineno if new_node else None,
        NEW_END: new_node.end_lineno if new_node else None,
    }


def extract_changes(before_code: str, after_code: str,
                    before_name: str = "<before>",
                    after_name: str = "<after>") -> list:
    """Compare two blocks of Python code and list the functions that changed.

    Returns a list of dictionaries, sorted by function name. Each dictionary
    has the function name, the change type (added/removed/modified), the old
    code, the new code, and the line numbers in both files.
    """
    before_functions = _collect_functions(before_code, before_name)
    after_functions = _collect_functions(after_code, after_name)

    before_lines = before_code.splitlines()
    after_lines = after_code.splitlines()

    all_names = sorted(set(before_functions) | set(after_functions))
    changes = []

    for name in all_names:
        old_node = before_functions.get(name)
        new_node = after_functions.get(name)

        if old_node is None:
            change_type = ADDED
        elif new_node is None:
            change_type = REMOVED
        elif _same_code(old_node, new_node):
            # The two functions mean the same thing, so there is nothing to
            # report. Comments and spacing on their own do not count.
            continue
        else:
            change_type = MODIFIED

        changes.append(
            _make_change(name, change_type, old_node, new_node,
                         before_lines, after_lines)
        )

    return changes


def extract_changes_from_files(before_path: str, after_path: str) -> list:
    """Read two files from disk and list the functions that changed."""
    before_code = Path(before_path).read_text(encoding="utf-8")
    after_code = Path(after_path).read_text(encoding="utf-8")
    return extract_changes(before_code, after_code,
                           str(before_path), str(after_path))


def format_changes(changes: list) -> str:
    """Turn the results into text that is easy for a person to read."""
    if not changes:
        return "No functions changed."

    lines = [f"{len(changes)} function(s) changed:"]
    for change in changes:
        lines.append("")
        lines.append(f"  {change[CHANGE_TYPE].upper()}: {change[NAME]}")
        if change[OLD_START] is not None:
            lines.append(
                f"    old lines {change[OLD_START]}-{change[OLD_END]}"
            )
        else:
            lines.append("    old lines: none (new function)")
        if change[NEW_START] is not None:
            lines.append(
                f"    new lines {change[NEW_START]}-{change[NEW_END]}"
            )
        else:
            lines.append("    new lines: none (deleted function)")

        if change[CHANGE_TYPE] == MODIFIED:
            lines.append("    --- old code ---")
            for line in change[OLD_CODE].splitlines():
                lines.append(f"    - {line}")
            lines.append("    --- new code ---")
            for line in change[NEW_CODE].splitlines():
                lines.append(f"    + {line}")

    return "\n".join(lines)


def main() -> int:
    """Let us run this file from the terminal: python -m prsentinel.diff_extractor"""
    parser = argparse.ArgumentParser(
        description="Show which functions changed between two Python files."
    )
    parser.add_argument("before_file", help="path to the old version of the file")
    parser.add_argument("after_file", help="path to the new version of the file")
    parser.add_argument("--json", action="store_true",
                        help="print the results as JSON instead of plain text")
    args = parser.parse_args()

    try:
        changes = extract_changes_from_files(args.before_file, args.after_file)
    except FileNotFoundError as error:
        print(f"Cannot read that file: {error}")
        return 1
    except SyntaxError as error:
        print(f"That file has a syntax error: {error}")
        return 1

    if args.json:
        print(json.dumps(changes, indent=2))
    else:
        print(format_changes(changes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
