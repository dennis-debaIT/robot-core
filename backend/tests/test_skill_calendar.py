from importlib import import_module

from app.skills.base import SkillContext

mod = import_module("app.skills.060_calendar")


class FakeCore:
    def __init__(self, reply):
        self._reply = reply
        self.seen_args = None

    def _try_calendar_command(self, captured, person_name):
        self.seen_args = (captured, person_name)
        return self._reply


def test_calendar_skill_forwards_captured_and_person_name():
    core = FakeCore("Termin 'Zahnarzt' wurde für Montag eingetragen.")
    ctx = SkillContext(
        message="trage einen Termin Zahnarzt für Montag ein",
        captured="trage einen termin zahnarzt für montag ein",
        person_name="Dennis",
        core=core,
    )
    reply, extra = mod.SKILL.handle(ctx)
    assert reply == "Termin 'Zahnarzt' wurde für Montag eingetragen."
    assert extra is None
    assert core.seen_args == ("trage einen termin zahnarzt für montag ein", "Dennis")


def test_calendar_skill_no_match_returns_none():
    core = FakeCore(None)
    ctx = SkillContext(message="wie ist das wetter", captured="wie ist das wetter", person_name=None, core=core)
    reply, _extra = mod.SKILL.handle(ctx)
    assert reply is None
