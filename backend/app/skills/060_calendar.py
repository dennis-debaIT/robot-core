"""Kalendertermin per Sprache/Text anlegen."""
from app.skills.base import Skill, SkillContext


def _handle(ctx: SkillContext):
    return ctx.core._try_calendar_command(ctx.captured, ctx.person_name), None


SKILL = Skill(name="calendar", reason="core_direct_answer", can_handle=lambda ctx: True, handle=_handle)
