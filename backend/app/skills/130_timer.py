"""Timer setzen/auflisten/umbenennen/abbrechen/quittieren."""
from app.skills.base import Skill, SkillContext


def _handle(ctx: SkillContext):
    return ctx.core._try_timer_command(ctx.captured), None


SKILL = Skill(name="timer", reason="core_direct_answer", can_handle=lambda ctx: True, handle=_handle)
