from __future__ import annotations

from pathlib import Path

from mindbot.skills import SkillLoader, SkillRoot, SkillSelector, parse_skill_markdown


def _write_skill(root: Path, name: str, description: str, when_to_use: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                f"when_to_use: {when_to_use}",
                "allowed_tools: ['read_file']",
                "---",
                "",
                f"# {name}",
                "",
                "Use the skill body for detailed guidance.",
            ]
        ),
        encoding="utf-8",
    )
    return skill_file


def test_parse_skill_markdown_reads_frontmatter_and_body(tmp_path: Path) -> None:
    skill_file = _write_skill(
        tmp_path,
        "python-helper",
        "Answers Python questions",
        "Use for Python code help",
    )

    skill = parse_skill_markdown(skill_file, loaded_from="builtin")

    assert skill.name == "python-helper"
    assert skill.description == "Answers Python questions"
    assert skill.when_to_use == "Use for Python code help"
    assert skill.allowed_tools == ["read_file"]
    assert "Use the skill body" in skill.body


def test_loader_registry_prefers_later_root_on_name_conflict(tmp_path: Path) -> None:
    builtin_root = tmp_path / "builtin"
    user_root = tmp_path / "user"
    _write_skill(builtin_root, "shared-skill", "builtin description", "builtin trigger")
    _write_skill(user_root, "shared-skill", "user description", "user trigger")

    loader = SkillLoader(
        [
            SkillRoot(path=builtin_root, loaded_from="builtin"),
            SkillRoot(path=user_root, loaded_from="user"),
        ]
    )

    registry = loader.load_registry()

    assert registry.require("shared-skill").description == "user description"
    assert registry.require("shared-skill").loaded_from == "user"


def test_selector_returns_overview_and_detail_for_metadata_match(tmp_path: Path) -> None:
    builtin_root = tmp_path / "builtin"
    _write_skill(
        builtin_root,
        "python-helper",
        "Answers Python questions",
        "Use for Python code help",
    )
    registry = SkillLoader([SkillRoot(path=builtin_root, loaded_from="builtin")]).load_registry()

    result = SkillSelector(
        registry,
        enabled=True,
        max_visible=5,
        max_detail_load=1,
        trigger_mode="metadata-match",
    ).select("Need help with Python functions")

    assert [summary.name for summary in result.summaries] == ["python-helper"]
    assert [selection.skill_name for selection in result.selections] == ["python-helper"]


def test_selector_explicit_only_requires_skill_name(tmp_path: Path) -> None:
    builtin_root = tmp_path / "builtin"
    _write_skill(
        builtin_root,
        "python-helper",
        "Answers Python questions",
        "Use for Python code help",
    )
    registry = SkillLoader([SkillRoot(path=builtin_root, loaded_from="builtin")]).load_registry()

    result = SkillSelector(
        registry,
        enabled=True,
        always_include=["python-helper"],
        max_visible=5,
        max_detail_load=1,
        trigger_mode="explicit-only",
    ).select("Need help with Python functions")

    assert [summary.name for summary in result.summaries] == ["python-helper"]
    assert result.selections == []

