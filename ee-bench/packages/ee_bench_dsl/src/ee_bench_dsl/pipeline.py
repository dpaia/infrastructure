"""Pipeline builder — the core of the ee_bench DSL."""

from __future__ import annotations

from typing import Any, Callable, Iterator

from ee_bench_generator import (
    CompositeProvider,
    DatasetEngine,
    GeneratorSpec,
    MultiGeneratorRunner,
    Selection,
    load_generator,
    load_provider,
)
from ee_bench_generator.interfaces import Generator, Provider

from ee_bench_dsl.generators import FunctionGenerator
from ee_bench_dsl.output import write_output
from ee_bench_dsl.providers import FunctionProvider


# ---------------------------------------------------------------------------
# Internal bookkeeping dataclasses
# ---------------------------------------------------------------------------

class _ProviderEntry:
    """Internal record of a .provider() call."""

    __slots__ = ("name", "type", "role", "item_mapping", "options", "instance")

    def __init__(
        self,
        name: str,
        *,
        type: str | None = None,
        role: str | None = None,
        item_mapping: dict[str, str] | None = None,
        options: dict[str, Any],
        instance: Provider | None = None,
    ) -> None:
        self.name = name
        self.type = type
        self.role = role
        self.item_mapping = item_mapping or {}
        self.options = options
        self.instance = instance


class _GeneratorEntry:
    """Internal record of a .generator() call."""

    __slots__ = ("name", "type", "output", "options", "instance")

    def __init__(
        self,
        name: str,
        *,
        type: str | None = None,
        output: str | None = None,
        options: dict[str, Any],
        instance: Generator | None = None,
    ) -> None:
        self.name = name
        self.type = type
        self.output = output
        self.options = options
        self.instance = instance


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class Pipeline:
    """Fluent pipeline builder.

    Build a pipeline by chaining ``.provider()``, ``.generator()``, and
    terminal methods (``.run()``, ``.collect()``, ``.iter()``).
    """

    def __init__(self) -> None:
        self._providers: list[_ProviderEntry] = []
        self._generators: list[_GeneratorEntry] = []
        self._selection_resource: str | None = None
        self._selection_filters: dict[str, Any] = {}
        self._selection_limit: int | None = None
        self._defer_validation: bool = False
        self._output_path: str | None = None
        self._output_format: str = "jsonl"
        self._transforms: list[Callable[[dict[str, Any]], dict[str, Any] | None]] = []

    # -- name dedup -----------------------------------------------------------

    def _unique_provider_name(self, base: str) -> str:
        existing = {e.name for e in self._providers}
        if base not in existing:
            return base
        idx = 2
        while f"{base}_{idx}" in existing:
            idx += 1
        return f"{base}_{idx}"

    def _unique_generator_name(self, base: str) -> str:
        existing = {e.name for e in self._generators}
        if base not in existing:
            return base
        idx = 2
        while f"{base}_{idx}" in existing:
            idx += 1
        return f"{base}_{idx}"

    # -- provider -------------------------------------------------------------

    def provider(
        self,
        name_or_instance: str | Provider,
        *,
        type: str | None = None,
        role: str | None = None,
        item_mapping: dict[str, str] | None = None,
        **options: Any,
    ) -> Pipeline:
        """Add a provider to the pipeline.

        When *name_or_instance* is a string and *type* is ``None``, the
        string is treated as the plugin type (single-provider shorthand).

        When *type* is given, *name_or_instance* is the instance identifier
        and *type* names the plugin.

        Passing a :class:`Provider` instance directly is also supported
        (e.g. ``from_items(...)``).
        """
        if isinstance(name_or_instance, Provider):
            base = getattr(name_or_instance, "_name", "inline")
            entry = _ProviderEntry(
                name=self._unique_provider_name(base),
                instance=name_or_instance,
                role=role,
                item_mapping=item_mapping,
                options=options,
            )
        else:
            entry = _ProviderEntry(
                name=name_or_instance,
                type=type,
                role=role,
                item_mapping=item_mapping,
                options=options,
            )
        self._providers.append(entry)
        return self

    # -- generator ------------------------------------------------------------

    def generator(
        self,
        name_or_instance: str | Generator,
        *,
        type: str | None = None,
        output: str | None = None,
        **options: Any,
    ) -> Pipeline:
        """Add a generator to the pipeline.

        When *name_or_instance* is a string and *type* is ``None``, the
        string is treated as the plugin type (single-generator shorthand).

        When *type* is given, *name_or_instance* is the instance identifier
        and *type* names the plugin.

        Passing a :class:`Generator` instance directly is also supported
        (e.g. ``each(fn)``).
        """
        if isinstance(name_or_instance, Generator):
            base = getattr(name_or_instance, "_name", "inline")
            entry = _GeneratorEntry(
                name=self._unique_generator_name(base),
                instance=name_or_instance,
                output=output,
                options=options,
            )
        else:
            entry = _GeneratorEntry(
                name=name_or_instance,
                type=type,
                output=output,
                options=options,
            )
        self._generators.append(entry)
        return self

    def generator_options(self, **kw: Any) -> Pipeline:
        """Merge additional options into the last added generator."""
        if not self._generators:
            raise ValueError("No generator to apply options to")
        self._generators[-1].options.update(kw)
        return self

    # -- selection / filtering ------------------------------------------------

    def select(
        self,
        resource: str,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        **kw_filters: Any,
    ) -> Pipeline:
        """Set the selection criteria.

        Args:
            resource: Resource type (e.g. ``"dataset_items"``).
            filters: Filter dict.
            limit: Max items.
            **kw_filters: Extra filters merged into *filters*.
        """
        self._selection_resource = resource
        self._selection_filters = {**(filters or {}), **kw_filters}
        if limit is not None:
            self._selection_limit = limit
        return self

    def filter(self, **kw: Any) -> Pipeline:
        """Add filters to the current selection."""
        self._selection_filters.update(kw)
        return self

    def limit(self, n: int) -> Pipeline:
        """Set the item limit."""
        self._selection_limit = n
        return self

    # -- transforms -----------------------------------------------------------

    def transform(
        self,
        fn: Callable[[dict[str, Any]], dict[str, Any] | None],
    ) -> Pipeline:
        """Append a post-processing transform.

        *fn* receives each record and returns a (possibly modified) dict.
        Return ``None`` to drop the record.
        """
        self._transforms.append(fn)
        return self

    # -- output ---------------------------------------------------------------

    def output(self, path: str, fmt: str = "jsonl") -> Pipeline:
        """Set the output path and format."""
        self._output_path = path
        self._output_format = fmt
        return self

    # -- validation -----------------------------------------------------------

    def defer_validation(self) -> Pipeline:
        """Defer provider/generator compatibility checks until run time."""
        self._defer_validation = True
        return self

    # -- terminals ------------------------------------------------------------

    def run(self) -> int:
        """Execute the pipeline, write output, return record count."""
        return write_output(
            self._apply_transforms(self._execute()),
            path=self._output_path,
            fmt=self._output_format,
        )

    def iter(self) -> Iterator[dict[str, Any]]:
        """Execute the pipeline and return a record iterator."""
        return self._apply_transforms(self._execute())

    def collect(self) -> list[dict[str, Any]]:
        """Execute the pipeline and return all records as a list."""
        return list(self.iter())

    # -- internal build helpers -----------------------------------------------

    def _build_selection(self) -> Selection:
        return Selection(
            resource=self._selection_resource or "",
            filters=self._selection_filters,
            limit=self._selection_limit,
        )

    def _build_provider(self) -> tuple[Provider, dict[str, Any]]:
        """Resolve provider entries into a Provider + provider_options."""
        if not self._providers:
            raise ValueError("Pipeline has no provider. Call .provider() first.")

        if len(self._providers) == 1:
            return self._build_single_provider(self._providers[0])

        # Multiple providers → CompositeProvider
        return self._build_composite_provider()

    def _build_single_provider(
        self, entry: _ProviderEntry
    ) -> tuple[Provider, dict[str, Any]]:
        if entry.instance is not None:
            prov = entry.instance
        else:
            plugin_type = entry.type or entry.name
            prov = load_provider(plugin_type)
        return prov, entry.options

    def _build_composite_provider(
        self,
    ) -> tuple[Provider, dict[str, Any]]:
        configs: list[dict[str, Any]] = []
        all_options: dict[str, dict[str, Any]] = {}

        for entry in self._providers:
            if entry.instance is not None:
                prov = entry.instance
            else:
                plugin_type = entry.type or entry.name
                prov = load_provider(plugin_type)

            cfg: dict[str, Any] = {
                "name": entry.name,
                "provider": prov,
            }
            if entry.role:
                cfg["role"] = entry.role
            if entry.item_mapping:
                cfg["item_mapping"] = entry.item_mapping

            configs.append(cfg)
            all_options[entry.name] = entry.options

        composite = CompositeProvider(configs)
        return composite, all_options

    def _resolve_generator(self, entry: _GeneratorEntry) -> Generator:
        if entry.instance is not None:
            return entry.instance
        plugin_type = entry.type or entry.name
        return load_generator(plugin_type)

    def _execute(self) -> Iterator[dict[str, Any]]:
        """Core execution: build engine(s) and yield records."""
        provider, provider_options = self._build_provider()
        selection = self._build_selection()

        if not self._generators:
            raise ValueError("Pipeline has no generator. Call .generator() first.")

        if len(self._generators) == 1:
            yield from self._run_single_generator(
                provider, selection, provider_options
            )
        else:
            yield from self._run_multi_generator(
                provider, selection, provider_options
            )

    def _run_single_generator(
        self,
        provider: Provider,
        selection: Selection,
        provider_options: dict[str, Any],
    ) -> Iterator[dict[str, Any]]:
        entry = self._generators[0]
        gen = self._resolve_generator(entry)
        engine = DatasetEngine(
            provider, gen, defer_validation=self._defer_validation
        )
        yield from engine.run(
            selection,
            provider_options=provider_options,
            generator_options=entry.options,
        )

    def _run_multi_generator(
        self,
        provider: Provider,
        selection: Selection,
        provider_options: dict[str, Any],
    ) -> Iterator[dict[str, Any]]:
        specs: list[GeneratorSpec] = []
        for entry in self._generators:
            gen = self._resolve_generator(entry)
            output_config: dict[str, Any] = {}
            if entry.output:
                output_config["path"] = entry.output
            specs.append(
                GeneratorSpec(
                    name=entry.name,
                    generator=gen,
                    options=entry.options,
                    output_config=output_config,
                )
            )

        runner = MultiGeneratorRunner(
            provider, specs, defer_validation=self._defer_validation
        )
        iterators = runner.run(selection, provider_options=provider_options)

        # In multi-generator mode with per-generator output paths, write
        # each generator's records to its own file and also yield all records.
        for spec in specs:
            records = iterators[spec.name]
            if spec.output_config.get("path"):
                materialized = list(records)
                write_output(
                    iter(materialized),
                    path=spec.output_config["path"],
                    fmt=spec.output_config.get("format", "jsonl"),
                )
                yield from materialized
            else:
                yield from records

    def _apply_transforms(
        self, records: Iterator[dict[str, Any]]
    ) -> Iterator[dict[str, Any]]:
        if not self._transforms:
            yield from records
            return
        for record in records:
            result: dict[str, Any] | None = record
            for fn in self._transforms:
                if result is None:
                    break
                result = fn(result)
            if result is not None:
                yield result
