from pathlib import Path

from eval_readiness.config import (
    ResolvedReadiness,
    UnsupportedReadiness,
    load_eval_projects,
    load_readiness_config,
    resolve_readiness,
)


ROOT = Path(__file__).resolve().parents[3]


def test_eval_projects_loads_eval_readiness_project() -> None:
    config = load_eval_projects(ROOT / ".github/config/eval-projects.json")

    assert config.organization == "dpaia"
    assert config.dataset_metadata_project == "3"
    assert config.eval_readiness_project == "17"
    assert config.eval_projects["codegen"] == "13"
    assert config.eval_projects["methodgen"] == "16"


def test_enabled_codegen_java_resolves() -> None:
    config = load_readiness_config(ROOT / ".github/config/eval-readiness.json")

    resolved = resolve_readiness(config, "codegen", ["REST", "Language: Java"])

    assert isinstance(resolved, ResolvedReadiness)
    assert resolved.profile.eval_type == "codegen"
    assert resolved.language.label == "Language: Java"
    assert resolved.language.teamcity_dataset_id == "Dpai-Bench"
    assert resolved.hf_path == "code-generation-swe/java/dpai-java-instances.large"


def test_disabled_methodgen_is_unsupported() -> None:
    config = load_readiness_config(ROOT / ".github/config/eval-readiness.json")

    resolved = resolve_readiness(config, "methodgen", ["Language: Java"])

    assert isinstance(resolved, UnsupportedReadiness)
    assert resolved.reason == "disabled_profile"


def test_missing_language_is_unsupported() -> None:
    config = load_readiness_config(ROOT / ".github/config/eval-readiness.json")

    resolved = resolve_readiness(config, "codegen", ["REST", "Spring"])

    assert isinstance(resolved, UnsupportedReadiness)
    assert resolved.reason == "missing_language"


def test_duplicate_supported_language_labels_are_unsupported() -> None:
    config = load_readiness_config(ROOT / ".github/config/eval-readiness.json")

    resolved = resolve_readiness(config, "codegen", ["Language: Java", "Language: C#"])

    assert isinstance(resolved, UnsupportedReadiness)
    assert resolved.reason == "duplicate_language"


def test_missing_profile_is_unsupported() -> None:
    config = load_readiness_config(ROOT / ".github/config/eval-readiness.json")

    resolved = resolve_readiness(config, "debugging", ["Language: Java"])

    assert isinstance(resolved, UnsupportedReadiness)
    assert resolved.reason == "missing_profile"
