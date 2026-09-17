"""Fahrzeug-Status (Akku, Reichweite, Ladezustand)."""
from app.skills.base import Skill, SkillContext


def _handle(ctx: SkillContext):
    return ctx.core._try_vehicle_query(ctx.captured), None


SKILL = Skill(name="vehicle", reason="core_direct_answer", can_handle=lambda ctx: True, handle=_handle)
