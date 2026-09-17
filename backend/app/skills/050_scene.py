"""Lichtszenen aktivieren ('aktiviere die Szene Abendlicht')."""
from app.skills.base import Skill, SkillContext


def _handle(ctx: SkillContext):
    return ctx.core._try_scene_command(ctx.captured), None


SKILL = Skill(name="scene", reason="core_direct_answer", can_handle=lambda ctx: True, handle=_handle)
