from importlib import import_module

from app.skills.base import SkillContext

mod = import_module("app.skills.040_light_command")


class FakeCore:
    def __init__(self, reply):
        self._reply = reply
        self.intent_calls = 0

    def _try_light_command(self, captured):
        return self._reply

    def _set_lights_display_intent(self):
        self.intent_calls += 1


def test_light_command_success_sets_display_intent():
    core = FakeCore("Licht ist jetzt aus.")
    ctx = SkillContext(message="mach das licht aus", captured="mach das licht aus", person_name=None, core=core)
    reply, extra = mod.SKILL.handle(ctx)
    assert reply == "Licht ist jetzt aus."
    assert extra is None
    assert core.intent_calls == 1


def test_light_command_no_match_skips_display_intent():
    core = FakeCore(None)
    ctx = SkillContext(message="wie spät ist es", captured="wie spät ist es", person_name=None, core=core)
    reply, extra = mod.SKILL.handle(ctx)
    assert reply is None
    assert core.intent_calls == 0


def test_light_command_skill_metadata():
    assert mod.SKILL.name == "light_command"
    assert mod.SKILL.reason == "core_direct_answer"
