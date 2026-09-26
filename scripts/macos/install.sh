#!/bin/bash
# Install IDAPro-MuiLs into the per-user IDA plugin directory on macOS.
# Nothing inside the IDA .app bundle is touched. Everything this script
# changes is recorded in a timestamped backup so uninstall.sh can undo it.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
IDAUSR="${IDAUSR:-$HOME/.idapro}"
PLUGINS="$IDAUSR/plugins"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$IDAUSR/muils-backup-$STAMP"

if pgrep -x ida >/dev/null || pgrep -x ida64 >/dev/null; then
    echo "IDA is running. Quit it first." >&2
    exit 1
fi

PLUGINS_EXISTED=$([ -d "$PLUGINS" ] && echo yes || echo no)
mkdir -p "$BACKUP" "$PLUGINS"
{
    echo "installed_at=$STAMP"
    echo "idausr=$IDAUSR"
    echo "plugins_dir_existed=$PLUGINS_EXISTED"
} > "$BACKUP/manifest.txt"

# Preserve anything we are about to replace, plus IDA's registry (desktop
# layouts, recent files) so a full rollback is possible.
[ -e "$PLUGINS/ida_modern_ui_loader.py" ] && cp -p "$PLUGINS/ida_modern_ui_loader.py" "$BACKUP/"
[ -d "$PLUGINS/ida_modern_ui" ] && cp -Rp "$PLUGINS/ida_modern_ui" "$BACKUP/"
[ -d "$IDAUSR/modern_ui" ] && cp -Rp "$IDAUSR/modern_ui" "$BACKUP/modern_ui.config"
[ -e "$IDAUSR/ida.reg" ] && cp -p "$IDAUSR/ida.reg" "$BACKUP/ida.reg"

rm -rf "$PLUGINS/ida_modern_ui"
cp -p "$REPO/ida_modern_ui_loader.py" "$PLUGINS/"
cp -Rp "$REPO/src/ida_modern_ui" "$PLUGINS/ida_modern_ui"
find "$PLUGINS/ida_modern_ui" -name '__pycache__' -type d -prune -exec rm -rf {} +

echo "Installed to: $PLUGINS"
echo "Backup at:    $BACKUP"
echo "Toggle in IDA with Ctrl+Alt+M; settings under Edit > IDAPro-MuiLs Settings..."
echo "Undo with:    $REPO/scripts/macos/uninstall.sh"
