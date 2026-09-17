"""'Was haben wir heute besprochen' — Tages-Gesprächsthemen."""
from app.skills.base import Skill, SkillContext


def _handle(ctx: SkillContext):
    return ctx.core._try_conversation_summary(ctx.captured, ctx.person_name), None


SKILL = Skill(name="conversation_summary", reason="core_direct_answer", can_handle=lambda ctx: True, handle=_handle)
