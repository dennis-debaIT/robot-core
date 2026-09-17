from importlib import import_module

from app.skills.base import SkillContext

mod = import_module("app.skills.140_robot")


class FakeCore:
    def __init__(self, query_reply=None, command_reply=None):
        self._query_reply = query_reply
        self._command_reply = command_reply
        self.query_calls = 0
        self.command_calls = 0

    def _try_robot_query(self, captured):
        self.query_calls += 1
        return self._query_reply

    def _try_robot_command(self, captured):
        self.command_calls += 1
        return self._command_reply


def test_robot_skill_prefers_query_over_command():
    core = FakeCore(query_reply="Der Staubsauger ist im Ladedock.", command_reply="Staubsauger fährt jetzt los.")
    ctx = SkillContext(message="wo ist der staubsauger", captured="wo ist der staubsauger", person_name=None, core=core)
    reply, extra = mod.SKILL.handle(ctx)
    assert reply == "Der Staubsauger ist im Ladedock."
    assert extra is None
    assert core.query_calls == 1
    assert core.command_calls == 1  # "or" wertet beide aus wie im Original


def test_robot_skill_falls_back_to_command():
    core = FakeCore(query_reply=None, command_reply="Staubsauger fährt jetzt los.")
    ctx = SkillContext(message="starte den staubsauger", captured="starte den staubsauger", person_name=None, core=core)
    reply, _extra = mod.SKILL.handle(ctx)
    assert reply == "Staubsauger fährt jetzt los."


def test_robot_skill_metadata_reason_is_robot_command():
    assert mod.SKILL.reason == "robot_command"
