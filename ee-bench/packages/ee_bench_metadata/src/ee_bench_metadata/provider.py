"""MetadataProvider - extracts metadata from <!--METADATA--> blocks in text."""

from __future__ import annotations

import re
from typing import Any, Iterator

from ee_bench_generator import Provider
from ee_bench_generator.errors import ProviderError
from ee_bench_generator.metadata import Context, FieldDescriptor, ProviderMetadata

# Regex to match the metadata block (dotall for multiline content)
_METADATA_PATTERN = re.compile(
    r"<!--METADATA\n(.*?)\nMETADATA-->",
    re.DOTALL,
)


def parse_metadata_block(text: str) -> dict[str, str]:
    """Parse the ``<!--METADATA ... METADATA-->`` block from *text*.

    Returns:
        Dictionary of key-value pairs.  Empty dict if no block found.
    """
    match = _METADATA_PATTERN.search(text)
    if not match:
        return {}

    content = match.group(1)
    result: dict[str, str] = {}

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        colon_idx = line.find(":")
        if colon_idx < 0:
            continue
        key = line[:colon_idx].strip()
        value = line[colon_idx + 1 :]
        # Restore escaped newlines
        value = value.replace("\\n", "\n")
        result[key] = value

    return result


class MetadataProvider(Provider):
    """Enrichment-only provider that extracts fields from a ``<!--METADATA-->`` block.

    The provider receives arbitrary text via ``item_mapping`` (keyed as
    ``text``) and parses the embedded metadata comment.  Individual keys
    are then exposed as provider fields.

    **Configuration (via ``prepare()``):**

    ``fields``
        **Required.**  Explicit list of metadata field names to serve.
        This list drives ``metadata.provided_fields`` declarations and
        ``get_field()`` validation.

    ``source``
        Source name for field descriptors.  Defaults to ``"pull_request"``.

    **Not a primary provider** -- calling :meth:`iter_items` raises
    :class:`~ee_bench_generator.errors.ProviderError`.
    """

    def __init__(self) -> None:
        self._fields: list[str] = []
        self._source: str = "pull_request"
        self._cache_key: str | None = None
        self._cache_result: dict[str, str] = {}

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="metadata",
            sources=[self._source],
            provided_fields=[
                FieldDescriptor(
                    name,
                    source=self._source,
                    description=f"Metadata field '{name}'",
                )
                for name in self._fields
            ],
        )

    def prepare(self, **options: Any) -> None:
        fields = options.get("fields")
        if not fields:
            raise ProviderError(
                "MetadataProvider requires 'fields' option — "
                "an explicit list of metadata field names to provide"
            )
        self._fields = list(fields)
        self._source = options.get("source", "pull_request")

    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:  # noqa: ARG002
        raise ProviderError(
            "MetadataProvider is an enrichment-only provider and cannot "
            "be used as a primary provider. Use it with item_mapping in a "
            "multi-provider configuration."
        )

    def get_field(self, name: str, source: str, context: Context) -> Any:  # noqa: ARG002
        if name not in self._fields:
            raise ProviderError(
                f"MetadataProvider does not provide field '{name}' "
                f"(configured fields: {self._fields})"
            )

        current = context.current_item or {}
        text = current.get("text", "")

        # Cache parsed metadata per text to avoid re-parsing
        if text != self._cache_key:
            self._cache_key = text
            self._cache_result = parse_metadata_block(text)

        return self._cache_result.get(name, "")
