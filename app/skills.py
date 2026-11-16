"""Catálogo de habilidades (Skills) do agente e truques interativos do pet."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.memory import MemoryStore

_META_KEY_ENABLED_SKILLS = "pet_skills_enabled"


@dataclass(frozen=True, slots=True)
class SkillPack:
    """Pacote modular de instruções e capacidades injetáveis no system prompt."""

    id: str
    icon: str
    name: str
    description: str
    voice_hint: str
    default_enabled: bool
    prompt_instruction: str


@dataclass(frozen=True, slots=True)
class PetTrick:
    """Truque físico/audiovisual do pet acionável por UI ou tag `[action:pet:<id>]`."""

    id: str
    icon: str
    name: str
    description: str
    voice_hint: str
    emotion: str
    duration_ms: int


SKILL_PACKS: tuple[SkillPack, ...] = (
    SkillPack(
        id="focus_coach",
        icon="🎯",
        name="Coach de Foco",
        description="Ajuda a iniciar sessões Pomodoro, manter blocos de foco e sugerir pausas curtas.",
        voice_hint='"bora focar 25 min" / "inicia um pomodoro"',
        default_enabled=True,
        prompt_instruction=(
            "Skill Coach de Foco ativa: incentive blocos de trabalho focado e, quando o usuário "
            "pedir para focar ou iniciar Pomodoro, emita [action:pomodoro:start] (ou [action:pomodoro:stop])."
        ),
    ),
    SkillPack(
        id="daily_briefing",
        icon="☀️",
        name="Briefing Diário",
        description="Combina hora do dia, clima e prioridades do Cowork Today em resumos objetivos.",
        voice_hint='"como está meu dia?" / "resumo de hoje"',
        default_enabled=True,
        prompt_instruction=(
            "Skill Briefing Diário ativa: ao ser perguntado sobre o dia, agenda ou prioridades, "
            "consulte o contexto do Cowork/clima e, se útil, emita [action:today:brief]."
        ),
    ),
    SkillPack(
        id="coding_buddy",
        icon="💻",
        name="Parceiro de Código",
        description="Auxilia em debugging, arquitetura e inspeção rápida da tela ou clipboard.",
        voice_hint='"olha minha tela" / "resume o que copiei"',
        default_enabled=True,
        prompt_instruction=(
            "Skill Parceiro de Código ativa: dê respostas técnicas diretas e concisas; use "
            "[action:vision:screen] ou [action:vision:clipboard] quando o usuário pedir para olhar tela/clipboard."
        ),
    ),
    SkillPack(
        id="wellness_breaks",
        icon="🧘",
        name="Bem-Estar & Pausas",
        description="Lembretes gentis de hidratação, postura, regra 20-20-20 e respiração guiada.",
        voice_hint='"vamos respirar" / "preciso alongar"',
        default_enabled=False,
        prompt_instruction=(
            "Skill Bem-Estar & Pausas ativa: sugira pausas breves de água, postura e respiração "
            "quando notar cansaço, podendo acionar [action:pet:meditate] ou [action:pet:stretch]."
        ),
    ),
    SkillPack(
        id="playful_companion",
        icon="✨",
        name="Pet Brincalhão",
        description="Habilita truques expressivos como dançar, cantar, celebrar, espreguiçar e cochilar.",
        voice_hint='"faz uma dancinha" / "canta pra mim"',
        default_enabled=True,
        prompt_instruction=(
            "Skill Pet Brincalhão ativa: reaja com carisma e use [action:pet:dance], "
            "[action:pet:sing], [action:pet:celebrate], [action:pet:meditate], [action:pet:stretch] "
            "ou [action:pet:nap] quando combinar com o pedido do usuário."
        ),
    ),
)

PET_TRICKS: tuple[PetTrick, ...] = (
    PetTrick(
        id="dance",
        icon="💃",
        name="Dançar",
        description="Sequência rítmica de saltinhos, brilho nos olhos e confetes.",
        voice_hint='"faz uma dancinha"',
        emotion="excited",
        duration_ms=2800,
    ),
    PetTrick(
        id="sing",
        icon="🎵",
        name="Cantar",
        description="Melodia procedural em Web Audio com notas musicais flutuantes.",
        voice_hint='"canta uma música"',
        emotion="happy",
        duration_ms=3000,
    ),
    PetTrick(
        id="meditate",
        icon="🧘",
        name="Meditar",
        description="Respiração calma e ritmo zen para acompanhar pausas.",
        voice_hint='"medita comigo"',
        emotion="love",
        duration_ms=3400,
    ),
    PetTrick(
        id="nap",
        icon="😴",
        name="Cochilar",
        description="Soneca aconchegante com partículas Zzz e respiração lenta.",
        voice_hint='"tira um cochilo"',
        emotion="sleepy",
        duration_ms=3400,
    ),
    PetTrick(
        id="celebrate",
        icon="🎉",
        name="Celebrar",
        description="Comemoração animada com fanfarra sonora e chuva de partículas.",
        voice_hint='"comemora!"',
        emotion="excited",
        duration_ms=2600,
    ),
    PetTrick(
        id="stretch",
        icon="🤸",
        name="Espreguiçar",
        description="Alongamento elástico (squash-and-stretch) para recarregar energia.",
        voice_hint='"se espreguiça"',
        emotion="happy",
        duration_ms=2400,
    ),
)

_PACKS_BY_ID: dict[str, SkillPack] = {pack.id: pack for pack in SKILL_PACKS}
_TRICKS_BY_ID: dict[str, PetTrick] = {trick.id: trick for trick in PET_TRICKS}


def default_enabled_skill_ids() -> list[str]:
    """Retorna os IDs das skills habilitadas por padrão."""
    return [pack.id for pack in SKILL_PACKS if pack.default_enabled]


def load_enabled_skills(memory: MemoryStore) -> list[str]:
    """Carrega do SQLite (`app_meta`) a lista de skills ativas, com fallback seguro."""
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
    """Ativa ou desativa uma skill por ID e persiste no SQLite (`app_meta`)."""
    cleaned = skill_id.strip().lower()
    if cleaned not in _PACKS_BY_ID:
        raise ValueError(f"Skill desconhecida: '{skill_id}'.")

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
    """Retorna o `PetTrick` correspondente ao identificador, se existir."""
    return _TRICKS_BY_ID.get(trick_id.strip().lower())


def list_skills_payload(enabled_ids: list[str]) -> dict[str, Any]:
    """Serializa pacotes de skills e truques do pet para a API REST."""
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
    """Gera o bloco de contexto de skills ativas para o system prompt do LLM."""
    enabled_set = set(enabled_ids)
    lines = [
        _PACKS_BY_ID[pack.id].prompt_instruction
        for pack in SKILL_PACKS
        if pack.id in enabled_set
    ]
    if not lines:
        return ""
    tricks_list = ", ".join(trick.id for trick in PET_TRICKS)
    lines.append(f"Truques físicos disponíveis via [action:pet:<nome>]: {tricks_list}.")
    return "\n".join(f"- {line}" for line in lines)
