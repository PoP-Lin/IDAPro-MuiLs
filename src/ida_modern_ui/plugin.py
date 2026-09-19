# -*- coding: utf-8 -*-
"""IDAPro-MuiLs plugin entry point."""

from __future__ import annotations

import os

import ida_idaapi
import ida_kernwin

from . import RUNTIME_BUILD
from .config import load_config, normalize_config, save_config
from .dock_runtime import dock_runtime_diagnostics, rescan_dock_runtime
from .layout_runtime import (
    BASE_LAYOUT_VERSION,
    apply_builtin_column_layout,
    TARGET_LAYOUT_VERSION,
    apply_balanced_panel_layout,
    apply_balanced_three_panel_layout,
    column_layout_runtime_diagnostics,
    layout_runtime_diagnostics,
)
from .navband_runtime import navband_runtime_diagnostics
from .panel_runtime import panel_runtime_diagnostics
from .plugin_panels import plugin_panel_diagnostics
from .popup_runtime import popup_runtime_diagnostics
from .qt_compat import (
    QApplication,
    dialog_accepted,
    execute_dialog,
    standard_button,
)
from .resize_runtime import resize_runtime_diagnostics
from .scrollbar_runtime import scrollbar_runtime_diagnostics
from .selection_runtime import selection_runtime_diagnostics
from .settings_dialog import SettingsDialog
from .theme import ThemeManager

ACTION_SETTINGS = "modern_ui:settings"


class _SettingsAction(ida_kernwin.action_handler_t):
    def __init__(self, plugin):
        super().__init__()
        self._plugin = plugin

    def activate(self, context):
        self._plugin.show_settings()
        return 1

    def update(self, context):
        return ida_kernwin.AST_ENABLE_ALWAYS


class _UIHooks(ida_kernwin.UI_Hooks):
    def __init__(self, plugin):
        super().__init__()
        self._plugin = plugin

    def ready_to_run(self):
        self._plugin.on_ui_ready()

    def widget_visible(self, widget):
        self._plugin.on_widget_visible(widget)

    def desktop_applied(self, name, from_idb, desktop_type):
        self._plugin.on_desktop_applied(name, from_idb, desktop_type)

    def finish_populating_widget_popup(self, widget, popup, ctx=None):
        self._plugin.on_finish_populating_widget_popup(widget, popup)

    if hasattr(ida_kernwin.UI_Hooks, "about_to_exit"):
        def about_to_exit(self):
            # IDA 9.4 emits this while both Qt and IDAPython are still alive.
            # IDA 9.3 keeps the existing plugin_t.term() cleanup path.
            self._plugin.term()


class ModernUIPlugin(ida_idaapi.plugin_t):
    flags = ida_idaapi.PLUGIN_FIX
    comment = "Modern, restrained Material-style interface for IDA"
    help = "Modernizes IDA while retaining compatibility with Qt plugin panels."
    wanted_name = "IDAPro-MuiLs: Toggle"
    wanted_hotkey = "Ctrl+Alt+M"

    def __init__(self):
        super().__init__()
        self._theme = ThemeManager()
        self._config = load_config()
        self._ui_hooks = None
        self._settings_action = None
        self._ready_rescan_done = False
        self._ready_reported = False
        self._layout_gate_open = False
        self._desktop_restored = False
        self._layout_migration_origin_version = None
        self._layout_migration_active = False
        self._terminated = False

    def init(self):
        self._ui_hooks = _UIHooks(self)
        self._ui_hooks.hook()
        self._register_actions()
        # Apply immediately as some builds load PLUGIN_FIX after ready_to_run.
        # In that late-load case this activation scan is already the final
        # inventory; ordinary startup receives one additional ready scan below.
        self._apply_saved_state()
        self._set_runtime_marker()
        self._report_runtime("init")
        return ida_idaapi.PLUGIN_KEEP

    def run(self, arg):
        self._config["enabled"] = not self._theme.enabled
        self._config = save_config(self._config)
        self._apply_saved_state()

    def term(self):
        # In 9.4 the early UI shutdown callback can precede plugin unloading.
        # Never restore overlays/native hooks twice or touch Qt again at term.
        if self._terminated:
            return
        self._terminated = True
        try:
            if self._ui_hooks is not None:
                self._ui_hooks.unhook()
                self._ui_hooks = None
            ida_kernwin.detach_action_from_menu("Edit/IDAPro-MuiLs Settings...", ACTION_SETTINGS)
            ida_kernwin.unregister_action(ACTION_SETTINGS)
            self._settings_action = None
        finally:
            self._theme.restore()

    def on_ui_ready(self):
        self._layout_gate_open = True
        self._config = load_config()
        self._apply_saved_state()

        self._maybe_migrate_panel_layout()
        # Apply built-in chooser/tree column widths only after the restored
        # desktop is visible.  Per-header guards make this idempotent and keep
        # user-adjusted widths intact; no resize/paint path is involved.
        apply_builtin_column_layout()

        diagnostics = dock_runtime_diagnostics()
        if not self._ready_rescan_done:
            # The desktop restore/migration can create title buttons after the
            # first theme application.  Inventory once at this lifecycle
            # boundary, after the restored dock tree is authoritative; no
            # timer or application-wide event filter is involved.
            self._ready_rescan_done = True
            if self._theme.enabled:
                diagnostics = rescan_dock_runtime()

        self._set_runtime_marker()
        if not self._ready_reported:
            self._ready_reported = True
            self._report_runtime("ready", diagnostics)

    def on_widget_visible(self, widget):
        if not self._theme.enabled:
            return
        qt_widget = None
        try:
            qt_widget = ida_kernwin.PluginForm.TWidgetToQtPythonWidget(widget)
            self._theme.refresh_ida_widget(qt_widget)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        # A hidden built-in panel may be constructed after ready_to_run.  Scan
        # only this newly visible subtree so the deferred column polish does
        # not touch plugin panels or enter a hot path.
        if qt_widget is not None:
            apply_builtin_column_layout(qt_widget)
        # widget_visible can fire while IDA is still constructing/restoring a
        # desktop.  Refresh its appearance immediately, but do not persist a
        # layout migration until a lifecycle boundary has opened the gate.
        if self._layout_gate_open:
            self._maybe_migrate_panel_layout()

    def on_desktop_applied(self, name, from_idb, desktop_type):
        # The desktop is now restored, so a one-time splitter migration will
        # not be overwritten later in the same startup sequence.
        self._layout_gate_open = True
        self._desktop_restored = True
        if self._layout_migration_origin_version is not None:
            # ready_to_run can precede the final desktop restore on some
            # builds.  Rewind the provisional version and validate/apply once
            # more against the authoritative restored splitter tree.
            self._config["panel_layout_version"] = int(
                self._layout_migration_origin_version
            )
            self._config = save_config(self._config)
            self._layout_migration_origin_version = None
        self._maybe_migrate_panel_layout()
        apply_builtin_column_layout()

    def on_finish_populating_widget_popup(self, widget, popup):
        if not self._theme.enabled:
            return
        owner = None
        try:
            owner = ida_kernwin.PluginForm.TWidgetToQtPythonWidget(widget)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        self._theme.refresh_ida_popup(owner, popup)

    def _maybe_migrate_panel_layout(self):
        if not self._theme.enabled or self._layout_migration_active:
            return
        self._layout_migration_active = True
        try:
            current_version = int(self._config.get("panel_layout_version", 0))
            if current_version >= TARGET_LAYOUT_VERSION:
                return

            applied_version = current_version
            message = ""
            # Prefer the current three-panel desktop when it is already visible.
            # Otherwise retain the original two-panel migration and wait for a
            # later Names widget_visible event before advancing to version 2.
            if apply_balanced_three_panel_layout():
                applied_version = TARGET_LAYOUT_VERSION
                message = (
                    "editor/lower 68:32, Functions/editor 29:71, "
                    "Output/Strings/Names 32:36:32"
                )
            elif (
                current_version < BASE_LAYOUT_VERSION
                and apply_balanced_panel_layout()
            ):
                applied_version = BASE_LAYOUT_VERSION
                message = "editor/lower 68:32, Output/Strings 43:57"
            else:
                return

            self._config["panel_layout_version"] = applied_version
            self._config = save_config(self._config)
            if (
                not self._desktop_restored
                and self._layout_migration_origin_version is None
            ):
                self._layout_migration_origin_version = current_version
            ida_kernwin.msg(
                f"[IDAPro-MuiLs] Applied balanced panel layout ({message}).\n"
            )
        finally:
            self._layout_migration_active = False

    @staticmethod
    def _set_runtime_marker():
        app = QApplication.instance()
        if app is None:
            return
        try:
            app.setProperty("modern_ui_runtime_build", RUNTIME_BUILD)
            app.setProperty("modern_ui_runtime_pid", int(os.getpid()))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    @staticmethod
    def _report_runtime(stage, diagnostics=None):
        snapshot = diagnostics or dock_runtime_diagnostics()
        resize = resize_runtime_diagnostics()
        scrollbars = scrollbar_runtime_diagnostics()
        selections = selection_runtime_diagnostics()
        navband = navband_runtime_diagnostics()
        panels = panel_runtime_diagnostics()
        plugin_panels = plugin_panel_diagnostics()
        popups = popup_runtime_diagnostics()
        layout = layout_runtime_diagnostics()
        columns = column_layout_runtime_diagnostics()
        counts = snapshot.get("target_counts", {})
        ida_kernwin.msg(
            "[IDAPro-MuiLs] "
            f"build={RUNTIME_BUILD} pid={os.getpid()} stage={stage} "
            f"scan_count={snapshot.get('scan_count', 0)} "
            f"targets=arrow:{counts.get('arrow', 0)},"
            f"area:{counts.get('arrow-area', 0)},"
            f"close:{counts.get('close', 0)},"
            f"title_action:{counts.get('title-action', 0)}\n"
            f"[IDAPro-MuiLs] resize_hook={int(resize.get('hook_installed', False))} "
            f"resize_windows={resize.get('window_count', 0)} "
            f"resize_cycles={resize.get('start_count', 0)}/"
            f"{resize.get('end_count', 0)} "
            f"scrollbar_overlays={scrollbars.get('overlay_count', 0)} "
            f"functions_selection={selections.get('functions_count', 0)} "
            f"navband={navband.get('navband_count', 0)} "
            f"legend_swatches={navband.get('legend_swatch_count', 0)} "
            f"panel_cli_groups={panels.get('cli_group_count', 0)} "
            f"panel_quick_filters={panels.get('quick_filter_surface_count', 0)} "
            f"plugin_panels={plugin_panels.get('tagged_count', 0)} "
            f"plugin_roles={plugin_panels.get('role_count', 0)} "
            f"popup_menus={popups.get('registered_count', 0)} "
            f"popup_dwm={popups.get('dwm_count', 0)} "
            f"popup_masks={popups.get('mask_count', 0)} "
            f"layout={layout.get('last_result', 'not-attempted')} "
            f"columns={columns.get('last_result', 'not-attempted')}"
            f"/{columns.get('apply_count', 0)}\n"
        )

    def show_settings(self):
        state = {"baseline": dict(self._config)}
        dialog = SettingsDialog(state["baseline"], self._preview)
        apply_button = dialog.buttons.button(standard_button("Apply"))

        def apply_and_update_baseline():
            self._commit(dialog.values())
            state["baseline"] = dict(self._config)

        apply_button.clicked.connect(apply_and_update_baseline)

        if execute_dialog(dialog) == dialog_accepted():
            self._commit(dialog.values())
        else:
            self._config = state["baseline"]
            self._apply_saved_state()

    def _preview(self, values):
        candidate = normalize_config({**self._config, **values})
        if candidate["enabled"]:
            self._theme.apply(candidate)
        else:
            self._theme.restore()

    def _commit(self, values):
        try:
            self._config = save_config({**self._config, **values})
            self._apply_saved_state()
            ida_kernwin.msg("[IDAPro-MuiLs] Settings saved.\n")
        except Exception as exc:
            ida_kernwin.msg(f"[IDAPro-MuiLs] Failed to save settings: {exc}\n")

    def _apply_saved_state(self):
        try:
            if self._config["enabled"]:
                self._theme.apply(self._config)
            else:
                self._theme.restore()
        except Exception as exc:
            ida_kernwin.msg(f"[IDAPro-MuiLs] Failed to apply theme: {exc}\n")

    def _register_actions(self):
        self._settings_action = _SettingsAction(self)
        description = ida_kernwin.action_desc_t(
            ACTION_SETTINGS,
            "IDAPro-MuiLs Settings...",
            self._settings_action,
            "Ctrl+Alt+Shift+M",
            "Configure the IDAPro-MuiLs theme",
            -1,
        )
        if ida_kernwin.register_action(description):
            ida_kernwin.attach_action_to_menu(
                "Edit/IDAPro-MuiLs Settings...",
                ACTION_SETTINGS,
                ida_kernwin.SETMENU_APP,
            )
