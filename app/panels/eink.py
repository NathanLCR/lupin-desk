"""Server-rendered E-ink Mode page for a Kindle (old WebKit browser).

Black and white, big type, no JavaScript, no WebSocket, no animation and no external
assets. Every piece of user text is HTML-escaped. The page is read-only: no forms, no
buttons, no links.
"""

from __future__ import annotations

import html
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

EINK_WIDGET_TYPES: frozenset[str] = frozenset(
    {"clock", "today", "calendar", "weather", "notes", "tasks", "checklist", "lupin_line"}
)
DEFAULT_REFRESH_MINUTES = 5

_CELL_PX = 90
_NOTE_MAX_CHARS = 160
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


@dataclass
class EinkData:
    """Everything the E-ink tiles can show, gathered by the caller before rendering."""

    now: datetime
    calendar: list[dict] | None = None
    weather: dict | None = None
    today: dict | None = None
    tasks: list[dict] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)
    lupin_line: str = ""


def clamp_refresh_minutes(value: Any) -> int:
    """Return a refresh interval in whole minutes, 1 to 60; garbage becomes the default."""
    if value is None or isinstance(value, bool):
        return DEFAULT_REFRESH_MINUTES
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_REFRESH_MINUTES
    return max(1, min(60, number))


def widget_types_on_page(page: dict, orientation: str) -> set[str]:
    """Return the E-ink widget types placed on one page variant."""
    widgets = page.get(orientation) if isinstance(page, dict) else None
    if not isinstance(widgets, list):
        return set()
    types: set[str] = set()
    for widget in widgets:
        if not isinstance(widget, dict):
            continue
        widget_type = widget.get("type")
        if isinstance(widget_type, str) and widget_type in EINK_WIDGET_TYPES:
            types.add(widget_type)
    return types


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _esc(value: Any) -> str:
    """HTML-escape any value as text; None becomes an empty string."""
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _config_of(widget: dict) -> dict:
    config = widget.get("config")
    return config if isinstance(config, dict) else {}


def _int_option(
    config: dict,
    key: str,
    default: int,
    low: int,
    high: int,
    *,
    fallback_key: str | None = None,
) -> int:
    if key in config:
        value = config.get(key, default)
    elif fallback_key is not None and fallback_key in config:
        value = config.get(fallback_key, default)
    else:
        value = default
    if not _is_int(value):
        return default
    return max(low, min(high, value))


def _hhmm(now: datetime) -> str:
    return f"{now.hour:02d}:{now.minute:02d}"


def _unavailable() -> str:
    return '<div class="t"><p class="mid">Unavailable</p></div>'


def _pct(value: float) -> str:
    text = f"{round(value, 3):.3f}".rstrip("0").rstrip(".")
    return text or "0"


# ---------------------------------------------------------------------------
# Tile renderers. Each returns the full tile body: a <div class="t"> wrapper.
# ---------------------------------------------------------------------------


def _render_clock(config: dict, data: EinkData) -> str:
    now = data.now
    if config.get("hour12") is True:
        hour = now.hour % 12 or 12
        suffix = " AM" if now.hour < 12 else " PM"
        time_text = f"{hour}:{now.minute:02d}{suffix}"
    else:
        time_text = _hhmm(now)
    date_text = f"{_WEEKDAYS[now.weekday()]}, {now.day} {_MONTHS[now.month - 1]} {now.year}"
    return (
        '<div class="t">'
        f'<div class="big">{_esc(time_text)}</div>'
        f'<div class="mid">{_esc(date_text)}</div>'
        "</div>"
    )


def _render_today(config: dict, data: EinkData) -> str:
    today = data.today
    if not isinstance(today, dict):
        return '<div class="t"><p class="mid">No summary</p></div>'
    parts = ['<div class="t">']
    parts.append(f'<h2 class="mid">{_esc(today.get("headline"))}</h2>')
    top = today.get("top")
    if isinstance(top, list):
        shown = 0
        for item in top:
            if shown >= 3:
                break
            if not isinstance(item, dict) or not item.get("why"):
                continue
            parts.append(f'<p class="row">{_esc(item.get("why"))}</p>')
            shown += 1
    warnings = today.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings[:3]:
            if warning:
                parts.append(f'<p class="row">Warning: {_esc(warning)}</p>')
    parts.append("</div>")
    return "".join(parts)


def _render_calendar(config: dict, data: EinkData) -> str:
    events = data.calendar
    parts = ['<div class="t">', "<h2>Calendar</h2>"]
    if not isinstance(events, (list, tuple)):
        parts.append('<p class="row">Calendar unavailable</p>')
    elif not events:
        parts.append('<p class="row">No events today</p>')
    else:
        limit = _int_option(config, "limit", 6, 1, 12, fallback_key="max")
        shown = 0
        for event in events:
            if shown >= limit:
                break
            if not isinstance(event, dict):
                continue
            when = "All day" if event.get("all_day") else _esc(event.get("start"))
            parts.append(
                f'<p class="row"><span class="time">{when}</span>{_esc(event.get("title"))}</p>'
            )
            shown += 1
    parts.append("</div>")
    return "".join(parts)


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _render_weather(config: dict, data: EinkData) -> str:
    weather = data.weather
    if not isinstance(weather, dict) or not weather.get("ok"):
        return '<div class="t"><h2>Weather</h2><p class="row">Weather unavailable</p></div>'
    parts = ['<div class="t">', "<h2>Weather</h2>"]
    parts.append(f'<p class="row">{_esc(weather.get("city"))}</p>')
    temperature = weather.get("temperature_c")
    if _is_finite_number(temperature):
        parts.append(f'<div class="big">{int(round(temperature))}&deg;C</div>')
    else:
        parts.append('<div class="big">--</div>')
    if weather.get("condition"):
        parts.append(f'<p class="mid">{_esc(weather.get("condition"))}</p>')
    apparent = weather.get("apparent_c")
    if _is_finite_number(apparent):
        parts.append(f'<p class="row">feels like {int(round(apparent))}&deg;C</p>')
    parts.append("</div>")
    return "".join(parts)


def _render_tasks(config: dict, data: EinkData) -> str:
    limit = _int_option(config, "limit", 8, 1, 20)
    open_tasks = [
        task for task in (data.tasks or []) if isinstance(task, dict) and not task.get("done")
    ]
    parts = ['<div class="t">', "<h2>Tasks</h2>"]
    if not open_tasks:
        parts.append('<p class="row">No open tasks</p>')
    for task in open_tasks[:limit]:
        parts.append(f'<p class="row">[ ] {_esc(task.get("title"))}</p>')
    parts.append("</div>")
    return "".join(parts)


def _render_notes(config: dict, data: EinkData) -> str:
    limit = _int_option(config, "limit", 4, 1, 10)
    notes = [note for note in (data.notes or []) if isinstance(note, dict)]
    parts = ['<div class="t">', "<h2>Notes</h2>"]
    if not notes:
        parts.append('<p class="row">No notes</p>')
    for note in notes[:limit]:
        text = str(note.get("text") or "")
        if len(text) > _NOTE_MAX_CHARS:
            text = text[: _NOTE_MAX_CHARS - 3] + "..."
        parts.append(f'<p class="row">{_esc(text)}</p>')
    parts.append("</div>")
    return "".join(parts)


def _render_lupin_line(config: dict, data: EinkData) -> str:
    text = config.get("text")
    if not (isinstance(text, str) and text.strip()):
        text = data.lupin_line
    if not (isinstance(text, str) and text.strip()):
        return '<div class="t"></div>'
    return f'<div class="t"><p class="mid">&ldquo;{_esc(text)}&rdquo;</p></div>'


_RENDERERS: dict[str, Callable[[dict, EinkData], str]] = {
    "clock": _render_clock,
    "today": _render_today,
    "calendar": _render_calendar,
    "weather": _render_weather,
    "notes": _render_notes,
    "tasks": _render_tasks,
    "checklist": _render_tasks,
    "lupin_line": _render_lupin_line,
}


def render_widget(widget: dict, data: EinkData) -> str | None:
    """Return the escaped inner HTML of one tile, or None for a widget this page does not show.

    Never raises: a renderer failure becomes a small "Unavailable" tile.
    """
    if not isinstance(widget, dict):
        return None
    widget_type = widget.get("type")
    if not isinstance(widget_type, str) or widget_type not in EINK_WIDGET_TYPES:
        return None
    try:
        return _RENDERERS[widget_type](_config_of(widget), data)
    except Exception:
        logger.warning("E-ink widget '%s' could not be rendered.", widget_type, exc_info=True)
        return _unavailable()


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

_STYLE = """
html, body { background: #fff; color: #000; margin: 0; padding: 0; }
body { font-family: Georgia, serif; font-size: 22px; padding: 8px; -webkit-box-sizing: border-box; box-sizing: border-box; }
#grid { position: relative; width: 100%; }
.w { position: absolute; border: 2px solid #000; overflow: hidden; -webkit-box-sizing: border-box; box-sizing: border-box; padding: 8px; }
h2 { font-size: 22px; font-weight: bold; margin: 0 0 6px 0; }
p { margin: 0 0 4px 0; }
.big { font-size: 64px; font-weight: bold; }
.mid { font-size: 30px; }
.row { font-size: 22px; }
.time { font-weight: bold; margin-right: 12px; }
.foot { font-size: 18px; color: #555; margin-top: 8px; }
"""


def _grid_size(layout: dict, orientation: str, widgets: list[dict]) -> tuple[int, int]:
    """Return (cols, rows) from the layout's grid; derive any missing or invalid axis."""
    declared = None
    grid = layout.get("grid")
    if isinstance(grid, dict) and isinstance(grid.get(orientation), dict):
        declared = grid[orientation]
    cols = declared.get("cols") if declared is not None else None
    rows = declared.get("rows") if declared is not None else None

    valid_cols = _is_int(cols) and cols >= 1
    valid_rows = _is_int(rows) and rows >= 1
    if valid_cols and valid_rows:
        return cols, rows

    spans = [
        widget
        for widget in widgets
        if all(_is_int(widget.get(key)) for key in ("x", "y", "w", "h"))
    ]
    derived_cols = max([widget["x"] + widget["w"] for widget in spans] + [1])
    derived_rows = max([widget["y"] + widget["h"] for widget in spans] + [1])
    return (cols if valid_cols else derived_cols, rows if valid_rows else derived_rows)


def _pages_of(layout: Any) -> list[dict]:
    raw_pages = layout.get("pages") if isinstance(layout, dict) else None
    return [page for page in raw_pages if isinstance(page, dict)] if isinstance(raw_pages, list) else []


def render_page(
    layout: dict,
    *,
    page_id: str | None,
    orientation: str,
    data: EinkData,
    refresh_minutes: int = DEFAULT_REFRESH_MINUTES,
    refresh_url: str = "",
) -> str:
    """Return the full E-ink HTML document for one page of a Layout."""
    layout = layout if isinstance(layout, dict) else {}
    pages = _pages_of(layout)

    page_index = 0
    for index, page in enumerate(pages):
        if page_id is not None and page.get("id") == page_id:
            page_index = index
            break
    page = pages[page_index] if pages else {}

    raw_widgets = page.get(orientation)
    widgets = [w for w in raw_widgets if isinstance(w, dict)] if isinstance(raw_widgets, list) else []
    cols, rows = _grid_size(layout, orientation, widgets)

    tiles: list[str] = []
    for widget in widgets:
        x, y, w, h = (widget.get(key) for key in ("x", "y", "w", "h"))
        if not all(_is_int(value) for value in (x, y, w, h)):
            continue
        if x < 0 or y < 0 or w < 1 or h < 1:
            continue
        inner = render_widget(widget, data)
        if inner is None:
            continue
        tiles.append(
            '<div class="w" style="position:absolute;'
            f"left:{_pct(100 * x / cols)}%;top:{_pct(100 * y / rows)}%;"
            f'width:{_pct(100 * w / cols)}%;height:{_pct(100 * h / rows)}%">'
            f"{inner}</div>"
        )

    seconds = clamp_refresh_minutes(refresh_minutes) * 60
    refresh_target = str(refresh_url or "")
    if refresh_target:
        refresh_content = f"{seconds};url={_esc(refresh_target)}"
    else:
        refresh_content = str(seconds)

    layout_name = layout.get("name")
    title = _esc(layout_name) if isinstance(layout_name, str) and layout_name.strip() else "Panel"

    try:
        updated = _hhmm(data.now)
    except Exception:
        updated = "--:--"

    footer_parts = [_esc(page.get("title") or page.get("id") or "")]
    footer_parts.append(f"Updated {updated}")
    if len(pages) > 1:
        footer_parts.append(f"Page {page_index + 1} of {len(pages)}")
    footer = " &middot; ".join(part for part in footer_parts if part)

    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta http-equiv="refresh" content="{refresh_content}">\n'
        f"<title>{title}</title>\n"
        f"<style>{_STYLE}</style>\n"
        "</head>\n"
        "<body>\n"
        f'<div id="grid" style="position:relative;width:100%;height:{rows * _CELL_PX}px">'
        + "".join(tiles)
        + "</div>\n"
        f'<div class="foot">{footer}</div>\n'
        "</body>\n"
        "</html>\n"
    )


# ---------------------------------------------------------------------------
# Route: GET /eink (data gathering and wiring). Nothing here calls an LLM: the Today and
# Lupin lines are deterministic, so calendar and email contents never reach a provider
# through this page. The data only travels to the Kindle on the trusted LAN.
# ---------------------------------------------------------------------------

_DEFAULT_ORIENTATION = "portrait"


def _pick_orientation(requested: str | None, device: dict | None) -> str:
    if requested in ("portrait", "landscape"):
        return str(requested)
    screen = (device or {}).get("screen")
    if isinstance(screen, dict) and screen.get("orientation") in ("portrait", "landscape"):
        return str(screen["orientation"])
    return _DEFAULT_ORIENTATION


def _next_page_id(layout: dict, page_id: str | None) -> str | None:
    """The page after ``page_id`` (wrapping), or None when the layout has a single page."""
    ids = [p.get("id") for p in _pages_of(layout)]
    ids = [i for i in ids if isinstance(i, str)]
    if len(ids) < 2:
        return None
    current = ids.index(page_id) if page_id in ids else 0
    return ids[(current + 1) % len(ids)]


def _error_page(message: str) -> str:
    return (
        '<!doctype html><html><head><meta charset="utf-8"><title>Panel</title></head>'
        f'<body style="font-family:Georgia,serif;font-size:24px;padding:24px">{_esc(message)}</body></html>'
    )


def register(app: Any) -> None:
    """Register GET /eink. Reads stores lazily from ``app.state`` (layouts, device_store, ...)."""
    import asyncio
    from urllib.parse import quote

    from fastapi import Query
    from fastapi.responses import HTMLResponse

    from app.today import build_deterministic_fallback

    state = app.state

    def _today_summary() -> dict | None:
        cowork = getattr(state, "cowork", None)
        if cowork is None:
            return None
        loaded = cowork.load_state()
        if not loaded.get("workspace_exists"):
            return None
        today_iso = datetime.now().date().isoformat()
        return build_deterministic_fallback(loaded, today_iso)

    def _gather(types: set[str], now: datetime) -> EinkData:
        data = EinkData(now=now)
        mac = getattr(state, "mac", None)
        settings = getattr(state, "settings", None)
        if "calendar" in types and mac is not None:
            try:
                data.calendar = mac.read_today_calendar()
            except Exception:
                logger.warning("E-ink: could not read the calendar.")
        if "weather" in types and mac is not None and settings is not None:
            try:
                data.weather = mac.get_weather(
                    settings.weather_latitude, settings.weather_longitude, settings.weather_city
                )
            except Exception:
                logger.warning("E-ink: could not read the weather.")
        if types & {"today", "lupin_line"}:
            try:
                data.today = _today_summary()
            except Exception:
                logger.warning("E-ink: could not build Today.")
            if isinstance(data.today, dict):
                data.lupin_line = str(data.today.get("headline") or "")
        productivity = getattr(state, "productivity", None)
        store = getattr(productivity, "store", None)
        if store is not None:
            if types & {"tasks", "checklist"}:
                try:
                    data.tasks = store.list_tasks()
                except Exception:
                    logger.warning("E-ink: could not read tasks.")
            if "notes" in types:
                try:
                    data.notes = store.list_notes()
                except Exception:
                    logger.warning("E-ink: could not read notes.")
        return data

    @app.get("/eink", response_class=HTMLResponse)
    async def eink_page(
        device: str | None = Query(default=None, max_length=64),
        layout: str | None = Query(default=None, max_length=80),
        page: str | None = Query(default=None, max_length=32),
        orientation: str | None = Query(default=None, max_length=16),
        refresh: str | None = Query(default=None, max_length=8),
    ) -> HTMLResponse:
        headers = {"Cache-Control": "no-store"}
        device_record = None
        device_store = getattr(state, "device_store", None)
        if device and device_store is not None:
            device_record = device_store.get(device)
            if device_record is not None:
                # A Kindle that opens the page counts as seen (no role change here).
                try:
                    device_store.touch(device)
                except Exception:
                    pass
        layouts = getattr(state, "layouts", None)
        if layouts is None:
            return HTMLResponse(_error_page("Panels are not available."), 503, headers)
        layout_id = layout or (device_record or {}).get("layout_id") or "default"
        document = layouts.get(layout_id)
        if not isinstance(document, dict):
            return HTMLResponse(_error_page("Unknown layout."), 404, headers)

        resolved = _pick_orientation(orientation, device_record)
        minutes = clamp_refresh_minutes(refresh)
        pages = _pages_of(document)
        current = next((p for p in pages if page is not None and p.get("id") == page), pages[0] if pages else {})
        types = widget_types_on_page(current, resolved)

        now = datetime.now()
        data = await asyncio.to_thread(_gather, types, now)

        # The refresh moves on to the next page, so a multi-page Layout rotates by itself.
        query = [f"refresh={minutes}"]
        if device:
            query.insert(0, f"device={quote(device, safe='')}")
        if layout:
            query.append(f"layout={quote(layout_id, safe='')}")
        if orientation in ("portrait", "landscape"):
            query.append(f"orientation={resolved}")
        next_page = _next_page_id(document, current.get("id"))
        if next_page:
            query.append(f"page={quote(next_page, safe='')}")
        body = render_page(
            document,
            page_id=current.get("id"),
            orientation=resolved,
            data=data,
            refresh_minutes=minutes,
            refresh_url="/eink?" + "&".join(query),
        )
        return HTMLResponse(body, headers=headers)
