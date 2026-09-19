#!/usr/bin/env python3
"""Build and verify a reproducible GitHub release archive."""

from __future__ import annotations

import argparse
import hashlib
import re
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "ida_modern_ui"
LOADER = ROOT / "ida_modern_ui_loader.py"
VERSION_FILE = PACKAGE_ROOT / "__init__.py"
RELEASE_DOCUMENTS = (
    (ROOT / "LICENSE", PurePosixPath("ida_modern_ui/project_docs/LICENSE")),
    (ROOT / "README.md", PurePosixPath("ida_modern_ui/project_docs/README.md")),
    (
        ROOT / "README.zh-CN.md",
        PurePosixPath("ida_modern_ui/project_docs/README.zh-CN.md"),
    ),
    (
        ROOT / "CONTRIBUTING.md",
        PurePosixPath("ida_modern_ui/project_docs/CONTRIBUTING.md"),
    ),
    (
        ROOT / "docs" / "TUTORIAL.md",
        PurePosixPath("ida_modern_ui/project_docs/docs/TUTORIAL.md"),
    ),
    (
        ROOT / "docs" / "COMPATIBILITY.md",
        PurePosixPath("ida_modern_ui/project_docs/docs/COMPATIBILITY.md"),
    ),
    (
        ROOT / "docs" / "images" / "overview.png",
        PurePosixPath("ida_modern_ui/project_docs/docs/images/overview.png"),
    ),
)
VERSION_PATTERN = re.compile(
    r'^__version__\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+'
    r'(?:-(?:alpha|beta|rc)\.(?:0|[1-9][0-9]*))?)"$',
    re.MULTILINE,
)
SKIPPED_DIRECTORIES = {"__pycache__"}
SKIPPED_SUFFIXES = {".pyc", ".pyo"}
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        help="expected semantic version; it must match ida_modern_ui.__version__",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "dist",
        help="directory for the ZIP and checksum (default: dist)",
    )
    return parser.parse_args()


def source_version() -> str:
    match = VERSION_PATTERN.search(VERSION_FILE.read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit(f"semantic __version__ was not found in {VERSION_FILE}")
    return match.group(1)


def payload() -> list[tuple[Path, PurePosixPath]]:
    if PACKAGE_ROOT.is_symlink():
        raise SystemExit(f"symbolic links are not allowed in releases: {PACKAGE_ROOT}")
    if not LOADER.is_file() or not PACKAGE_ROOT.is_dir():
        raise SystemExit("plugin loader or source package is missing")

    files: list[tuple[Path, PurePosixPath]] = [
        (LOADER, PurePosixPath(LOADER.name)),
        *RELEASE_DOCUMENTS,
    ]
    for source, archive_path in files:
        if source.is_symlink():
            raise SystemExit(f"symbolic links are not allowed in releases: {source}")
        if not source.is_file():
            raise SystemExit(f"required release file is missing: {source}")
        if archive_path.is_absolute() or ".." in archive_path.parts:
            raise SystemExit(f"unsafe archive path: {archive_path}")

    for source in sorted(PACKAGE_ROOT.rglob("*")):
        if source.is_symlink():
            raise SystemExit(f"symbolic links are not allowed in releases: {source}")
        if not source.is_file():
            continue
        relative_source = source.relative_to(PACKAGE_ROOT)
        if any(part in SKIPPED_DIRECTORIES for part in relative_source.parts):
            continue
        if source.suffix.lower() in SKIPPED_SUFFIXES:
            continue
        archive_path = PurePosixPath("ida_modern_ui", *relative_source.parts)
        if archive_path.is_absolute() or ".." in archive_path.parts:
            raise SystemExit(f"unsafe archive path: {archive_path}")
        files.append((source, archive_path))

    archive_paths = [str(archive_path) for _, archive_path in files]
    if len(archive_paths) != len(set(archive_paths)):
        raise SystemExit("duplicate paths were found in the release payload")
    return sorted(files, key=lambda item: str(item[1]))


def write_archive(target: Path, files: list[tuple[Path, PurePosixPath]]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent), delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for source, archive_path in files:
                info = zipfile.ZipInfo(str(archive_path), date_time=ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (0o100644 & 0xFFFF) << 16
                archive.writestr(info, source.read_bytes(), compresslevel=9)
        temporary_path.replace(target)
    finally:
        temporary_path.unlink(missing_ok=True)


def verify_archive(target: Path, files: list[tuple[Path, PurePosixPath]]) -> None:
    expected = {str(archive_path): source.read_bytes() for source, archive_path in files}
    with zipfile.ZipFile(target, mode="r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise SystemExit("release archive contains duplicate paths")
        if set(names) != set(expected):
            missing = sorted(set(expected) - set(names))
            extra = sorted(set(names) - set(expected))
            raise SystemExit(f"release archive path mismatch: missing={missing} extra={extra}")
        for name, expected_bytes in expected.items():
            if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
                raise SystemExit(f"release archive contains an unsafe path: {name}")
            if archive.read(name) != expected_bytes:
                raise SystemExit(f"release archive content mismatch: {name}")


def main() -> int:
    args = parse_args()
    version = source_version()
    if args.version is not None and args.version != version:
        raise SystemExit(f"version mismatch: source={version} requested={args.version}")

    output_dir = args.output_dir.resolve()
    package_root = PACKAGE_ROOT.resolve()
    try:
        output_dir.relative_to(package_root)
    except ValueError:
        pass
    else:
        raise SystemExit(f"output directory must be outside the source package: {output_dir}")
    archive_path = output_dir / f"IDAPro-MuiLs-v{version}.zip"
    checksum_path = output_dir / f"IDAPro-MuiLs-v{version}.zip.sha256"
    files = payload()
    write_archive(archive_path, files)
    verify_archive(archive_path, files)

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest().upper()
    with checksum_path.open("w", encoding="ascii", newline="\n") as checksum_file:
        checksum_file.write(f"{digest}  {archive_path.name}\n")
    print(f"RELEASE_BUILD_OK version={version} files={len(files)}")
    print(f"archive={archive_path}")
    print(f"sha256={digest}")
    print(f"checksum={checksum_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
