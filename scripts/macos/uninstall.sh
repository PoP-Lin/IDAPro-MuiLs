#!/bin/bash
# Remove IDAPro-MuiLs from ~/.idapro and optionally roll back to the backup
# taken by install.sh.  Usage: uninstall.sh [--restore-backup [DIR]] [--keep-config]
set -euo pipefail

IDAUSR="${IDAUSR:-$HOME/.idapro}"
PLUGINS="$IDAUSR/plugins"
RESTORE=no; KEEP_CONFIG=no; BACKUP=""
while [ $# -gt 0 ]; do
    case "$1" in
        --restore-backup) RESTORE=yes; if [ $# -gt 1 ] && [ -d "$2" ]; then BACKUP="$2"; shift; fi ;;
        --keep-config) KEEP_CONFIG=yes ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

if pgrep -x ida >/dev/null || pgrep -x ida64 >/dev/null; then
    echo "IDA is running. Quit it first." >&2
    exit 1
fi

rm -f "$PLUGINS/ida_modern_ui_loader.py"
rm -rf "$PLUGINS/ida_modern_ui"
if [ "$KEEP_CONFIG" = no ]; then
    rm -rf "$IDAUSR/modern_ui"
fi
# Remove the plugins dir only if this script's install created it and it is now empty.
rmdir "$PLUGINS" 2>/dev/null || true
echo "Removed plugin files from $PLUGINS"

if [ "$RESTORE" = yes ]; then
    if [ -z "$BACKUP" ]; then
        BACKUP="$(ls -d "$IDAUSR"/muils-backup-* 2>/dev/null | sort | tail -1 || true)"
    fi
    if [ -z "$BACKUP" ] || [ ! -d "$BACKUP" ]; then
        echo "No backup directory found." >&2; exit 1
    fi
    [ -e "$BACKUP/ida.reg" ] && cp -p "$BACKUP/ida.reg" "$IDAUSR/ida.reg" && echo "Restored ida.reg from $BACKUP"
    [ -e "$BACKUP/ida_modern_ui_loader.py" ] && mkdir -p "$PLUGINS" && cp -p "$BACKUP/ida_modern_ui_loader.py" "$PLUGINS/"
    [ -d "$BACKUP/ida_modern_ui" ] && mkdir -p "$PLUGINS" && cp -Rp "$BACKUP/ida_modern_ui" "$PLUGINS/"
    [ -d "$BACKUP/modern_ui.config" ] && cp -Rp "$BACKUP/modern_ui.config" "$IDAUSR/modern_ui"
    echo "Rollback from $BACKUP complete."
fi
