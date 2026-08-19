from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from libcst.metadata import CodeRange
from metacode import ParsedComment, parse
from printo import describe_call


@dataclass
class Coordinate:
    file: Optional[Path]
    class_name: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    converter_id: Optional[str] = None


@dataclass(frozen=True, repr=False)
class SourcePosition:
    """
    Describe and lazily partition a node's span in the original source.

    ``coordinate`` is the ordinary syntactic position, while ``node_range`` is
    the node's whitespace-inclusive LibCST range. The required resolver maps
    that range to absolute Python-character offsets in ``source``. It is
    normally shared by every position produced during one traversal, so the
    first access performs one alignment pass and later positions reuse its
    results.

    The range identifies a contextual source span rather than
    ``Module.code_for_node()`` output, which may lose ambient indentation or
    add a final newline. For the exact source slice ``node_source_span``::

        code_before + node_source_span + code_after == source

    Offsets and the two surrounding source slices are cached independently.
    """

    coordinate: Coordinate
    source: str
    node_range: CodeRange
    offset_resolver: Callable[[CodeRange], Tuple[int, int]] = field(repr=False, compare=False)

    @cached_property
    def start_offset(self) -> int:
        """Lazily resolve and cache the node span's starting source index."""
        return self.offset_resolver(self.node_range)[0]

    @cached_property
    def end_offset(self) -> int:
        """Lazily resolve and cache the node span's ending source index."""
        return self.offset_resolver(self.node_range)[1]

    @cached_property
    def code_before(self) -> str:
        """Lazily slice and cache the exact source prefix before node_range."""
        return self.source[:self.start_offset]

    @cached_property
    def code_after(self) -> str:
        """Lazily slice and cache the exact source suffix after node_range."""
        return self.source[self.end_offset:]

    def __repr__(self) -> str:
        """Describe public source data and lazy offsets with an item limit of 80."""
        return describe_call(
            type(self),
            [],
            {
                'coordinate': self.coordinate,
                'source': self.source,
                'node_range': self.node_range,
                'start_offset': self.start_offset,
                'end_offset': self.end_offset,
            },
            item_limit=80,
        )


@dataclass(frozen=True, repr=False)
class Context:
    """
    Describe a callback invocation and its position in the original source.

    Source-related data and lazy fragments are exposed through ``position``.
    The dataclass is frozen, although a dictionary supplied as ``meta`` remains
    mutable.
    """

    position: SourcePosition
    comment: Optional[str]
    meta: Optional[Dict[str, Any]] = None

    def __repr__(self) -> str:
        """Describe public callback data with an item limit of 80."""
        return describe_call(
            type(self),
            [],
            {
                'position': self.position,
                'comment': self.comment,
                'meta': self.meta,
            },
            item_limit=80,
        )

    def get_metacodes(self, key: Union[str, List[str]]) -> List[ParsedComment]:
        if self.comment is None:
            return []
        return parse(self.comment, key)
