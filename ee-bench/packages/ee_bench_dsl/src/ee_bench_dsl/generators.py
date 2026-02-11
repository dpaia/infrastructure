"""Ad-hoc generators: FunctionGenerator and each() helper."""

from __future__ import annotations

from typing import Any, Callable, Iterator

from ee_bench_generator.interfaces import Generator, Provider
from ee_bench_generator.metadata import (
    Context,
    FieldDescriptor,
    GeneratorMetadata,
)


class FunctionGenerator(Generator):
    """A Generator backed by a Python callable.

    Two calling conventions are supported:

    *Per-item* (``item_fn``): called once per item yielded by the provider's
    ``iter_items()``.  Signature: ``(item: dict, ctx: Context) -> dict | None``.
    Return ``None`` to skip an item.

    *Bulk* (``process_fn``): called once with the provider and context.
    Signature: ``(provider: Provider, ctx: Context) -> Iterator[dict]``.

    Args:
        item_fn: Per-item callable.
        process_fn: Bulk callable (mutually exclusive with *item_fn*).
        name: Generator name for metadata.
    """

    def __init__(
        self,
        *,
        item_fn: Callable[[dict[str, Any], Context], dict[str, Any] | None] | None = None,
        process_fn: Callable[[Provider, Context], Iterator[dict[str, Any]]] | None = None,
        name: str = "function_generator",
    ) -> None:
        if item_fn and process_fn:
            raise ValueError("Provide either item_fn or process_fn, not both")
        if not item_fn and not process_fn:
            raise ValueError("Provide either item_fn or process_fn")
        self._item_fn = item_fn
        self._process_fn = process_fn
        self._name = name

    # -- Generator ABC --------------------------------------------------------

    @property
    def metadata(self) -> GeneratorMetadata:
        return GeneratorMetadata(
            name=self._name,
            required_fields=[],
            optional_fields=[],
        )

    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    def generate(
        self, provider: Provider, context: Context
    ) -> Iterator[dict[str, Any]]:
        if self._process_fn is not None:
            yield from self._process_fn(provider, context)
            return

        assert self._item_fn is not None
        for item in provider.iter_items(context):
            context.current_item = item
            result = self._item_fn(item, context)
            if result is not None:
                yield result


def each(
    fn: Callable[[dict[str, Any], Context], dict[str, Any] | None],
) -> FunctionGenerator:
    """Create a per-item :class:`FunctionGenerator`.

    >>> gen = each(lambda item, ctx: {"id": item["id"]})
    >>> gen.metadata.name
    'function_generator'
    """
    return FunctionGenerator(item_fn=fn)
