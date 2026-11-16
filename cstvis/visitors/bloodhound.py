from dataclasses import replace
from typing import Dict, List, Optional, Type

from libcst import CSTNode, CSTVisitor, metadata

from cstvis.converter import Converter, resolve_converters
from cstvis.dto import Context, Coordinate, SourcePosition
from cstvis.source_offsets import SourceOffsetResolver
from cstvis.wrapper import CallableWrapper


class Bloodhound(CSTVisitor):
    """
    Discover coordinates and source ranges for registered conversions.

    Public coordinates use ``PositionProvider``. Contextual node ranges use
    ``WhitespaceInclusivePositionProvider``, which requires an additional
    metadata pass and includes whitespace owned by each node.
    """

    METADATA_DEPENDENCIES = (metadata.PositionProvider, metadata.WhitespaceInclusivePositionProvider)

    def __init__(
        self,
        nodes_mapping: Dict[Type[CSTNode], List[Converter]],
        comments: Dict[int, str],
        filters: Dict[Type[CSTNode], List[CallableWrapper[bool]]],
        source_offsets: SourceOffsetResolver,
    ) -> None:
        self.coordinates: List[Coordinate] = []
        self.nodes_mapping = nodes_mapping
        self.comments = comments
        self.filters = filters
        self.source_offsets = source_offsets

    def on_visit(self, node: CSTNode) -> bool:
        if not self.nodes_mapping.get(type(node)) and not self.nodes_mapping.get(CSTNode):  # type: ignore[type-abstract]
            return True

        position = self.get_metadata(metadata.PositionProvider, node)
        coordinate = Coordinate(
            file=None,
            class_name=node.__class__.__name__,
            start_line=position.start.line,
            start_column=position.start.column,
            end_line=position.end.line,
            end_column=position.end.column,
        )

        node_type_filters = list(dict.fromkeys(self.filters.get(type(node), []) + self.filters.get(CSTNode, [])))  # type: ignore[type-abstract]
        context: Optional[Context] = None
        if node_type_filters:
            context = self._build_context(node, coordinate)
            if not all(filter_function.call_with_context(node, context) for filter_function in node_type_filters):
                return True

        converter_ids = resolve_converters(self.nodes_mapping, type(node))
        for converter, converter_id in converter_ids.items():
            if converter.filters:
                if context is None:
                    context = self._build_context(node, coordinate)
                if not all(filter_function.call_with_context(node, context) for filter_function in converter.filters):
                    continue
            self.coordinates.append(replace(coordinate, converter_id=converter_id))

        return True

    def _build_context(self, node: CSTNode, coordinate: Coordinate) -> Context:
        node_range = self.get_metadata(metadata.WhitespaceInclusivePositionProvider, node)
        return Context(
            SourcePosition(coordinate, self.source_offsets.source, node_range, self.source_offsets),
            self.comments.get(coordinate.start_line),
        )
