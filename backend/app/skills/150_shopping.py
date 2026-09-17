"""Einkaufsliste per Sprache/Text pflegen."""
from app.skills.base import Skill, SkillContext


def _handle(ctx: SkillContext):
    return ctx.core._try_shopping_command(ctx.captured), None


SKILL = Skill(name="shopping", reason="shopping_command", can_handle=lambda ctx: True, handle=_handle)
