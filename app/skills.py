"""Catalog of the agent's skills and the pet's interactive tricks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app import speech
from app.memory import MemoryStore

_META_KEY_ENABLED_SKILLS = "pet_skills_enabled"


@dataclass(frozen=True, slots=True)
class SkillPack:
    """Modular pack of instructions and capabilities injectable into the system prompt."""

    id: str
    icon: str
    name: str
    description: str
    default_enabled: bool

    @property
    def voice_hint(self) -> str:
        return speech.SKILL_VOICE_HINTS[self.id]

    @property
    def prompt_instruction(self) -> str:
        return speech.SKILL_PROMPT_INSTRUCTIONS[self.id]


@dataclass(frozen=True, slots=True)
class PetTrick:
    """Physical/audiovisual pet trick triggered from the UI or by an `[action:pet:<id>]` tag."""

    id: str
    icon: str
    name: str
    description: str
    emotion: str
    duration_ms: int

    @property
    def voice_hint(self) -> str:
        return speech.TRICK_VOICE_HINTS[self.id]


SKILL_PACKS: tuple[SkillPack, ...] = (
    SkillPack(
        id="focus_coach",
        icon="🎯",
        name="Focus Coach",
        description="Helps start Pomodoro sessions, keep focus blocks and suggest short breaks.",
        default_enabled=True,
    ),
    SkillPack(
        id="daily_briefing",
        icon="☀️",
        name="Daily Briefing",
        description="Combines time of day, weather and Cowork Today priorities into concise summaries.",
        default_enabled=True,
    ),
    SkillPack(
        id="coding_buddy",
        icon="💻",
        name="Coding Buddy",
        description="Helps with debugging, architecture and quick inspection of the screen or clipboard.",
        default_enabled=True,
    ),
    SkillPack(
        id="wellness_breaks",
        icon="🧘",
        name="Wellness & Breaks",
        description="Gentle reminders for hydration, posture, the 20-20-20 rule and guided breathing.",
        default_enabled=False,
    ),
    SkillPack(
        id="playful_companion",
        icon="✨",
        name="Playful Pet",
        description="Enables expressive tricks such as dancing, singing, celebrating, stretching and napping.",
        default_enabled=True,
    ),
)

PET_TRICKS: tuple[PetTrick, ...] = (
    PetTrick(
        id="dance",
        icon="💃",
        name="Dance",
        description="Rhythmic sequence of little hops, sparkling eyes and confetti.",
        emotion="excited",
        duration_ms=2800,
    ),
    PetTrick(
        id="sing",
        icon="🎵",
        name="Sing",
        description="Procedural Web Audio melody with floating musical notes.",
        emotion="happy",
        duration_ms=3000,
    ),
    PetTrick(
        id="meditate",
        icon="🧘",
        name="Meditate",
        description="Calm breathing and a zen rhythm to go with breaks.",
        emotion="love",
        duration_ms=3400,
    ),
    PetTrick(
        id="nap",
        icon="😴",
        name="Nap",
        description="Cozy nap with Zzz particles and slow breathing.",
        emotion="sleepy",
        duration_ms=3400,
    ),
    PetTrick(
        id="celebrate",
        icon="🎉",
        name="Celebrate",
        description="Lively celebration with a sound fanfare and a shower of particles.",
        emotion="excited",
        duration_ms=2600,
    ),
    PetTrick(
        id="stretch",
        icon="🤸",
        name="Stretch",
        description="Elastic squash-and-stretch to recharge energy.",
        emotion="happy",
        duration_ms=2400,
    ),
)

_PACKS_BY_ID: dict[str, SkillPack] = {pack.id: pack for pack in SKILL_PACKS}
_TRICKS_BY_ID: dict[str, PetTrick] = {trick.id: trick for trick in PET_TRICKS}


def default_enabled_skill_ids() -> list[str]:
    """Return the IDs of the skills enabled by default."""
    return [pack.id for pack in SKILL_PACKS if pack.default_enabled]


def load_enabled_skills(memory: MemoryStore) -> list[str]:
    """Load the list of active skills from SQLite (`app_meta`), with a safe fallback."""
    raw = memory.get_meta(_META_KEY_ENABLED_SKILLS)
    if not raw:
        return default_enabled_skill_ids()
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return default_enabled_skill_ids()
        valid = [str(item) for item in parsed if isinstance(item, str) and item in _PACKS_BY_ID]
        return valid
    except json.JSONDecodeError:
        return default_enabled_skill_ids()


def set_skill_enabled(memory: MemoryStore, skill_id: str, enabled: bool) -> list[str]:
    """Enable or disable a skill by ID and persist it in SQLite (`app_meta`)."""
    cleaned = skill_id.strip().lower()
    if cleaned not in _PACKS_BY_ID:
        raise ValueError(f"Unknown skill: '{skill_id}'.")

    current = load_enabled_skills(memory)
    current_set = set(current)
    if enabled:
        current_set.add(cleaned)
    else:
        current_set.discard(cleaned)

    ordered = [pack.id for pack in SKILL_PACKS if pack.id in current_set]
    memory.set_meta(_META_KEY_ENABLED_SKILLS, json.dumps(ordered, ensure_ascii=False))
    return ordered


def get_trick(trick_id: str) -> PetTrick | None:
    """Return the `PetTrick` for the identifier, if it exists."""
    return _TRICKS_BY_ID.get(trick_id.strip().lower())


def list_skills_payload(enabled_ids: list[str]) -> dict[str, Any]:
    """Serialize the skill packs and pet tricks for the REST API."""
    enabled_set = set(enabled_ids)
    return {
        "enabled_ids": [pack.id for pack in SKILL_PACKS if pack.id in enabled_set],
        "packs": [
            {
                "id": pack.id,
                "icon": pack.icon,
                "name": pack.name,
                "description": pack.description,
                "voice_hint": pack.voice_hint,
                "enabled": pack.id in enabled_set,
            }
            for pack in SKILL_PACKS
        ],
        "tricks": [
            {
                "id": trick.id,
                "icon": trick.icon,
                "name": trick.name,
                "description": trick.description,
                "voice_hint": trick.voice_hint,
                "emotion": trick.emotion,
                "duration_ms": trick.duration_ms,
            }
            for trick in PET_TRICKS
        ],
    }


def build_skills_prompt(enabled_ids: list[str]) -> str:
    """Build the active-skills context block for the LLM system prompt."""
    enabled_set = set(enabled_ids)
    lines = [
        _PACKS_BY_ID[pack.id].prompt_instruction
        for pack in SKILL_PACKS
        if pack.id in enabled_set
    ]
    if not lines:
        return ""
    tricks_list = ", ".join(trick.id for trick in PET_TRICKS)
    lines.append(speech.PET_TRICKS_PROMPT_LINE.format(tricks_list=tricks_list))
    return "\n".join(f"- {line}" for line in lines)
