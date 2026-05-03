from __future__ import annotations

from pathlib import Path

from mindbot.skills import (
    ScriptDefinition,
    SkillLoader,
    SkillRoot,
    SkillSelector,
    parse_flat_skill_markdown,
    parse_skill_markdown,
)


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


def _write_flat_skill(root: Path, name: str, description: str, when_to_use: str) -> Path:
    """Write a flat .md skill file."""
    skill_file = root / f"{name}.md"
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
                "Flat skill body.",
            ]
        ),
        encoding="utf-8",
    )
    return skill_file


def test_parse_flat_skill_markdown_uses_filename_as_default_name(tmp_path: Path) -> None:
    """Flat skills use filename stem as default name."""
    skill_file = _write_flat_skill(tmp_path, "my-flat-skill", "Flat desc", "Flat trigger")

    skill = parse_flat_skill_markdown(skill_file, loaded_from="user")

    assert skill.name == "my-flat-skill"
    assert skill.description == "Flat desc"
    assert skill.when_to_use == "Flat trigger"
    assert skill.skill_dir == tmp_path


def test_parse_flat_skill_markdown_respects_frontmatter_name(tmp_path: Path) -> None:
    """Frontmatter name overrides filename."""
    skill_file = tmp_path / "filename.md"
    skill_file.write_text(
        "---\nname: frontmatter-name\ndescription: test\n---\n\nBody",
        encoding="utf-8",
    )

    skill = parse_flat_skill_markdown(skill_file, loaded_from="user")

    assert skill.name == "frontmatter-name"


def test_scan_discovers_flat_skills(tmp_path: Path) -> None:
    """Scan should discover flat .md skills."""
    _write_flat_skill(tmp_path, "flat-one", "Flat skill one", "Use one")
    _write_flat_skill(tmp_path, "flat-two", "Flat skill two", "Use two")

    loader = SkillLoader([SkillRoot(path=tmp_path, loaded_from="user")])
    skills = loader.scan()

    names = {s.name for s in skills}
    assert "flat-one" in names
    assert "flat-two" in names


def test_scan_subdir_wins_over_flat_same_name(tmp_path: Path) -> None:
    """Subdirectory skill wins over flat skill with same name."""
    # Create subdirectory skill
    _write_skill(tmp_path, "shared", "subdir description", "subdir trigger")
    # Create flat skill with same name
    _write_flat_skill(tmp_path, "shared", "flat description", "flat trigger")

    loader = SkillLoader([SkillRoot(path=tmp_path, loaded_from="user")])
    registry = loader.load_registry()

    skill = registry.require("shared")
    assert skill.description == "subdir description"


def test_scan_skips_toplevel_skill_md(tmp_path: Path) -> None:
    """Top-level SKILL.md marker file should be skipped."""
    marker = tmp_path / "SKILL.md"
    marker.write_text("---\nname: marker\n---\n\nShould be ignored", encoding="utf-8")

    loader = SkillLoader([SkillRoot(path=tmp_path, loaded_from="user")])
    skills = loader.scan()

    names = {s.name for s in skills}
    assert "marker" not in names


def _write_skill_with_scripts(
    root: Path,
    name: str,
    description: str,
    scripts: dict[str, str] | None = None,
) -> Path:
    """Write a skill with optional scripts directory."""
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "---",
                "",
                f"# {name}",
            ]
        ),
        encoding="utf-8",
    )

    if scripts:
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        for script_name, script_content in scripts.items():
            script_file = scripts_dir / script_name
            script_file.write_text(script_content, encoding="utf-8")
            script_file.chmod(0o755)

    return skill_file


def test_skill_discovers_scripts(tmp_path: Path) -> None:
    """Skill should discover scripts in scripts/ directory."""
    _write_skill_with_scripts(
        tmp_path,
        "my-skill",
        "A skill with scripts",
        scripts={
            "process.py": "#!/usr/bin/env python3\nprint('hello')",
            "validate.sh": "#!/bin/bash\necho 'valid'",
        },
    )

    loader = SkillLoader([SkillRoot(path=tmp_path, loaded_from="user")])
    registry = loader.load_registry()

    skill = registry.require("my-skill")
    assert len(skill.scripts) == 2

    script_names = {s.name for s in skill.scripts}
    assert "process" in script_names
    assert "validate" in script_names


def test_script_definition_detects_language(tmp_path: Path) -> None:
    """ScriptDefinition should detect language from extension."""
    script_file = tmp_path / "test.py"
    script_file.write_text("print('hello')", encoding="utf-8")

    script = ScriptDefinition.from_file(script_file)

    assert script.name == "test"
    assert script.language == "python"
    assert script.entrypoint == "python {path}"


def test_skill_get_script(tmp_path: Path) -> None:
    """SkillDefinition.get_script should return script by name."""
    _write_skill_with_scripts(
        tmp_path,
        "test-skill",
        "Test",
        scripts={"helper.py": "print('hi')"},
    )

    loader = SkillLoader([SkillRoot(path=tmp_path, loaded_from="user")])
    skill = loader.scan()[0]

    script = skill.get_script("helper")
    assert script is not None
    assert script.name == "helper"
    assert script.language == "python"

    assert skill.get_script("nonexistent") is None


def test_skill_ignores_hidden_scripts(tmp_path: Path) -> None:
    """Hidden files in scripts/ should be ignored."""
    _write_skill_with_scripts(
        tmp_path,
        "test-skill",
        "Test",
        scripts={
            ".hidden.py": "print('hidden')",
            "visible.py": "print('visible')",
        },
    )

    loader = SkillLoader([SkillRoot(path=tmp_path, loaded_from="user")])
    skill = loader.scan()[0]

    script_names = {s.name for s in skill.scripts}
    assert "visible" in script_names
    assert ".hidden" not in script_names

