from app.skills import registry as mod
from app.skills.base import Skill, SkillContext

EXPECTED_ORDER = [
    "runtime_question", "person_knowledge", "light_schedule", "light_command",
    "scene", "calendar", "vehicle", "pv", "conversation_summary", "summary",
    "reminder", "note", "timer", "robot", "shopping",
]


def test_get_skills_finds_all_migrated_skills_in_order():
    skills = mod.reload_skills()
    names = [s.name for s in skills]
    assert names == EXPECTED_ORDER


def test_broken_skill_import_is_skipped_not_raised(monkeypatch, temp_db):
    """Ein Skill-Modul, das beim Import crasht, darf den Loader nicht mitreißen —
    andere Skills müssen trotzdem geladen werden (graceful degradation)."""

    def fake_iter_modules(_path):
        return [
            (None, "010_runtime_question", False),
            (None, "does_not_exist_at_all", False),
        ]

    monkeypatch.setattr(mod.pkgutil, "iter_modules", fake_iter_modules)
    skills = mod._load_skills()
    assert [s.name for s in skills] == ["runtime_question"]


def test_skill_missing_SKILL_attribute_is_skipped(monkeypatch, temp_db):
    def fake_iter_modules(_path):
        return [(None, "010_runtime_question", False)]

    class _FakeModuleNoSkill:
        pass

    monkeypatch.setattr(mod.pkgutil, "iter_modules", fake_iter_modules)
    monkeypatch.setattr(mod.importlib, "import_module", lambda _name: _FakeModuleNoSkill())
    skills = mod._load_skills()
    assert skills == []


def test_dispatch_stops_at_first_match():
    """Kleine, in-memory Registry: erster can_handle==True gewinnt, danach wird
    nicht mehr weitergemacht."""
    calls = []

    def make_skill(name, matches, reply):
        def can_handle(ctx):
            calls.append(name)
            return matches

        def handle(ctx):
            return reply, None

        return Skill(name=name, reason="core_direct_answer", can_handle=can_handle, handle=handle)

    skills = [
        make_skill("a", False, "A"),
        make_skill("b", True, "B"),
        make_skill("c", True, "C"),
    ]
    ctx = SkillContext(message="hi", captured="hi", person_name=None, core=None)
    winner = None
    for skill in skills:
        if skill.can_handle(ctx):
            reply, _extra = skill.handle(ctx)
            if reply:
                winner = reply
                break
    assert winner == "B"
    assert calls == ["a", "b"]  # "c" wird nie geprüft
