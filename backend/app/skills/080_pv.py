"""PV-Anlagen-Status (Tagesertrag, aktuelle Leistung)."""
from app.skills.base import Skill, SkillContext


def _handle(ctx: SkillContext):
    return ctx.core._try_pv_query(ctx.captured), None


SKILL = Skill(name="pv", reason="core_direct_answer", can_handle=lambda ctx: True, handle=_handle)
