# Contributing

Contributions that keep the plugin restrained, fast, and compatible with IDA's
native workspace are welcome.

## Development setup

1. Install Python 3.10 or 3.11.
2. Install the CI dependencies:

   ```powershell
   python -m pip install -r requirements-ci.txt
   ```

3. Run the offline checks:

   ```powershell
   python scripts/run_checks.py --require-qt
   python -m ruff check src scripts ida_modern_ui_loader.py --select E9,F63,F7,F82
   ```

4. Build and verify the distributable archive:

   ```powershell
   python scripts/build_release.py
   ```

The offline suite does not require IDA. Changes that affect widget discovery,
painting, layout, or native window handling should also be exercised in IDA
9.3 with a separate `IDAUSR` directory before a pull request is submitted.

## Pull requests

- Keep changes focused and explain the user-visible behavior.
- Add or update a regression check for behavior changes.
- Do not commit IDA SDK files, databases, crash dumps, licensed binaries,
  private samples, or machine-specific verification logs.
- Preserve third-party plugin layouts and local widget stylesheets.
- Update `CHANGELOG.md` when a change is visible to users.

By contributing, you agree that your contribution is licensed under the MIT
License used by this repository.
