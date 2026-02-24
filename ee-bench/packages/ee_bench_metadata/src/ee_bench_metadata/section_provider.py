"""SectionProvider - extracts content from markdown ## sections in text."""

from __future__ import annotations

import re
from typing import Any, Iterator

from ee_bench_generator import Provider
from ee_bench_generator.errors import ProviderError
from ee_bench_generator.metadata import Context, FieldDescriptor, ProviderMetadata

# Pattern matching ## headers (at start of line)
_SECTION_HEADER_PATTERN = re.compile(r"^##\s+", re.MULTILINE)

# Pattern matching the start of a metadata block
_METADATA_START_PATTERN = re.compile(r"<!--\s*METADATA\b", re.IGNORECASE)


def _parse_sections(text: str, sections: dict[str, str]) -> dict[str, str]:
    """Extract content from markdown ``##`` sections.

    Args:
        text: The full text (e.g. a PR body) containing markdown sections.
        sections: Mapping of ``field_name -> section_header`` where
            *section_header* is the exact ``## Header`` string to look for.

    Returns:
        Dictionary of ``field_name -> section_content`` (stripped).
        Fields whose headers are not found get empty strings.
    """
    result: dict[str, str] = {}

    for field_name, header in sections.items():
        # Find the header in the text
        header_idx = text.find(header)
        if header_idx < 0:
            result[field_name] = ""
            continue

        # Content starts after the header line
        content_start = text.find("\n", header_idx)
        if content_start < 0:
            result[field_name] = ""
            continue
        content_start += 1  # skip the newline

        # Content ends at the next ## header or <!--METADATA or end of text
        remaining = text[content_start:]

        # Find next ## header
        next_header = _SECTION_HEADER_PATTERN.search(remaining)
        # Find metadata block
        metadata_match = _METADATA_START_PATTERN.search(remaining)

        end_idx = len(remaining)
        if next_header:
            end_idx = min(end_idx, next_header.start())
        if metadata_match:
            end_idx = min(end_idx, metadata_match.start())

        content = remaining[:end_idx].strip()
        result[field_name] = content

    return result


class SectionProvider(Provider):
    """Enrichment provider that extracts content from markdown ``##`` sections.

    The provider receives arbitrary text via ``item_mapping`` (keyed as
    ``text``) and extracts content between ``## Header`` markers.

    **Configuration (via ``prepare()``):**

    ``sections``
        **Required.** Dictionary mapping field names to section headers::

            {"problem_statement": "## Problem Statement",
             "hints_text": "## Hints"}

    ``source``
        Source name for field descriptors.  Defaults to ``"pull_request"``.

    **Not a primary provider** — calling :meth:`iter_items` raises
    :class:`~ee_bench_generator.errors.ProviderError`.
    """

    def __init__(self) -> None:
        self._sections: dict[str, str] = {}
        self._source: str = "pull_request"
        self._cache_key: str | None = None
        self._cache_result: dict[str, str] = {}

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="markdown_sections",
            sources=[self._source],
            provided_fields=[
                FieldDescriptor(
                    name,
                    source=self._source,
                    description=f"Section content for '{header}'",
                )
                for name, header in self._sections.items()
            ],
        )

    def prepare(self, **options: Any) -> None:
        sections = options.get("sections")
        if not sections:
            raise ProviderError(
                "SectionProvider requires 'sections' option — "
                "a dict mapping field_name -> section_header"
            )
        self._sections = dict(sections)
        self._source = options.get("source", "pull_request")

    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:  # noqa: ARG002
        raise ProviderError(
            "SectionProvider is an enrichment-only provider and cannot "
            "be used as a primary provider. Use it with item_mapping in a "
            "multi-provider configuration."
        )

    def get_field(self, name: str, source: str, context: Context) -> Any:  # noqa: ARG002
        if name not in self._sections:
            raise ProviderError(
                f"SectionProvider does not provide field '{name}' "
                f"(configured sections: {list(self._sections.keys())})"
            )

        current = context.current_item or {}
        text = current.get("text", "")

        # Cache parsed sections per text to avoid re-parsing
        if text != self._cache_key:
            self._cache_key = text
            self._cache_result = _parse_sections(text, self._sections)

        return self._cache_result.get(name, "")
