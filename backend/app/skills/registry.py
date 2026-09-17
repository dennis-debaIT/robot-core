"""Lädt alle Skill-Module aus app/skills/ automatisch beim ersten Zugriff.

Jede Datei außer base.py/registry.py/__init__.py wird importiert und muss ein
Modul-Level SKILL = Skill(...) definieren. Reihenfolge: alphabetisch nach
Dateiname — die migrierten Skills tragen deshalb ein zweistelliges Präfix
(10_..., 20_...), das die bisherige Reihenfolge aus robot_core.py nachbildet.

Ein einzelner kaputter Skill (Importfehler, fehlendes SKILL) darf die App nie
zum Absturz bringen — er wird übersprungen und landet als Warnung im
Audit-Log, genau wie die übrigen "nie stillschweigend verschlucken"-Fixes.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

from app.skills.base import Skill

if TYPE_CHECKING:
    pass

_SKIP_MODULES = {"base", "registry", "__init__"}

_cache: list[Skill] | None = None


def _load_skills() -> list[Skill]:
    import app.skills as _skills_pkg
    skills: list[Skill] = []
    for _finder, name, _is_pkg in sorted(pkgutil.iter_modules(_skills_pkg.__path__), key=lambda m: m[1]):
        if name in _SKIP_MODULES:
            continue
        try:
            mod = importlib.import_module(f"app.skills.{name}")
        except Exception as exc:
            from app.audit.service import AuditService
            AuditService().log_warn(source="skills", message=f"Skill-Modul '{name}' konnte nicht geladen werden: {type(exc).__name__}: {exc}")
            continue
        skill = getattr(mod, "SKILL", None)
        if skill is None or not isinstance(skill, Skill):
            from app.audit.service import AuditService
            AuditService().log_warn(source="skills", message=f"Skill-Modul '{name}' hat kein gültiges SKILL-Objekt definiert — übersprungen.")
            continue
        skills.append(skill)
    return skills


def get_skills() -> list[Skill]:
    """Gecachte, sortierte Liste aller erfolgreich geladenen Skills.
    Wird beim ersten Aufruf gebaut (z.B. beim ersten Chat nach dem Start)."""
    global _cache
    if _cache is None:
        _cache = _load_skills()
    return _cache


def reload_skills() -> list[Skill]:
    """Erzwingt einen Neuaufbau — nützlich für Tests."""
    global _cache
    _cache = None
    return get_skills()
