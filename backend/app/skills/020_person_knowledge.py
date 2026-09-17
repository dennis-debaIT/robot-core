"""'Was weißt du über X' / 'Erzähle mir etwas über X'."""
from app.skills.base import Skill, SkillContext


def _handle(ctx: SkillContext):
    return ctx.core._try_answer_person_knowledge_question(ctx.captured), None


SKILL = Skill(name="person_knowledge", reason="core_direct_answer", can_handle=lambda ctx: True, handle=_handle)
