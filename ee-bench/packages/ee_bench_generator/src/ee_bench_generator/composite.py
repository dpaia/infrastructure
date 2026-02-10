"""CompositeProvider — wraps multiple providers behind a single Provider interface."""

from __future__ import annotations

import re
from typing import Any, Iterator

from jinja2 import Environment, StrictUndefined

from ee_bench_generator.errors import EEBenchError, ProviderError
from ee_bench_generator.interfaces import Provider
from ee_bench_generator.metadata import (
    Context,
    FieldDescriptor,
    ProviderMetadata,
    Selection,
)

# Pattern to extract provider references from item_mapping templates:
#   {{ providers.swe_bench_data.repo }}
#   {{ providers.swe_bench_data.repo | split('/') | first }}
_PROVIDER_REF_PATTERN = re.compile(r"providers\.(\w+)\.(\w+)")


class CyclicDependencyError(EEBenchError):
    """Raised when provider dependency graph contains a cycle."""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__(f"Cyclic provider dependency: {' -> '.join(cycle)}")


class CompositeProviderConfigError(EEBenchError):
    """Raised for invalid CompositeProvider configuration."""


def _build_dependency_graph(
    provider_configs: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Build a dependency graph by scanning item_mapping templates for provider references.

    Returns:
        Dict mapping provider name -> list of provider names it depends on.
    """
    graph: dict[str, list[str]] = {}
    for cfg in provider_configs:
        name = cfg["name"]
        deps: list[str] = []
        item_mapping = cfg.get("item_mapping", {})
        for _field, template in item_mapping.items():
            for match in _PROVIDER_REF_PATTERN.finditer(str(template)):
                dep_name = match.group(1)
                if dep_name not in deps:
                    deps.append(dep_name)
        graph[name] = deps
    return graph


def _topological_sort(graph: dict[str, list[str]]) -> list[str]:
    """Topological sort of provider names. Raises CyclicDependencyError on cycles."""
    visited: dict[str, int] = {}  # 0=in-progress, 1=done
    order: list[str] = []

    def visit(node: str, path: list[str]) -> None:
        if node in visited:
            if visited[node] == 0:
                cycle_start = path.index(node)
                raise CyclicDependencyError(path[cycle_start:] + [node])
            return
        visited[node] = 0
        path.append(node)
        for dep in graph.get(node, []):
            visit(dep, path)
        path.pop()
        visited[node] = 1
        order.append(node)

    for node in graph:
        if node not in visited:
            visit(node, [])

    return order


def _extract_dependencies(item_mapping: dict[str, str]) -> dict[str, list[str]]:
    """Extract (provider_name -> [field_names]) from item_mapping templates."""
    deps: dict[str, list[str]] = {}
    for _field, template in item_mapping.items():
        for match in _PROVIDER_REF_PATTERN.finditer(str(template)):
            prov_name = match.group(1)
            field_name = match.group(2)
            deps.setdefault(prov_name, [])
            if field_name not in deps[prov_name]:
                deps[prov_name].append(field_name)
    return deps


class CompositeProvider(Provider):
    """A Provider that wraps multiple providers behind a single Provider interface.

    One provider is designated as ``primary`` (drives ``iter_items()``).
    The rest are enrichment providers whose input items are resolved
    through ``item_mapping`` Jinja2 templates referencing other providers' fields.

    Args:
        provider_configs: List of dicts, each with keys:
            - ``name``: unique instance identifier
            - ``provider``: instantiated Provider object
            - ``role``: ``"primary"`` for exactly one provider (optional, default enrichment)
            - ``item_mapping``: dict of field -> Jinja2 template (optional)
        validate: If True, validate the configuration at init time.
    """

    def __init__(
        self,
        provider_configs: list[dict[str, Any]],
        *,
        validate: bool = True,
    ) -> None:
        if not provider_configs:
            raise CompositeProviderConfigError("At least one provider config is required")

        self._configs_by_name: dict[str, dict[str, Any]] = {}
        self._providers_by_name: dict[str, Provider] = {}
        self._primary_name: str | None = None

        for cfg in provider_configs:
            name = cfg["name"]
            if name in self._configs_by_name:
                raise CompositeProviderConfigError(
                    f"Duplicate provider name: '{name}'"
                )
            self._configs_by_name[name] = cfg
            self._providers_by_name[name] = cfg["provider"]
            if cfg.get("role") == "primary":
                if self._primary_name is not None:
                    raise CompositeProviderConfigError(
                        "Exactly one provider must have role 'primary', "
                        f"found multiple: '{self._primary_name}' and '{name}'"
                    )
                self._primary_name = name

        if validate and self._primary_name is None:
            raise CompositeProviderConfigError(
                "Exactly one provider must have role 'primary'"
            )

        # Build dependency DAG and topological order
        dep_graph = _build_dependency_graph(provider_configs)
        self._dependency_order = _topological_sort(dep_graph)

        # Build field routing table: (field_name, source) -> provider_name
        self._field_routing: dict[tuple[str, str], str] = {}
        # Process in dependency order so that enrichment providers can override
        # fields from providers they depend on. Primary provider's fields are base.
        for pname in self._dependency_order:
            prov = self._providers_by_name[pname]
            for fd in prov.metadata.provided_fields:
                self._field_routing[(fd.name, fd.source)] = pname

        # Per-item field cache: (item_key, provider_name, field_name, source) -> value
        self._field_cache: dict[tuple[Any, str, str, str], Any] = {}
        self._current_item_key: Any = None

        # Jinja2 env for rendering item_mapping templates
        self._jinja_env = Environment(undefined=StrictUndefined)
        self._jinja_env.filters["split"] = lambda s, sep: s.split(sep)

    @property
    def primary(self) -> Provider:
        """The primary provider that drives iter_items()."""
        return self._providers_by_name[self._primary_name]

    @property
    def metadata(self) -> ProviderMetadata:
        """Merged metadata from all providers.

        Union of all provided_fields and sources. Primary wins on collisions
        (but in practice all fields are included since field_routing handles dispatch).
        """
        all_fields: list[FieldDescriptor] = []
        all_sources: set[str] = set()
        seen: set[tuple[str, str]] = set()

        for pname in self._dependency_order:
            prov = self._providers_by_name[pname]
            for fd in prov.metadata.provided_fields:
                key = (fd.name, fd.source)
                if key not in seen:
                    all_fields.append(fd)
                    seen.add(key)
            all_sources.update(prov.metadata.sources)

        return ProviderMetadata(
            name="composite",
            sources=sorted(all_sources),
            provided_fields=all_fields,
        )

    def prepare(self, **options: Any) -> None:
        """Prepare all providers.

        Expects options keyed by provider instance name::

            composite_provider.prepare(
                swe_bench_data={"dataset_name": "..."},
                upstream_prs={"token": "..."},
            )

        If a flat dict is passed (no provider name keys), it is forwarded to the
        primary provider only (backward-compatible behavior).
        """
        # Detect whether options are keyed by provider name
        provider_names = set(self._configs_by_name.keys())
        if options and provider_names.intersection(options.keys()):
            # Keyed by provider name
            for pname in self._dependency_order:
                prov_opts = options.get(pname, {})
                self._providers_by_name[pname].prepare(**prov_opts)
        else:
            # Flat dict — forward to primary only (backward compat)
            for pname in self._dependency_order:
                if pname == self._primary_name:
                    self._providers_by_name[pname].prepare(**options)
                else:
                    self._providers_by_name[pname].prepare()

    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:
        """Delegate to primary provider's iter_items(). Clears per-item cache."""
        for item in self.primary.iter_items(context):
            # Clear cache for new item
            self._field_cache.clear()
            self._current_item_key = id(item)
            yield item

    def get_field(self, name: str, source: str, context: Context) -> Any:
        """Resolve a field through the provider chain.

        1. Look up the owning provider from field_routing
        2. If primary, delegate directly
        3. If enrichment, resolve item_mapping, create mapped context, delegate
        """
        # Check cache first
        cache_key = (self._current_item_key, name, source)
        if cache_key in self._field_cache:
            return self._field_cache[cache_key]

        # Find owning provider
        routing_key = (name, source)
        owner_name = self._field_routing.get(routing_key)
        if owner_name is None:
            raise ProviderError(
                f"No provider can supply field '{name}' from source '{source}'"
            )

        value = self._resolve_field(owner_name, name, source, context)
        self._field_cache[cache_key] = value
        return value

    def _resolve_field(
        self, provider_name: str, name: str, source: str, context: Context
    ) -> Any:
        """Resolve a field from a specific provider, handling item_mapping for enrichments."""
        if provider_name == self._primary_name:
            return self._providers_by_name[provider_name].get_field(
                name, source, context
            )

        # Enrichment provider — resolve its item_mapping to create a mapped context
        cfg = self._configs_by_name[provider_name]
        item_mapping = cfg.get("item_mapping", {})

        if not item_mapping:
            # No mapping — delegate directly with current context
            return self._providers_by_name[provider_name].get_field(
                name, source, context
            )

        # Resolve upstream fields referenced in item_mapping templates
        mapped_item = self._resolve_item_mapping(item_mapping, context)

        # Create a new context with the mapped item
        mapped_context = Context(
            selection=context.selection,
            options=context.options,
            current_item=mapped_item,
        )

        return self._providers_by_name[provider_name].get_field(
            name, source, mapped_context
        )

    def _resolve_item_mapping(
        self, item_mapping: dict[str, str], context: Context
    ) -> dict[str, Any]:
        """Resolve item_mapping templates by fetching upstream provider fields."""
        # Build the providers namespace for Jinja2 rendering
        providers_ns: dict[str, dict[str, Any]] = {}

        # Collect all referenced providers and fields
        all_deps = _extract_dependencies(item_mapping)

        for dep_prov_name, dep_fields in all_deps.items():
            if dep_prov_name not in providers_ns:
                providers_ns[dep_prov_name] = {}

            for field_name in dep_fields:
                # Find the source for this field from the dependency provider
                dep_prov = self._providers_by_name.get(dep_prov_name)
                if dep_prov is None:
                    raise ProviderError(
                        f"item_mapping references unknown provider '{dep_prov_name}'"
                    )

                # Find the source for this field
                field_source = self._find_field_source(dep_prov_name, field_name)

                # Recursively resolve the field (may trigger upstream providers).
                # Use a 4-tuple cache key that includes the provider name so that
                # raw upstream values don't collide with routed values cached by
                # get_field() (which uses a 3-tuple key).
                dep_cache_key = (
                    self._current_item_key, dep_prov_name, field_name, field_source,
                )
                if dep_cache_key in self._field_cache:
                    value = self._field_cache[dep_cache_key]
                else:
                    value = self._resolve_field(
                        dep_prov_name, field_name, field_source, context
                    )
                    self._field_cache[dep_cache_key] = value

                providers_ns[dep_prov_name][field_name] = value

        # Render each template in item_mapping
        mapped_item: dict[str, Any] = {}
        for field_name, template_str in item_mapping.items():
            tmpl = self._jinja_env.from_string(str(template_str))
            rendered = tmpl.render(providers=providers_ns)
            # Try to convert numeric strings back to numbers
            mapped_item[field_name] = _coerce_value(rendered)

        return mapped_item

    def _find_field_source(self, provider_name: str, field_name: str) -> str:
        """Find the source for a field from a specific provider."""
        prov = self._providers_by_name[provider_name]
        for fd in prov.metadata.provided_fields:
            if fd.name == field_name:
                return fd.source
        # Field might be in current_item (primary provider's iter_items output)
        # Use a generic source
        if provider_name == self._primary_name:
            # For primary provider, the field might be available through any source
            if prov.metadata.sources:
                return prov.metadata.sources[0]
        raise ProviderError(
            f"Provider '{provider_name}' has no field '{field_name}' in its metadata"
        )


def _coerce_value(value: str) -> Any:
    """Try to coerce a rendered template string to int or float."""
    try:
        return int(value)
    except (ValueError, TypeError):
        pass
    try:
        return float(value)
    except (ValueError, TypeError):
        pass
    return value
