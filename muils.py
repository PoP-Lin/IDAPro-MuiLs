#!/usr/bin/env python3
"""IDAPro-MuiLs manager: install, remove, or toggle the theme on any platform.

Stdlib only, Python 3.8+.  Targets IDA's per-user plugin directory, which is
shared by every IDA 9.x release (and later) on the machine, so the .app / .exe
bundle is never modified and a new IDA version picks the theme up unchanged.

    python muils.py install            copy plugin into the user plugin dir (with backup)
    python muils.py uninstall          remove plugin files and its settings
    python muils.py uninstall --restore-backup [DIR]   ... and roll back the latest backup
    python muils.py status             show where things are and what is installed
    python muils.py enable | disable   flip the saved "enabled" flag without opening IDA
    python muils.py theme dark|oled    set the saved theme

Options: --idausr DIR (override the IDA user directory), --keep-config (uninstall).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC_LOADER = ROOT / "ida_modern_ui_loader.py"
SRC_PACKAGE = ROOT / "src" / "ida_modern_ui"
OWNED = ("ida_modern_ui_loader.py", "ida_modern_ui")
CONFIG_SUBDIR = "modern_ui"
BACKUP_PREFIX = "muils-backup-"


def user_idadir(override: str | None = None) -> Path:
    """Same rule IDA uses for ida_diskio.get_user_idadir()."""
    if override:
        return Path(override).expanduser()
    env = os.environ.get("IDAUSR")
    if env:
        # IDAUSR may hold several dirs; the first one is where plugins are read from.
        return Path(env.split(os.pathsep)[0]).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Hex-Rays" / "IDA Pro"
    return Path.home() / ".idapro"


def ida_running() -> bool:
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ida.exe"], capture_output=True, text=True).stdout
            out += subprocess.run(["tasklist", "/FI", "IMAGENAME eq ida64.exe"], capture_output=True, text=True).stdout
            return "ida.exe" in out.lower() or "ida64.exe" in out.lower()
        return subprocess.run(["pgrep", "-x", "ida"], capture_output=True).returncode == 0 or \
            subprocess.run(["pgrep", "-x", "ida64"], capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def require_ida_closed() -> None:
    if ida_running():
        sys.exit("IDA is running. Quit it first.")


def copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def make_backup(idausr: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = idausr / f"{BACKUP_PREFIX}{stamp}"
    plugins = idausr / "plugins"
    backup.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created": stamp,
        "idausr": str(idausr),
        "plugins_dir_existed": plugins.is_dir(),
        "platform": sys.platform,
        "saved": [],
    }
    for name in OWNED:
        target = plugins / name
        if target.is_dir():
            copy_tree(target, backup / name)
            manifest["saved"].append(name)
        elif target.is_file():
            shutil.copy2(target, backup / name)
            manifest["saved"].append(name)
    config_dir = idausr / CONFIG_SUBDIR
    if config_dir.is_dir():
        copy_tree(config_dir, backup / "modern_ui.config")
        manifest["saved"].append("modern_ui.config")
    reg = idausr / "ida.reg"  # desktop layouts / recent files on macOS and Linux
    if reg.is_file():
        shutil.copy2(reg, backup / "ida.reg")
        manifest["saved"].append("ida.reg")
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return backup


def latest_backup(idausr: Path) -> Path | None:
    candidates = sorted(p for p in idausr.glob(f"{BACKUP_PREFIX}*") if p.is_dir())
    return candidates[-1] if candidates else None


def cmd_install(args) -> None:
    idausr = user_idadir(args.idausr)
    plugins = idausr / "plugins"
    if not SRC_LOADER.is_file() or not SRC_PACKAGE.is_dir():
        sys.exit(f"Plugin sources not found next to {__file__}")
    require_ida_closed()
    backup = make_backup(idausr)
    plugins.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(plugins / "ida_modern_ui", ignore_errors=True)
    shutil.copy2(SRC_LOADER, plugins / "ida_modern_ui_loader.py")
    copy_tree(SRC_PACKAGE, plugins / "ida_modern_ui")
    print(f"Installed to: {plugins}")
    print(f"Backup at:    {backup}")
    print("In IDA: Ctrl+Alt+M toggles the theme; Edit > IDAPro-MuiLs Settings... configures it.")
    print(f"Undo with:    python {Path(__file__).name} uninstall [--restore-backup]")


def cmd_uninstall(args) -> None:
    idausr = user_idadir(args.idausr)
    plugins = idausr / "plugins"
    require_ida_closed()
    for name in OWNED:
        target = plugins / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()
    if not args.keep_config:
        shutil.rmtree(idausr / CONFIG_SUBDIR, ignore_errors=True)
    print(f"Removed plugin files from {plugins}")
    if args.restore_backup is None:
        return
    backup = Path(args.restore_backup) if args.restore_backup else latest_backup(idausr)
    if backup is None or not backup.is_dir():
        sys.exit("No backup directory found.")
    manifest = {}
    try:
        manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    for name in OWNED:
        saved = backup / name
        if saved.is_dir():
            plugins.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(plugins / name, ignore_errors=True)
            copy_tree(saved, plugins / name)
        elif saved.is_file():
            plugins.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, plugins / name)
    if (backup / "modern_ui.config").is_dir():
        shutil.rmtree(idausr / CONFIG_SUBDIR, ignore_errors=True)
        copy_tree(backup / "modern_ui.config", idausr / CONFIG_SUBDIR)
    if (backup / "ida.reg").is_file():
        shutil.copy2(backup / "ida.reg", idausr / "ida.reg")
        print("Restored ida.reg")
    if manifest.get("plugins_dir_existed") is False and plugins.is_dir() and not any(plugins.iterdir()):
        plugins.rmdir()
    print(f"Rollback from {backup} complete.")


def _config_path(idausr: Path) -> Path:
    return idausr / CONFIG_SUBDIR / "config.json"


def _load_user_config(idausr: Path) -> dict:
    path = _config_path(idausr)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_user_config(idausr: Path, data: dict) -> None:
    path = _config_path(idausr)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def cmd_toggle(args, enabled: bool) -> None:
    idausr = user_idadir(args.idausr)
    data = _load_user_config(idausr)
    data["enabled"] = enabled
    _save_user_config(idausr, data)
    print(f"Theme {'enabled' if enabled else 'disabled'} for the next IDA start ({_config_path(idausr)})")


def cmd_theme(args) -> None:
    idausr = user_idadir(args.idausr)
    data = _load_user_config(idausr)
    data["theme"] = {"dark": "modern_dark", "oled": "modern_oled"}[args.name]
    _save_user_config(idausr, data)
    print(f"Theme set to {data['theme']} ({_config_path(idausr)})")


def cmd_status(args) -> None:
    idausr = user_idadir(args.idausr)
    plugins = idausr / "plugins"
    print(f"Platform:        {sys.platform}")
    print(f"IDA user dir:    {idausr}")
    loader = plugins / "ida_modern_ui_loader.py"
    package = plugins / "ida_modern_ui"
    installed = loader.is_file() and package.is_dir()
    print(f"Installed:       {'yes' if installed else 'no'}  ({plugins})")
    if installed:
        try:
            sys.path.insert(0, str(plugins))
            version = (package / "__init__.py").read_text(encoding="utf-8")
            for line in version.splitlines():
                if line.startswith("__version__"):
                    print(f"Version:         {line.split('=')[1].strip().strip(chr(34))}")
        except OSError:
            pass
    config = _load_user_config(idausr)
    print(f"Saved config:    {_config_path(idausr)} {'(present)' if config else '(defaults)'}")
    if config:
        print(f"  enabled={config.get('enabled', True)} theme={config.get('theme', 'default')}")
    backups = sorted(p.name for p in idausr.glob(f"{BACKUP_PREFIX}*") if p.is_dir())
    print(f"Backups:         {len(backups)}" + (f" (latest {backups[-1]})" if backups else ""))
    print(f"IDA running:     {'yes' if ida_running() else 'no'}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--idausr", help="IDA user directory (default: $IDAUSR, %%APPDATA%%\\Hex-Rays\\IDA Pro, or ~/.idapro)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("install")
    un = sub.add_parser("uninstall")
    un.add_argument("--restore-backup", nargs="?", const="", metavar="DIR")
    un.add_argument("--keep-config", action="store_true")
    sub.add_parser("status")
    sub.add_parser("enable")
    sub.add_parser("disable")
    th = sub.add_parser("theme")
    th.add_argument("name", choices=("dark", "oled"))
    args = parser.parse_args(argv)
    {
        "install": cmd_install,
        "uninstall": cmd_uninstall,
        "status": cmd_status,
        "enable": lambda a: cmd_toggle(a, True),
        "disable": lambda a: cmd_toggle(a, False),
        "theme": cmd_theme,
    }[args.command](args)


if __name__ == "__main__":
    main()
