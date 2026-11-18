from pathlib import Path

import pytest

from simple_agent.skills import SkillError, discover_skills


def make_skill(root: Path, name: str, description: str = "A useful skill") -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\nInstructions here.\n",
        encoding="utf-8",
    )
    return directory


def test_discovery_precedence_and_lazy_loading(tmp_path: Path) -> None:
    project, user = tmp_path / "project", tmp_path / "user"
    directory = make_skill(project, "example")
    make_skill(user, "example", "User skill")
    skills, warnings = discover_skills([project, user])
    assert skills["example"].description == "A useful skill"
    assert "shadowed" in warnings[0]
    (directory / "SKILL.md").write_text("Changed after discovery", encoding="utf-8")
    assert "Changed after discovery" in skills["example"].load()


def test_invalid_skill_produces_diagnostic_and_other_skills_load(tmp_path: Path) -> None:
    make_skill(tmp_path, "good")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: bad\ndescription: [\n---\n", encoding="utf-8")
    skills, warnings = discover_skills([tmp_path])
    assert list(skills) == ["good"]
    assert len(warnings) == 1
    assert "bad" in warnings[0]


def test_resource_reads_are_confined_to_skill_directory(tmp_path: Path) -> None:
    directory = make_skill(tmp_path / "skills", "example")
    (directory / "references").mkdir()
    (directory / "references" / "guide.md").write_text("guide", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    skill = discover_skills([tmp_path / "skills"])[0]["example"]
    assert skill.read_resource("references/guide.md") == "guide"
    with pytest.raises(SkillError):
        skill.read_resource("../../secret.txt")
    with pytest.raises(SkillError):
        skill.read_resource(str(outside))
