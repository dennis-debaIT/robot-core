"""Notizen speichern/suchen/löschen/auflisten."""
from app.skills.base import Skill, SkillContext


def _handle(ctx: SkillContext):
    return ctx.core._try_note_command(ctx.captured, ctx.person_name), None


SKILL = Skill(name="note", reason="core_direct_answer", can_handle=lambda ctx: True, handle=_handle)
