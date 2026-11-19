"""Time of day and Now Playing as tone (Lupin 04). Pure functions.

Time of day drives Energy (sleepy late at night, brighter in the morning). Now Playing only
nudges the tone (calmer or livelier) and never triggers speech. Only the tone word reaches
the LLM, never the title or artist.
"""

from __future__ import annotations

from typing import Any

# (first hour, last hour) -> target energy 0-100.
_ENERGY_BY_HOUR: tuple[tuple[int, int, int], ...] = (
    (0, 5, 20),
    (6, 8, 80),
    (9, 11, 90),
    (12, 17, 70),
    (18, 21, 55),
    (22, 23, 35),
)
TIME_WEIGHT = 0.6  # how much the time of day pulls Energy away from the stored value

_CALM_WORDS = (
    "ambient", "classical", "jazz", "lofi", "lo-fi", "chill", "acoustic", "piano",
    "sleep", "instrumental", "new age", "meditation", "bossa",
)
_LIVELY_WORDS = (
    "rock", "pop", "dance", "electronic", "edm", "house", "techno", "hip hop", "hip-hop",
    "rap", "metal", "punk", "funk", "samba", "forro", "reggaeton", "disco",
)
CALM_BPM = 90
LIVELY_BPM = 125


def time_of_day_energy(hour: int) -> int:
    for first, last, energy in _ENERGY_BY_HOUR:
        if first <= hour <= last:
            return energy
    return 70


def effective_energy(stored: float, hour: int) -> float:
    """Blend the stored Energy with the time-of-day target."""
    target = time_of_day_energy(hour)
    return round(max(0.0, min(100.0, (1 - TIME_WEIGHT) * stored + TIME_WEIGHT * target)), 2)


def music_tone(now_playing: dict[str, Any] | None) -> str | None:
    """"calm", "lively" or None, from the genre and tempo of what is playing right now."""
    if not now_playing or not now_playing.get("playing"):
        return None
    genre = str(now_playing.get("genre") or "").lower()
    if any(word in genre for word in _CALM_WORDS):
        return "calm"
    if any(word in genre for word in _LIVELY_WORDS):
        return "lively"
    bpm = now_playing.get("bpm")
    if isinstance(bpm, (int, float)):
        if bpm < CALM_BPM:
            return "calm"
        if bpm >= LIVELY_BPM:
            return "lively"
    return None
