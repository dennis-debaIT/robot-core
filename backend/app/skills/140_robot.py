"""Saugroboter/Mähroboter-Status und -Befehle (Fragen und Aktionen gebündelt,
wie im Original-Code: robot_reply = _try_robot_query(...) or _try_robot_command(...))."""
from app.skills.base import Skill, SkillContext


def _handle(ctx: SkillContext):
    reply = ctx.core._try_robot_query(ctx.captured) or ctx.core._try_robot_command(ctx.captured)
    return reply, None


SKILL = Skill(name="robot", reason="robot_command", can_handle=lambda ctx: True, handle=_handle)
