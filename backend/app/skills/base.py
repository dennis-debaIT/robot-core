"""Gemeinsame Typen für das Skill-System.

Ein Skill ist ein eigenständiges Modul unter app/skills/, das eine
Modul-Ebene-Variable SKILL = Skill(...) definiert. registry.py lädt alle
Module automatisch beim Start (siehe dort) — neue Fähigkeiten brauchen keinen
Eingriff in robot_core.py, nur eine neue Datei hier.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from app.integrations.robot_core import RobotCore


@dataclass
class SkillContext:
    message: str            # Rohtext der Nutzeräußerung
    captured: str            # normalisierter Text (microphone.capture_text)
    person_name: str | None
    core: "RobotCore"        # Zugriff auf geteilte Services (core.profile, core.memory, ...)


@dataclass
class Skill:
    name: str                                                       # eindeutiger Bezeichner, z.B. "calendar"
    reason: str                                                      # response_reason für die API-Antwort
    can_handle: Callable[[SkillContext], bool]
    handle: Callable[[SkillContext], tuple[str | None, Any | None]]  # (reply, extra) — extra meist None
