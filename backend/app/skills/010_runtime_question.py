"""Eigenstatus-Fragen (Akku, Update, Display, Gerätezustand)."""
from app.skills.base import Skill, SkillContext


def _handle(ctx: SkillContext):
    return ctx.core._try_answer_runtime_question(ctx.captured), None


SKILL = Skill(name="runtime_question", reason="core_direct_answer", can_handle=lambda ctx: True, handle=_handle)
