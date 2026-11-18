"""Unit tests for the configurable shortcut store (`ShortcutStore`) and safe macOS control (`MacController`)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.mac_control import MacController
from app.shortcuts import ShortcutStore


def test_default_seed_and_find_replace(tmp_path: Path) -> None:
    """Ensure automatic seeding with all essential shortcuts (including `find_replace`) and idempotency."""
    db_file = tmp_path / "shortcuts.db"
    store = ShortcutStore(db_path=db_file)
    try:
        items = store.list_shortcuts()
        assert len(items) >= 22

        slugs = {item["slug"] for item in items}
        expected_slugs = {
            "mission_control",
            "app_expose",
            "space_left",
            "space_right",
            "switch_window",
            "switch_app",
            "fullscreen_window",
            "toggle_dock",
            "screenshot_clipboard",
            "screenshot_file",
            "screenshot_full",
            "find",
            "find_replace",
            "paste_plain",
            "undo",
            "redo",
            "play_pause",
            "next_track",
            "prev_track",
            "volume_up",
            "volume_down",
            "volume_mute",
            "lock_screen",
            "pomodoro_25",
        }
        assert expected_slugs.issubset(slugs)

        find_replace = store.get_shortcut("find_replace")
        assert find_replace is not None
        assert find_replace["title"] == "Find and Replace"
        assert find_replace["category"] == "editing"
        assert find_replace["action_type"] == "keystroke"
        assert find_replace["payload"] == {"keys": "cmd+opt+f"}
        assert "substituir" in find_replace["voice_triggers"]

        # Category filter
        capture_items = store.list_shortcuts(category="capture")
        assert {item["slug"] for item in capture_items} == {
            "screenshot_clipboard",
            "screenshot_file",
            "screenshot_full",
        }
    finally:
        store.close()

    # Reopening the database must not duplicate the seed
    reopened = ShortcutStore(db_path=db_file)
    try:
        assert len(reopened.list_shortcuts()) == len(items)
    finally:
        reopened.close()


def test_crud_reorder_trigger_and_reset_defaults(tmp_path: Path) -> None:
    """Validate creation, lookup by ID/slug, update, reorder, voice trigger, removal and reset."""
    store = ShortcutStore(db_path=tmp_path / "crud.db")
    try:
        created = store.create_shortcut(
            {
                "title": "Abrir Notas Rápidas",
                "icon": "📝",
                "category": "apps",
                "action_type": "app_activate",
                "payload": {"app": "Notes"},
                "voice_triggers": "abrir notas, bloco de notas",
                "color": "amber",
                "pinned_on_deck": True,
                "requires_confirmation": True,
            }
        )
        assert created["slug"] == "abrir_notas_rapidas"
        assert created["requires_confirmation"] is True
        assert created["is_default"] is False

        # A title collision generates a unique slug with a numeric suffix
        duplicate_title = store.create_shortcut(
            {
                "title": "Abrir Notas Rápidas",
                "action_type": "agent_prompt",
                "payload": {"prompt": "Resuma minhas notas"},
            }
        )
        assert duplicate_title["slug"] == "abrir_notas_rapidas_2"

        # Lookup by integer ID and by slug
        by_id = store.get_shortcut(created["id"])
        by_slug = store.get_shortcut("abrir_notas_rapidas")
        assert by_id == by_slug

        # Strict validation of action_type and duplicate explicit slug
        with pytest.raises(ValueError):
            store.create_shortcut(
                {
                    "title": "Invalido",
                    "action_type": "shell_exec",
                    "payload": {"cmd": "rm -rf /"},
                }
            )
        with pytest.raises(ValueError):
            store.create_shortcut(
                {
                    "slug": "find_replace",
                    "title": "Duplicado",
                    "action_type": "keystroke",
                    "payload": {"keys": "cmd+k"},
                }
            )

        # Update
        updated = store.update_shortcut(
            created["id"],
            {
                "title": "Abrir Apple Notes",
                "voice_triggers": "apple notes, minhas anotacoes",
                "requires_confirmation": False,
            },
        )
        assert updated is not None
        assert updated["title"] == "Abrir Apple Notes"
        assert updated["requires_confirmation"] is False

        # Voice trigger lookup (preferring the most specific match)
        match_replace = store.find_by_trigger("Ei, abre o pesquisar e substituir aí")
        assert match_replace is not None
        assert match_replace["slug"] == "find_replace"

        match_custom = store.find_by_trigger("Quero abrir minhas anotações")
        assert match_custom is not None
        assert match_custom["slug"] == "abrir_notas_rapidas"

        # Reorder putting the custom item on top
        reordered = store.reorder_shortcuts(["abrir_notas_rapidas", "find_replace"])
        assert reordered[0]["slug"] == "abrir_notas_rapidas"
        assert reordered[1]["slug"] == "find_replace"

        # Delete
        assert store.delete_shortcut("abrir_notas_rapidas") is True
        assert store.delete_shortcut("abrir_notas_rapidas") is False
        assert store.get_shortcut(created["id"]) is None

        # Reset defaults restores a clean catalog
        restored = store.reset_defaults()
        restored_slugs = {item["slug"] for item in restored}
        assert "abrir_notas_rapidas_2" not in restored_slugs
        assert "find_replace" in restored_slugs
    finally:
        store.close()


def test_build_agent_shortcuts_prompt_respects_limit(tmp_path: Path) -> None:
    """Ensure the shortcuts prompt includes slugs, triggers and open apps, and respects `max_chars`."""
    store = ShortcutStore(db_path=tmp_path / "prompt.db")
    try:
        running_apps = [
            {"name": "Google Chrome", "running": True, "frontmost": True},
            {"name": "Visual Studio Code", "running": True, "frontmost": False},
            {"name": "Spotify", "running": False, "frontmost": False},
        ]
        prompt = store.build_agent_shortcuts_prompt(running_apps=running_apps, max_chars=1800)
        assert len(prompt) <= 1800
        assert "[find_replace]" in prompt
        assert "Find and Replace" in prompt
        assert "Google Chrome*" in prompt
        assert "Visual Studio Code" in prompt

        tight_prompt = store.build_agent_shortcuts_prompt(running_apps=running_apps, max_chars=220)
        assert len(tight_prompt) <= 220
        assert tight_prompt
    finally:
        store.close()


def test_mac_controller_prevents_command_injection() -> None:
    """Reject malicious payloads in `activate_app`, `execute_keystroke` and `execute_mac_command` without invoking a subprocess."""
    calls: list[list[str]] = []

    def fake_runner(argv: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    mac = MacController(runner=fake_runner)

    malicious_apps = [
        "Google Chrome; rm -rf /",
        "Safari | whoami",
        "Terminal`id`",
        "Finder$(cat /etc/passwd)",
        "../../Applications/Terminal.app",
        "/Applications/Safari.app",
        "-e malicious",
        'Notes" & do shell script "id',
        "",
    ]
    for bad_app in malicious_apps:
        res = mac.activate_app(bad_app)
        assert res["ok"] is False

    malicious_keys = [
        'cmd+a"; do shell script "whoami',
        "cmd+shift+a;ls",
        "super+a",
        "cmd+",
        "cmd++a",
        "ctrl+alt+del;id",
        "",
    ]
    for bad_keys in malicious_keys:
        res = mac.execute_keystroke(bad_keys)
        assert res["ok"] is False

    bad_commands = ["rm_rf", "shell:whoami", "mission_control;id", ""]
    for bad_cmd in bad_commands:
        res = mac.execute_mac_command(bad_cmd)
        assert res["ok"] is False

    # No invalid attempt may trigger a subprocess
    assert calls == []


def test_keystroke_whitelist_and_accessibility_diagnostics() -> None:
    """Validate safe translation of keystrokes to `osascript` and a clear Accessibility diagnostic."""
    recorded: list[list[str]] = []

    def ok_runner(argv: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
        recorded.append(argv)
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    mac = MacController(runner=ok_runner)

    res1 = mac.execute_keystroke("cmd+opt+f")
    assert res1["ok"] is True
    assert res1["needs_accessibility"] is False
    assert recorded[-1][:2] == ["/usr/bin/osascript", "-e"]
    assert recorded[-1][2] == 'tell application "System Events" to keystroke "f" using {command down, option down}'

    res2 = mac.execute_keystroke("ctrl+left")
    assert res2["ok"] is True
    assert recorded[-1][2] == 'tell application "System Events" to key code 123 using {control down}'

    res3 = mac.execute_keystroke("cmd+grave")
    assert res3["ok"] is True
    assert recorded[-1][2] == 'tell application "System Events" to key code 50 using {command down}'

    res4 = mac.execute_keystroke("cmd+ctrl+shift+4")
    assert res4["ok"] is True
    assert recorded[-1][2] == (
        'tell application "System Events" to keystroke "4" '
        "using {command down, control down, shift down}"
    )

    # macOS Accessibility error 1002
    def denied_runner(argv: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=argv,
            returncode=1,
            stdout="",
            stderr="execution error: System Events got an error: osascript is not allowed to send keystrokes. (1002)",
        )

    mac_denied = MacController(runner=denied_runner)
    denied = mac_denied.execute_keystroke("cmd+opt+f")
    assert denied["ok"] is False
    assert denied["needs_accessibility"] is True
    assert "System Settings → Privacy & Security → Accessibility" in denied["error"]


def test_activate_app_and_mac_commands_use_safe_argv() -> None:
    """Check that `activate_app`, `execute_mac_command` and `run_shortcut` build valid `argv` lists."""
    recorded: list[list[str]] = []

    def fake_runner(argv: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
        recorded.append(argv)
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="74\n", stderr="")

    mac = MacController(runner=fake_runner)

    res_app = mac.activate_app("Google Chrome")
    assert res_app["ok"] is True
    assert recorded[-1] == ["/usr/bin/open", "-a", "Google Chrome"]

    res_mc = mac.execute_mac_command("mission_control")
    assert res_mc["ok"] is True
    assert recorded[-1] == ["/usr/bin/open", "-a", "Mission Control"]

    res_shot = mac.execute_mac_command("screenshot_area_file")
    assert res_shot["ok"] is True
    assert recorded[-1][0:2] == ["/usr/sbin/screencapture", "-i"]
    assert res_shot["file"].endswith(".png")

    res_vol = mac.execute_mac_command("volume_up")
    assert res_vol["ok"] is True
    assert res_vol["volume"] == 74

    # Pomodoro does not need a subprocess
    prev_len = len(recorded)
    res_pomo = mac.run_shortcut(
        {
            "slug": "pomodoro_25",
            "title": "Pomodoro 25m",
            "action_type": "mac_command",
            "payload": {"command": "pomodoro_start"},
        }
    )
    assert res_pomo["ok"] is True
    assert res_pomo["pomodoro"]["active"] is True
    assert len(recorded) == prev_len

    # agent_prompt returns the prompt without a subprocess
    res_prompt = mac.run_shortcut(
        {
            "slug": "resumo",
            "title": "Resumo",
            "action_type": "agent_prompt",
            "payload": {"prompt": "Resuma meu dia"},
        }
    )
    assert res_prompt["ok"] is True
    assert res_prompt["prompt"] == "Resuma meu dia"


def test_list_running_apps_and_mac_status_cache() -> None:
    """Validate parsing of open apps, frontmost app, status telemetry and the 3s cache."""
    calls: list[list[str]] = []

    def fake_runner(argv: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if argv[0] == "/usr/bin/osascript" and "background only is false" in argv[2]:
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout="Finder||false\nVisual Studio Code||true\nSpotify||false\n",
                stderr="",
            )
        if argv[0] == "/usr/bin/osascript":
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout="Visual Studio Code||65||false||Spotify||playing||Time||Pink Floyd\n",
                stderr="",
            )
        if argv[0] == "/usr/bin/pmset":
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout="Now drawing from 'Battery Power'\n -InternalBattery-0 (id=123)\t82%; discharging; 4:10 remaining\n",
                stderr="",
            )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    mac = MacController(runner=fake_runner)

    apps = mac.list_running_apps()
    assert apps[0]["name"] == "Visual Studio Code"
    assert apps[0]["frontmost"] is True
    assert apps[0]["running"] is True

    by_name = {app["name"]: app for app in apps}
    assert by_name["Spotify"]["running"] is True
    assert by_name["Google Chrome"]["running"] is False
    assert by_name["Google Chrome"]["favorite"] is True

    calls.clear()
    status1 = mac.get_mac_status()
    status2 = mac.get_mac_status()
    assert status1 == status2
    # The second call must come from the cache (only 2 subprocesses in total: osascript + pmset)
    assert len(calls) == 2
    assert status1["active_app"] == "Visual Studio Code"
    assert status1["volume"] == 65
    assert status1["muted"] is False
    assert status1["battery_percent"] == 82
    assert status1["charging"] is False
    assert status1["now_playing"] == {
        "app": "Spotify",
        "state": "playing",
        "track": "Time",
        "artist": "Pink Floyd",
    }


def test_weather_cache_and_offline_fallback() -> None:
    """Validate the Open-Meteo query with a 15-minute cache and a graceful fallback when offline."""
    fetch_count = 0

    def fake_weather(lat: float, lon: float, city: str) -> dict[str, Any]:
        nonlocal fetch_count
        fetch_count += 1
        return {
            "current": {
                "temperature_2m": 24.5,
                "apparent_temperature": 25.0,
                "weather_code": 61,
                "is_day": 1,
                "wind_speed_10m": 12.3,
            }
        }

    mac = MacController(weather_fetcher=fake_weather)
    w1 = mac.get_weather(-23.5505, -46.6333, "São Paulo")
    w2 = mac.get_weather(-23.5505, -46.6333, "São Paulo")
    assert fetch_count == 1
    assert w1 == w2
    assert w1["ok"] is True
    assert w1["offline"] is False
    assert w1["temperature_c"] == 24.5
    assert w1["condition"] == "Rain"
    assert w1["effect"] == "rain"

    def offline_weather(lat: float, lon: float, city: str) -> dict[str, Any]:
        raise RuntimeError("no internet")

    mac_offline = MacController(weather_fetcher=offline_weather)
    fallback = mac_offline.get_weather(-23.5505, -46.6333, "São Paulo")
    assert fallback["ok"] is False
    assert fallback["offline"] is True
    assert fallback["effect"] == "none"
    assert fallback["temperature_c"] is None


def test_mac_status_and_media_omit_uninstalled_players(monkeypatch: pytest.MonkeyPatch) -> None:
    """Omit the Spotify/Music AppleScript blocks when not installed to avoid compile errors."""
    recorded: list[list[str]] = []

    def fake_subprocess_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        recorded.append(argv)
        if argv[0] == "/usr/bin/osascript":
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout="Finder||50||false||||||||\n",
                stderr="",
            )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    # Case 1: Spotify missing and Music present
    def exists_only_music(self: Path) -> bool:
        return str(self) == "/System/Applications/Music.app"

    monkeypatch.setattr(Path, "exists", exists_only_music)
    mac = MacController()
    status = mac.get_mac_status()
    assert status["active_app"] == "Finder"
    assert status["volume"] == 50
    assert status["muted"] is False
    osa_script = recorded[0][2]
    assert 'application "Spotify"' not in osa_script
    assert 'application "Music"' in osa_script

    res_play = mac.execute_mac_command("play_pause")
    assert res_play["ok"] is True
    media_script = recorded[-1][2]
    assert 'application "Spotify"' not in media_script
    assert 'application "Music"' in media_script

    # Case 2: neither player installed
    recorded.clear()
    monkeypatch.setattr(Path, "exists", lambda self: False)
    mac_none = MacController()
    status_none = mac_none.get_mac_status()
    assert status_none["active_app"] == "Finder"
    assert 'application "Spotify"' not in recorded[0][2]
    assert 'application "Music"' not in recorded[0][2]

    res_no_player = mac_none.execute_mac_command("play_pause")
    assert res_no_player["ok"] is True
    assert res_no_player["output"] == "no_player"



def test_default_titles_are_english_and_triggers_bilingual() -> None:
    """Seeds have English titles and keep every Portuguese phrase next to new English ones."""
    from app.shortcuts import DEFAULT_SHORTCUTS, _LEGACY_PT_DEFAULTS

    assert set(_LEGACY_PT_DEFAULTS) == {item["slug"] for item in DEFAULT_SHORTCUTS}
    by_slug = {item["slug"]: item for item in DEFAULT_SHORTCUTS}
    for slug, (_old_title, old_triggers) in _LEGACY_PT_DEFAULTS.items():
        phrases = [p.strip() for p in by_slug[slug]["voice_triggers"].split(",")]
        old = [p.strip() for p in old_triggers.split(",")]
        assert all(p in phrases for p in old)
        assert len(phrases) >= len(old) + 2 or len(phrases) >= 6, slug
    assert by_slug["app_expose"]["title"] == "App Exposé"
    assert by_slug["paste_plain"]["title"] == "Paste Without Formatting"
    assert by_slug["space_left"]["title"] == "Space Left ⬅️"


def test_voice_triggers_resolve_in_both_languages(tmp_path: Path) -> None:
    """A Portuguese and an English phrase resolve to the same Shortcut."""
    store = ShortcutStore(db_path=tmp_path / "bi.db")
    try:
        pt = store.find_by_trigger("colar sem formatação")
        en = store.find_by_trigger("paste as plain text")
        assert pt is not None and en is not None
        assert pt["slug"] == en["slug"] == "paste_plain"
    finally:
        store.close()


def test_legacy_migration_upgrades_untouched_rows_only(tmp_path: Path) -> None:
    from app.shortcuts import DEFAULT_SHORTCUTS, _LEGACY_PT_DEFAULTS

    db_file = tmp_path / "legacy.db"
    store = ShortcutStore(db_path=db_file)
    old_title, old_triggers = _LEGACY_PT_DEFAULTS["undo"]
    store._conn.execute(
        "UPDATE shortcuts SET title = ?, voice_triggers = ? WHERE slug = 'undo'",
        (old_title, old_triggers),
    )
    store._conn.execute(
        "UPDATE shortcuts SET title = 'My Redo', voice_triggers = ? WHERE slug = 'redo'",
        (_LEGACY_PT_DEFAULTS["redo"][1],),
    )
    store._conn.execute(
        "UPDATE shortcuts SET title = ?, voice_triggers = 'buscar agora' WHERE slug = 'find'",
        (_LEGACY_PT_DEFAULTS["find"][0],),
    )
    store._conn.commit()
    store.close()

    store = ShortcutStore(db_path=db_file)
    try:
        defaults = {i["slug"]: i for i in DEFAULT_SHORTCUTS}
        undo = store.get_shortcut("undo")
        assert undo["title"] == "Undo"
        assert undo["voice_triggers"] == defaults["undo"]["voice_triggers"]
        redo = store.get_shortcut("redo")
        assert redo["title"] == "My Redo"
        assert redo["voice_triggers"] == _LEGACY_PT_DEFAULTS["redo"][1]
        find = store.get_shortcut("find")
        assert find["title"] == _LEGACY_PT_DEFAULTS["find"][0]
        assert find["voice_triggers"] == "buscar agora"
        snapshot = store.list_shortcuts()
    finally:
        store.close()

    store = ShortcutStore(db_path=db_file)
    try:
        assert store.list_shortcuts() == snapshot
    finally:
        store.close()
