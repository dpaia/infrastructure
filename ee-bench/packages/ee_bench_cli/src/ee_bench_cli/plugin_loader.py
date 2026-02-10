"""Shared logic to parse config and build provider/generator instances.

Handles both singular (``provider:``) and plural (``providers:``) config formats.
"""

from __future__ import annotations

from typing import Any

from ee_bench_generator import (
    CompositeProvider,
    GeneratorSpec,
    load_generator,
    load_provider,
)
from ee_bench_generator.interfaces import Generator, Provider


def build_provider_from_config(
    config: dict[str, Any],
) -> tuple[Provider, dict[str, Any]]:
    """Build a provider (possibly composite) from config.

    Supports two config formats:

    **Singular** (``provider:`` key)::

        provider:
          name: huggingface_dataset    # acts as both identifier and type
          options: { ... }

        # or flat:
        provider: huggingface_dataset
        provider_options: { ... }

    **Plural** (``providers:`` key)::

        providers:
          - name: swe_bench_data
            type: huggingface_dataset
            role: primary
            options: { ... }
          - name: upstream_prs
            type: github_pull_requests
            item_mapping:
              owner: "{{ providers.swe_bench_data.repo | split('/') | first }}"
            options: { ... }

    Args:
        config: Parsed configuration dictionary.

    Returns:
        Tuple of (Provider instance, provider_options dict).
        For singular: provider_options is a flat dict.
        For composite: provider_options is keyed by provider instance name.
    """
    if "providers" in config:
        return _build_composite_provider(config)
    return _build_single_provider(config)


def _build_single_provider(
    config: dict[str, Any],
) -> tuple[Provider, dict[str, Any]]:
    """Build a single provider from singular config format."""
    provider_config = config.get("provider")

    if isinstance(provider_config, dict):
        provider_name = provider_config.get("name")
        provider_options = dict(provider_config.get("options", {}))
    else:
        provider_name = provider_config
        provider_options = {}

    if not provider_name:
        raise ValueError("Provider name is required in config.")

    # Merge flat provider_options into nested options (flat overrides nested)
    flat_options = config.get("provider_options", {})
    if flat_options:
        provider_options = {**provider_options, **flat_options}

    provider = load_provider(provider_name)
    return provider, provider_options


def _build_composite_provider(
    config: dict[str, Any],
) -> tuple[Provider, dict[str, Any]]:
    """Build a CompositeProvider from plural config format."""
    providers_list = config["providers"]

    provider_configs: list[dict[str, Any]] = []
    provider_options: dict[str, dict[str, Any]] = {}

    for entry in providers_list:
        name = entry["name"]
        plugin_type = entry.get("type", name)
        role = entry.get("role")
        item_mapping = entry.get("item_mapping", {})
        options = dict(entry.get("options", {}))

        provider_instance = load_provider(plugin_type)

        cfg: dict[str, Any] = {
            "name": name,
            "provider": provider_instance,
        }
        if role:
            cfg["role"] = role
        if item_mapping:
            cfg["item_mapping"] = item_mapping

        provider_configs.append(cfg)
        provider_options[name] = options

    composite = CompositeProvider(provider_configs)
    return composite, provider_options


def build_generators_from_config(
    config: dict[str, Any],
) -> list[GeneratorSpec]:
    """Build generator spec(s) from config.

    Supports two config formats:

    **Singular** (``generator:`` key)::

        generator:
          name: github_pr_importer
          options: { ... }
        output:
          format: jsonl
          path: results/out.jsonl

    **Plural** (``generators:`` key)::

        generators:
          - name: pr_import
            type: github_pr_importer
            options: { ... }
            output:
              format: jsonl
              path: results/import.jsonl
          - name: dataset_export
            type: dpaia_jvm
            options: {}
            output:
              format: jsonl
              path: datasets/export.jsonl

    Args:
        config: Parsed configuration dictionary.

    Returns:
        List of GeneratorSpec instances.
    """
    if "generators" in config:
        return _build_multiple_generators(config)
    return [_build_single_generator(config)]


def _build_single_generator(config: dict[str, Any]) -> GeneratorSpec:
    """Build a single GeneratorSpec from singular config format."""
    generator_config = config.get("generator")

    if isinstance(generator_config, dict):
        generator_name = generator_config.get("name")
        generator_options = dict(generator_config.get("options", {}))
    else:
        generator_name = generator_config
        generator_options = {}

    if not generator_name:
        raise ValueError("Generator name is required in config.")

    # Merge flat generator_options into nested options (flat overrides nested)
    flat_options = config.get("generator_options", {})
    if flat_options:
        generator_options = {**generator_options, **flat_options}

    generator = load_generator(generator_name)
    output_config = dict(config.get("output", {}))

    return GeneratorSpec(
        name=generator_name,
        generator=generator,
        options=generator_options,
        output_config=output_config,
    )


def _build_multiple_generators(config: dict[str, Any]) -> list[GeneratorSpec]:
    """Build multiple GeneratorSpecs from plural config format."""
    generators_list = config["generators"]
    specs: list[GeneratorSpec] = []

    for entry in generators_list:
        name = entry["name"]
        plugin_type = entry.get("type", name)
        options = dict(entry.get("options", {}))
        output_config = dict(entry.get("output", {}))

        generator_instance = load_generator(plugin_type)

        specs.append(
            GeneratorSpec(
                name=name,
                generator=generator_instance,
                options=options,
                output_config=output_config,
            )
        )

    return specs
