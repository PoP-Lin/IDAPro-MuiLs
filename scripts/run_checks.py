#!/usr/bin/env python3
"""Run the repository's offline regression checks with one command."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
EXPECTED_CHECK_COUNT = 10


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-qt",
        action="store_true",
        help="fail when a check falls back to a static-only path",
    )
    return parser.parse_args()


def syntax_check() -> list[str]:
    failures: list[str] = []
    paths = [ROOT / "ida_modern_ui_loader.py"]
    paths.extend(sorted((ROOT / "src").rglob("*.py")))
    paths.extend(sorted(SCRIPTS.glob("*.py")))
    for path in paths:
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
        except (OSError, SyntaxError, UnicodeError) as error:
            failures.append(f"{path.relative_to(ROOT)}: {error}")
    return failures


def main() -> int:
    args = parse_args()
    syntax_failures = syntax_check()
    if syntax_failures:
        print("SYNTAX_CHECK_FAILED", file=sys.stderr)
        for failure in syntax_failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    checks = sorted(SCRIPTS.glob("check_*.py"))
    if len(checks) != EXPECTED_CHECK_COUNT:
        print(
            f"CHECK_DISCOVERY_FAILED expected={EXPECTED_CHECK_COUNT} actual={len(checks)}",
            file=sys.stderr,
        )
        return 1

    environment = os.environ.copy()
    environment.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    failures: list[str] = []

    for check in checks:
        relative = check.relative_to(ROOT)
        print(f"\n==> {relative}", flush=True)
        completed = subprocess.run(
            [sys.executable, str(check)],
            cwd=str(ROOT),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output = completed.stdout.rstrip()
        if output:
            print(output)
        if completed.returncode != 0:
            failures.append(f"{relative} exited {completed.returncode}")
        if args.require_qt and "static_only=1" in output:
            failures.append(f"{relative} used a static-only fallback")

    if failures:
        print("\nOFFLINE_CHECKS_FAILED", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(f"\nOFFLINE_CHECKS_OK syntax=passed checks={len(checks)}/{len(checks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
