"""Zeitversetzter Lichtbefehl ('schalte um 20 Uhr das Licht aus')."""
from app.skills.base import Skill, SkillContext


def _handle(ctx: SkillContext):
    return ctx.core._try_light_schedule_command(ctx.captured, ctx.person_name), None


SKILL = Skill(name="light_schedule", reason="core_direct_answer", can_handle=lambda ctx: True, handle=_handle)
