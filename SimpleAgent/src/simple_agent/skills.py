"""Discover and progressively load local Agent Skills.

Each search path is a directory of skill directories. Earlier search paths have
priority, so callers can put project-level paths before user-level paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

import yaml


class SkillError(ValueError):
    """A skill or one of its resources could not be loaded."""


def _frontmatter(path: Path) -> dict:
    """Read just the YAML header, leaving instructions for activation time."""
    try:
        with path.open(encoding="utf-8-sig") as file:
            if file.readline().strip() != "---":
                raise SkillError("missing opening YAML frontmatter delimiter")
            lines: list[str] = []
            size = 0
            for line in file:
                if line.strip() == "---":
                    break
                lines.append(line)
                size += len(line)
                if size > 65536:
                    raise SkillError("YAML frontmatter exceeds 64 KiB")
            else:
                raise SkillError("missing closing YAML frontmatter delimiter")
        metadata = yaml.safe_load("".join(lines))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise SkillError(str(exc)) from exc
    if not isinstance(metadata, dict):
        raise SkillError("YAML frontmatter must be a mapping")
    return metadata


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path

    def load(self) -> str:
        """Return the complete instructions and their directory for references."""
        try:
            text = self.path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise SkillError(f"Cannot load skill {self.name}: {exc}") from exc
        return (f"Skill: {self.name}\nSkill directory: {self.path.parent}\n"
                f"Resolve relative resource paths from this directory.\n\n{text}")

    def read_resource(self, relative_path: str) -> str:
        """Read a UTF-8 resource inside this skill; reject traversal/symlinks out."""
        root = self.path.parent.resolve()
        if Path(relative_path).is_absolute():
            raise SkillError("Resource path must be relative to the skill directory")
        candidate = (root / relative_path).resolve()
        if candidate == root or not candidate.is_relative_to(root):
            raise SkillError("Resource must be a file inside the skill directory")
        try:
            return candidate.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise SkillError(f"Cannot read skill resource {relative_path}: {exc}") from exc


def discover_skills(paths: Iterable[Path]) -> tuple[dict[str, Skill], list[str]]:
    """Return skills by name and diagnostics; first search path wins collisions.

    Invalid/missing descriptions and unparseable metadata are skipped. Other
    naming violations are warnings, following the client integration guidance.
    """
    skills: dict[str, Skill] = {}
    warnings: list[str] = []
    for root in paths:
        root = Path(root).expanduser()
        if not root.exists():
            continue
        try:
            children = sorted(root.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            warnings.append(f"{root}: {exc}")
            continue
        for directory in children:
            path = directory / "SKILL.md"
            if not directory.is_dir() or not path.is_file():
                continue
            try:
                metadata = _frontmatter(path)
                name, description = metadata.get("name"), metadata.get("description")
                if not isinstance(name, str) or not name.strip():
                    raise SkillError("name must be a non-empty string")
                if not isinstance(description, str) or not description.strip():
                    raise SkillError("description must be a non-empty string")
                name, description = name.strip(), description.strip()
                if len(name) > 64 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
                    warnings.append(f"{path}: name does not follow Agent Skills naming rules")
                if name != directory.name:
                    warnings.append(f"{path}: name does not match directory name")
                if len(description) > 1024:
                    warnings.append(f"{path}: description exceeds 1024 characters")
                if name in skills:
                    warnings.append(f"{path}: skill {name!r} is shadowed by {skills[name].path}")
                    continue
                skills[name] = Skill(name, description, path.resolve())
            except SkillError as exc:
                warnings.append(f"{path}: {exc}")
    return skills, warnings
