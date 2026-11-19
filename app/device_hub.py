"""Hub for connected Bodies and Panels: picks the Active Body and routes WebSocket messages.

Every WebSocket connection gets one entry in ``DeviceHub.entries``. A connection that
says hello with a valid ``device_id`` is backed by a record in the DeviceStore (its
roles, name, layout and body priority); a legacy client without one gets a Body-only
entry with no store record, which keeps the pre-device behaviour.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from app.actions import CURRENT_CALLER, ActionRegistry
from app.devices import DEVICE_ID_RE, DeviceStore

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
HANDLED_TYPES = frozenset({"subscribe", "unsubscribe", "action"})

# Legacy tie-breaker between Bodies with no user priority; other kinds count as 1.
_KIND_RANK = {"esp32": 3, "rg406h-web": 2}
_DEFAULT_KIND_RANK = 1

# Kinds a legacy hello used for Bodies. A device first seen with one of these keeps its
# Body role (stored as Body + Panel); any other new device starts as a Panel only.
LEGACY_BODY_KINDS = frozenset({"esp32", "rg406h-web", "web"})

_TOPIC_RE = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,63}")
_MAX_TOPICS = 64

Send = Callable[[dict[str, Any]], Awaitable[Any]]


def _roles(entry: dict[str, Any]) -> list[str]:
    """Roles of an entry; entries without a roles key are legacy Bodies."""
    roles = entry.get("roles")
    return list(roles) if isinstance(roles, list) else ["body"]


def _rank_key(entry: dict[str, Any]) -> tuple[bool, int, int, int]:
    """Sort key for choosing the Active Body: user priority, then kind rank, then newest hello."""
    priority = entry.get("priority")
    kind_rank = _KIND_RANK.get(entry.get("body"), _DEFAULT_KIND_RANK)
    return (priority is not None, -(priority or 0), kind_rank, entry.get("seq", 0))


def _store_fields(record: dict[str, Any]) -> dict[str, Any]:
    """The fields of a store record that an entry mirrors."""
    return {
        "name": record["name"],
        "roles": list(record["roles"]),
        "layout_id": record["layout_id"],
        "priority": record["body_priority"],
    }


class DeviceHub:
    """Tracks open connections, the Active Body, and topic subscriptions."""

    def __init__(self, store: DeviceStore, actions: ActionRegistry) -> None:
        self.store = store
        self.actions = actions
        # Public and shared: main.py exposes this same list as app.state.bodies.
        self.entries: list[dict[str, Any]] = []
        self._seq = 0

    # ------------------------------------------------------------------
    # Active Body
    # ------------------------------------------------------------------

    def current_active_body(self) -> dict[str, Any] | None:
        """Return the entry that should run Lupin, or None when no Body is connected."""
        bodies = [entry for entry in self.entries if "body" in _roles(entry)]
        if not bodies:
            return None
        return max(bodies, key=_rank_key)

    def _contains(self, entry: dict[str, Any]) -> bool:
        return any(item is entry for item in self.entries)

    def _remove(self, entry: dict[str, Any]) -> None:
        # Slice assignment keeps the list object, which app.state.bodies shares.
        self.entries[:] = [item for item in self.entries if item is not entry]

    async def announce_active_body(
        self, previous: dict[str, Any] | None, skip: dict[str, Any] | None
    ) -> None:
        """Tell every connection (except ``skip``) when the Active Body changed."""
        active = self.current_active_body()
        if active is previous:
            return
        for entry in list(self.entries):
            if entry is skip:
                continue
            if active is None:
                message = {"type": "active_body", "active_body": None, "active": False}
            else:
                message = {
                    "type": "active_body",
                    "active_body": active["body"],
                    "active": entry is active,
                }
            try:
                await entry["send"](message)
            except Exception:
                logger.info("Body %s did not receive the Active Body notice.", entry.get("body"))

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def hello(self, body_info: dict[str, Any], data: dict[str, Any], send: Send) -> None:
        """Register a connection on hello and send it the welcome message."""
        kind = str(data.get("body") or "unknown")
        audio_formats = data.get("audio")
        wants_audio = isinstance(audio_formats, list) and len(audio_formats) > 0
        body_info["body"] = kind
        body_info["wants_audio"] = wants_audio

        previous = self.current_active_body()
        old_entry = body_info.get("entry")
        if old_entry is not None:
            self._remove(old_entry)

        raw_name = data.get("name")
        name = raw_name if isinstance(raw_name, str) else ""
        raw_screen = data.get("screen")
        screen = raw_screen if isinstance(raw_screen, dict) else None
        device_id = data.get("device_id")

        self._seq += 1
        entry: dict[str, Any]
        if kind == "editor":
            # Layout editor live preview is an ephemeral read-only subscriber, never a device or Body.
            entry = {
                "body": kind,
                "device_id": None,
                "name": name,
                "roles": [],
                "layout_id": None,
                "priority": None,
                "seq": self._seq,
                "send": send,
                "wants_audio": False,
                "topics": set(),
                "screen": {},
            }
        elif isinstance(device_id, str) and DEVICE_ID_RE.match(device_id):
            record = self.store.upsert_hello(
                device_id,
                name=name,
                kind=kind,
                screen=screen,
                default_roles=["body", "panel"] if kind in LEGACY_BODY_KINDS else ["panel"],
            )
            entry = {
                "body": kind,
                "device_id": device_id,
                **_store_fields(record),
                "seq": self._seq,
                "send": send,
                "wants_audio": wants_audio,
                "topics": set(),
                "screen": record["screen"],
            }
        else:
            entry = {
                "body": kind,
                "device_id": None,
                "name": name,
                "roles": ["body"],
                "layout_id": None,
                "priority": None,
                "seq": self._seq,
                "send": send,
                "wants_audio": wants_audio,
                "topics": set(),
                "screen": screen or {},
            }

        self.entries.append(entry)
        body_info["entry"] = entry

        active = self.current_active_body()
        if active is not None:
            active_body = active["body"]
        else:
            active_body = kind if "body" in entry["roles"] else None
        welcome: dict[str, Any] = {
            "type": "welcome",
            "protocol": PROTOCOL_VERSION,
            "active_body": active_body,
            "active": active is entry,
        }
        if entry["device_id"] is not None:
            welcome.update(
                {
                    "device_id": entry["device_id"],
                    "name": entry["name"],
                    "roles": entry["roles"],
                    "layout_id": entry["layout_id"],
                }
            )
        await send(welcome)
        await self.announce_active_body(previous, skip=entry)

    async def disconnect(self, entry: dict[str, Any] | None) -> None:
        """Remove a closed connection and announce any Active Body change."""
        if entry is None or not self._contains(entry):
            return
        previous = self.current_active_body()
        self._remove(entry)
        await self.announce_active_body(previous, skip=None)

    async def device_changed(self, device_id: str | None = None) -> None:
        """Re-read store records into open connections after a roles, name, layout or priority edit."""
        previous = self.current_active_body()
        changed: list[dict[str, Any]] = []
        for entry in list(self.entries):
            entry_device_id = entry.get("device_id")
            if entry_device_id is None:
                continue
            if device_id is not None and entry_device_id != device_id:
                continue
            record = self.store.get(entry_device_id)
            if record is None:
                continue
            fields = _store_fields(record)
            if any(entry.get(key) != value for key, value in fields.items()):
                entry.update(fields)
                changed.append(entry)

        active = self.current_active_body()
        for entry in changed:
            message = {
                "type": "role",
                "device_id": entry["device_id"],
                "name": entry["name"],
                "roles": entry["roles"],
                "layout_id": entry["layout_id"],
                "active": entry is active,
            }
            try:
                await entry["send"](message)
            except Exception:
                logger.info("Device %s did not receive the role change.", entry["device_id"])
        await self.announce_active_body(previous, skip=None)

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def handle_message(
        self, entry: dict[str, Any] | None, data: dict[str, Any], send: Send
    ) -> bool:
        """Handle a message this hub owns. Returns False for any other message type."""
        msg_type = data.get("type")
        if not isinstance(msg_type, str) or msg_type not in HANDLED_TYPES:
            return False

        if msg_type == "action":
            token = CURRENT_CALLER.set(entry)
            try:
                reply = await self.actions.run(data.get("id"), data.get("args"))
            finally:
                CURRENT_CALLER.reset(token)
            await send(reply)
            return True

        if entry is None:
            await send({"type": "error", "message": "Send hello first."})
            return True

        topics = data.get("topics")
        if not isinstance(topics, list):
            await send({"type": "error", "message": "topics must be a list."})
            return True

        subscribed = entry.setdefault("topics", set())
        for topic in topics:
            if not isinstance(topic, str) or not _TOPIC_RE.fullmatch(topic):
                continue
            if msg_type == "subscribe":
                if topic in subscribed or len(subscribed) < _MAX_TOPICS:
                    subscribed.add(topic)
            else:
                subscribed.discard(topic)

        await send({"type": "subscribed", "topics": sorted(subscribed)})
        return True

    async def publish(self, topic: str, payload: Any) -> int:
        """Send a topic message to every connection subscribed to it; return how many got it."""
        delivered = 0
        for entry in list(self.entries):
            if topic not in (entry.get("topics") or ()):
                continue
            try:
                await entry["send"]({"type": "topic", "topic": topic, "data": payload})
                delivered += 1
            except Exception:
                logger.info("Topic %s was not delivered to a connection.", topic)
        return delivered
