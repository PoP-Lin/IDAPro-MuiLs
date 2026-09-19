## Summary

Describe the user-visible change and why it is needed.

## Verification

- [ ] `python scripts/run_checks.py --require-qt`
- [ ] `python -m ruff check src scripts ida_modern_ui_loader.py --select E9,F63,F7,F82`
- [ ] IDA interaction tested when the change affects runtime UI behavior
- [ ] No SDK files, databases, dumps, licensed binaries, or machine-specific logs included
- [ ] `CHANGELOG.md` updated for user-visible behavior
