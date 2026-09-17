"""Sofortiger Lichtbefehl ('mach das Licht aus')."""
from app.skills.base import Skill, SkillContext


def _handle(ctx: SkillContext):
    reply = ctx.core._try_light_command(ctx.captured)
    if reply:
        ctx.core._set_lights_display_intent()
    return reply, None


SKILL = Skill(name="light_command", reason="core_direct_answer", can_handle=lambda ctx: True, handle=_handle)
