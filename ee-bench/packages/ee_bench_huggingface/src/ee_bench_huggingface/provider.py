"""HuggingFace dataset provider implementation."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterator

from ee_bench_generator import Provider
from ee_bench_generator.errors import ProviderError
from ee_bench_generator.metadata import Context, FieldDescriptor, ProviderMetadata

# Supported filter operators and their match functions.
# Each takes (field_value, filter_arg) and returns bool.
_FILTER_OPS: dict[str, Any] = {
    "eq": lambda v, arg: str(v) == str(arg),
    "not_eq": lambda v, arg: str(v) != str(arg),
    "in": lambda v, arg: str(v) in [str(a) for a in arg],
    "not_in": lambda v, arg: str(v) not in [str(a) for a in arg],
    "contains": lambda v, arg: str(arg) in str(v),
    "not_contains": lambda v, arg: str(arg) not in str(v),
    "regex": lambda v, arg: bool(re.search(str(arg), str(v))),
    "startswith": lambda v, arg: str(v).startswith(str(arg)),
    "endswith": lambda v, arg: str(v).endswith(str(arg)),
}


def _compile_filters(raw: dict[str, Any]) -> list[tuple[str, str, Any]]:
    """Compile a filters dict into a list of (field, operator, argument) tuples.

    Supports two syntaxes per field:
      - Shorthand:  ``field: value``  → ``eq`` match
      - Advanced:   ``field: {op: arg, ...}``  → one tuple per operator

    Returns:
        List of (field_name, operator, argument) tuples.

    Raises:
        ProviderError: If an unknown operator is used.
    """
    compiled: list[tuple[str, str, Any]] = []
    for field, spec in raw.items():
        if isinstance(spec, dict):
            for op, arg in spec.items():
                if op not in _FILTER_OPS:
                    raise ProviderError(
                        f"Unknown filter operator '{op}' for field '{field}'. "
                        f"Supported: {sorted(_FILTER_OPS)}"
                    )
                compiled.append((field, op, arg))
        else:
            # Shorthand: scalar value → eq
            compiled.append((field, "eq", spec))
    return compiled


def _row_matches(row: dict[str, Any], compiled: list[tuple[str, str, Any]]) -> bool:
    """Check whether a dataset row satisfies all compiled filter conditions."""
    for field, op, arg in compiled:
        value = row.get(field, "")
        if not _FILTER_OPS[op](value, arg):
            return False
    return True


class HuggingFaceDatasetProvider(Provider):
    """Provider that reads data from HuggingFace datasets.

    Dynamically discovers dataset columns and exposes them as provider fields.
    Works with any dataset on HuggingFace Hub (e.g., ScaleAI/SWE-bench_Pro).

    Provided sources:
    - dataset_item: All columns from the dataset, discovered at prepare() time
    - dataset_metadata: Computed metadata fields (e.g., checksum)
    """

    def __init__(self) -> None:
        self._dataset = None
        self._options: dict[str, Any] = {}
        self._column_names: list[str] = []
        self._provided_fields: list[FieldDescriptor] = []
        self._compiled_filters: list[tuple[str, str, Any]] = []

    @property
    def metadata(self) -> ProviderMetadata:
        fields = list(self._provided_fields) if self._provided_fields else []
        # Always declare the checksum field from dataset_metadata
        if not any(f.name == "checksum" and f.source == "dataset_metadata" for f in fields):
            fields.append(
                FieldDescriptor(
                    "checksum",
                    source="dataset_metadata",
                    description="SHA-256 checksum of the serialized row",
                )
            )
        return ProviderMetadata(
            name="huggingface_dataset",
            sources=["dataset_item", "dataset_metadata"],
            provided_fields=fields,
        )

    def prepare(self, **options: Any) -> None:
        """Prepare the provider by loading the dataset.

        Args:
            **options: Provider options including:
                - dataset_name: HuggingFace dataset ID (e.g., "ScaleAI/SWE-bench_Pro")
                - dataset_path: Local file path (alternative to dataset_name)
                - split: Dataset split (default: "test")
                - hf_token: HuggingFace API token for gated datasets
                - filters: Generic filter dict (see below)
                - filter_repos: (legacy) List of repos to include
                - exclude_repos: (legacy) List of repos to exclude
                - filter_language: (legacy) Filter by repo_language field

            The ``filters`` option supports filtering by any dataset field::

                filters:
                  repo_language: Python           # shorthand for eq
                  instance_id:
                    contains: django              # substring match
                  repo:
                    in: [django/django, ...]      # inclusion list
                  version:
                    regex: "^4\\\\."              # regex match

            Supported operators: eq, not_eq, in, not_in, contains,
            not_contains, regex, startswith, endswith.

            Legacy options (filter_language, filter_repos, exclude_repos)
            are converted to the generic filters format internally.
        """
        self._options = options

        dataset_name = options.get("dataset_name")
        dataset_path = options.get("dataset_path")
        split = options.get("split", "test")
        hf_token = options.get("hf_token")

        if not dataset_name and not dataset_path:
            raise ProviderError(
                "Either 'dataset_name' or 'dataset_path' must be provided"
            )

        try:
            from datasets import load_dataset
        except ImportError:
            raise ProviderError(
                "The 'datasets' package is required. Install with: pip install datasets>=2.20"
            )

        # Treat empty string token as None (from ${HF_TOKEN:-} when env var is unset)
        if hf_token is not None and not hf_token.strip():
            hf_token = None

        try:
            if dataset_path:
                ds = load_dataset("json", data_files=dataset_path, split=split)
            else:
                load_kwargs: dict[str, Any] = {"split": split}
                if hf_token:
                    load_kwargs["token"] = hf_token
                ds = load_dataset(dataset_name, **load_kwargs)
        except Exception as e:
            raise ProviderError(f"Failed to load dataset: {e}")

        self._dataset = ds
        self._column_names = list(ds.column_names)

        # Build dynamic field descriptors from dataset columns
        self._provided_fields = []
        for col in self._column_names:
            self._provided_fields.append(
                FieldDescriptor(
                    col,
                    source="dataset_item",
                    description=f"Dataset column: {col}",
                )
            )
        # Add checksum field
        self._provided_fields.append(
            FieldDescriptor(
                "checksum",
                source="dataset_metadata",
                description="SHA-256 checksum of the serialized row",
            )
        )

        # Compile filters
        self._compiled_filters = self._build_filters(options)

    @staticmethod
    def _build_filters(options: dict[str, Any]) -> list[tuple[str, str, Any]]:
        """Build compiled filter list from options, merging generic and legacy."""
        filters_raw: dict[str, Any] = dict(options.get("filters") or {})

        # Convert legacy options into generic filter entries
        filter_language = options.get("filter_language")
        if filter_language:
            filters_raw.setdefault("repo_language", filter_language)

        filter_repos = options.get("filter_repos")
        if filter_repos:
            existing = filters_raw.get("repo")
            if isinstance(existing, dict):
                existing.setdefault("in", filter_repos)
            else:
                filters_raw.setdefault("repo", {"in": filter_repos})

        exclude_repos = options.get("exclude_repos")
        if exclude_repos:
            existing = filters_raw.get("repo")
            if isinstance(existing, dict):
                existing.setdefault("not_in", exclude_repos)
            else:
                filters_raw.setdefault("repo", {"not_in": exclude_repos})

        if not filters_raw:
            return []

        return _compile_filters(filters_raw)

    def get_field(self, name: str, source: str, context: Context) -> Any:
        """Retrieve a specific field value from the current dataset item.

        Args:
            name: Field name (dataset column name or metadata field).
            source: Data source ("dataset_item" or "dataset_metadata").
            context: Runtime context with current_item set.

        Returns:
            Field value.
        """
        if self._dataset is None:
            raise ProviderError("Provider not prepared. Call prepare() first.")

        current = context.current_item
        if not current:
            raise ProviderError("No current item in context")

        if source == "dataset_item":
            if name not in current:
                raise ProviderError(
                    f"Column '{name}' not found in dataset item. "
                    f"Available: {list(current.keys())}"
                )
            return current[name]
        elif source == "dataset_metadata":
            if name == "checksum":
                return self._compute_checksum(current)
            raise ProviderError(f"Unknown dataset_metadata field: {name}")
        else:
            raise ProviderError(f"Unknown source: {source}")

    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:
        """Iterate over dataset items, applying configured filters.

        Yields:
            Dataset rows as dictionaries with all column values.
        """
        if self._dataset is None:
            raise ProviderError("Provider not prepared. Call prepare() first.")

        limit = context.selection.limit

        count = 0
        for i in range(len(self._dataset)):
            if limit is not None and count >= limit:
                return

            row = self._dataset[i]

            if self._compiled_filters and not _row_matches(row, self._compiled_filters):
                continue

            yield dict(row)
            count += 1

    @staticmethod
    def _compute_checksum(row: dict[str, Any]) -> str:
        """Compute SHA-256 checksum of a serialized row."""
        serialized = json.dumps(row, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
