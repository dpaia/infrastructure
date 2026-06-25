from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_EVAL_PROJECTS_PATH = Path(".github/config/eval-projects.json")
DEFAULT_READINESS_PATH = Path(".github/config/eval-readiness.json")


class ConfigError(ValueError):
    """Raised when eval-readiness config is structurally invalid."""


@dataclass(frozen=True)
class EvalProjectsConfig:
    organization: str
    dataset_metadata_project: str
    eval_readiness_project: str
    eval_projects: Mapping[str, str]


@dataclass(frozen=True)
class ReadinessProfile:
    eval_type: str
    enabled: bool
    hf_dataset: str
    hf_base_path: str
    generator_kind: str
    registration_bucket: str


@dataclass(frozen=True)
class LanguageMapping:
    label: str
    hf_dir: str
    hf_filename: str
    pipeline_language_enum: str
    teamcity_dataset_id: str


@dataclass(frozen=True)
class ReadinessConfig:
    profiles: Mapping[str, ReadinessProfile]
    languages: Mapping[str, LanguageMapping]


@dataclass(frozen=True)
class ResolvedReadiness:
    profile: ReadinessProfile
    language: LanguageMapping

    @property
    def hf_path(self) -> str:
        return str(
            PurePosixPath(self.profile.hf_base_path)
            / self.language.hf_dir
            / self.language.hf_filename
        )


@dataclass(frozen=True)
class UnsupportedReadiness:
    reason: str
    detail: str


def load_eval_projects(path: Path = DEFAULT_EVAL_PROJECTS_PATH) -> EvalProjectsConfig:
    raw = _read_json_object(path)
    organization = _required_string(raw, "organization", path)
    dataset_metadata_project = _required_project_number(raw, "dataset_metadata_project", path)
    eval_readiness_project = _required_project_number(raw, "eval_readiness_project", path)
    eval_projects_raw = raw.get("eval_projects")
    if not isinstance(eval_projects_raw, dict) or not eval_projects_raw:
        raise ConfigError(f"{path}: eval_projects must be a non-empty object")

    eval_projects: dict[str, str] = {}
    for eval_type, project_number in eval_projects_raw.items():
        if not isinstance(eval_type, str) or not eval_type:
            raise ConfigError(f"{path}: eval_projects keys must be non-empty strings")
        eval_projects[eval_type] = _coerce_project_number(project_number, f"eval_projects.{eval_type}", path)

    return EvalProjectsConfig(
        organization=organization,
        dataset_metadata_project=dataset_metadata_project,
        eval_readiness_project=eval_readiness_project,
        eval_projects=eval_projects,
    )


def load_readiness_config(path: Path = DEFAULT_READINESS_PATH) -> ReadinessConfig:
    raw = _read_json_object(path)
    profiles_raw = raw.get("profiles")
    if not isinstance(profiles_raw, dict) or not profiles_raw:
        raise ConfigError(f"{path}: profiles must be a non-empty object")
    languages_raw = raw.get("languages")
    if not isinstance(languages_raw, dict) or not languages_raw:
        raise ConfigError(f"{path}: languages must be a non-empty object")

    profiles: dict[str, ReadinessProfile] = {}
    for eval_type, profile_raw in profiles_raw.items():
        if not isinstance(eval_type, str) or not eval_type:
            raise ConfigError(f"{path}: profiles keys must be non-empty strings")
        if not isinstance(profile_raw, dict):
            raise ConfigError(f"{path}: profiles.{eval_type} must be an object")
        profiles[eval_type] = ReadinessProfile(
            eval_type=eval_type,
            enabled=_required_bool(profile_raw, "enabled", path, f"profiles.{eval_type}"),
            hf_dataset=_required_string(profile_raw, "hf_dataset", path, f"profiles.{eval_type}"),
            hf_base_path=_required_string(profile_raw, "hf_base_path", path, f"profiles.{eval_type}"),
            generator_kind=_required_string(profile_raw, "generator_kind", path, f"profiles.{eval_type}"),
            registration_bucket=_required_string(profile_raw, "registration_bucket", path, f"profiles.{eval_type}"),
        )

    languages: dict[str, LanguageMapping] = {}
    for label, language_raw in languages_raw.items():
        if not isinstance(label, str) or not label.startswith("Language: "):
            raise ConfigError(f"{path}: language keys must be labels like 'Language: Java'")
        if not isinstance(language_raw, dict):
            raise ConfigError(f"{path}: languages.{label} must be an object")
        languages[label] = LanguageMapping(
            label=label,
            hf_dir=_required_string(language_raw, "hf_dir", path, f"languages.{label}"),
            hf_filename=_required_string(language_raw, "hf_filename", path, f"languages.{label}"),
            pipeline_language_enum=_required_string(
                language_raw, "pipeline_language_enum", path, f"languages.{label}"
            ),
            teamcity_dataset_id=_required_string(language_raw, "teamcity_dataset_id", path, f"languages.{label}"),
        )

    return ReadinessConfig(profiles=profiles, languages=languages)


def resolve_readiness(
    config: ReadinessConfig,
    eval_type: str,
    labels: Iterable[str],
) -> ResolvedReadiness | UnsupportedReadiness:
    profile = config.profiles.get(eval_type)
    if profile is None:
        return UnsupportedReadiness("missing_profile", f"No eval-readiness profile for eval type '{eval_type}'")
    if not profile.enabled:
        return UnsupportedReadiness("disabled_profile", f"Eval-readiness profile '{eval_type}' is disabled")

    supported_language_labels = sorted(label for label in labels if label in config.languages)
    if not supported_language_labels:
        return UnsupportedReadiness(
            "missing_language",
            "No supported language label found; expected one of: " + ", ".join(sorted(config.languages)),
        )
    if len(supported_language_labels) > 1:
        return UnsupportedReadiness(
            "duplicate_language",
            "Multiple supported language labels found: " + ", ".join(supported_language_labels),
        )

    return ResolvedReadiness(profile=profile, language=config.languages[supported_language_labels[0]])


def _read_json_object(path: Path) -> Mapping[str, Any]:
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(f"{path}: file does not exist") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected JSON object")
    return raw


def _required_project_number(raw: Mapping[str, Any], key: str, path: Path) -> str:
    return _coerce_project_number(raw.get(key), key, path)


def _coerce_project_number(value: Any, key: str, path: Path) -> str:
    if isinstance(value, int) and value > 0:
        return str(value)
    if isinstance(value, str) and value.isdecimal() and int(value) > 0:
        return value
    raise ConfigError(f"{path}: {key} must be a positive project number")


def _required_string(raw: Mapping[str, Any], key: str, path: Path, prefix: str | None = None) -> str:
    value = raw.get(key)
    if isinstance(value, str) and value:
        return value
    display_key = f"{prefix}.{key}" if prefix else key
    raise ConfigError(f"{path}: {display_key} must be a non-empty string")


def _required_bool(raw: Mapping[str, Any], key: str, path: Path, prefix: str) -> bool:
    value = raw.get(key)
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{path}: {prefix}.{key} must be a boolean")
