"""Ad-hoc providers: FunctionProvider and from_items() helper."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Iterator

from ee_bench_generator.interfaces import Provider
from ee_bench_generator.metadata import (
    Context,
    FieldDescriptor,
    ProviderMetadata,
)


class FunctionProvider(Provider):
    """A Provider backed by a Python iterable / callable.

    Each yielded dict becomes an item.  Fields are auto-discovered from
    the first item's keys.

    Args:
        data: An iterable of dicts, **or** a callable returning one.
        source: The source name to expose in metadata (default ``"item"``).
        name: Provider name for metadata (default ``"function_provider"``).
    """

    def __init__(
        self,
        data: Iterable[dict[str, Any]] | Callable[[], Iterable[dict[str, Any]]],
        *,
        source: str = "item",
        name: str = "function_provider",
    ) -> None:
        self._data = data
        self._source = source
        self._name = name
        self._items: list[dict[str, Any]] | None = None

    # -- Provider ABC ---------------------------------------------------------

    @property
    def metadata(self) -> ProviderMetadata:
        fields = self._discover_fields()
        return ProviderMetadata(
            name=self._name,
            sources=[self._source],
            provided_fields=fields,
        )

    def prepare(self, **options: Any) -> None:
        self._materialise()

    def get_field(self, name: str, source: str, context: Context) -> Any:
        item = context.current_item or {}
        return item.get(name)

    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:
        self._materialise()
        assert self._items is not None
        yield from self._items

    # -- internals ------------------------------------------------------------

    def _materialise(self) -> None:
        if self._items is not None:
            return
        raw = self._data() if callable(self._data) else self._data
        self._items = list(raw)

    def _discover_fields(self) -> list[FieldDescriptor]:
        self._materialise()
        if not self._items:
            return []
        first = self._items[0]
        return [
            FieldDescriptor(name=k, source=self._source)
            for k in first.keys()
        ]


def from_items(
    data: Iterable[dict[str, Any]] | Callable[[], Iterable[dict[str, Any]]],
    source: str = "item",
) -> FunctionProvider:
    """Create a :class:`FunctionProvider` from an iterable of dicts.

    >>> prov = from_items([{"id": 1}, {"id": 2}])
    >>> prov.metadata.name
    'function_provider'
    """
    return FunctionProvider(data, source=source)
