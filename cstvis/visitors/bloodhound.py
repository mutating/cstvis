from dataclasses import replace
from typing import Dict, List, Type

from libcst import CSTNode, CSTVisitor, metadata

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
        nodes_mapping: Dict[Type[CSTNode], List[CallableWrapper[CSTNode]]],
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
        converters = self.nodes_mapping.get(type(node), []) + self.nodes_mapping.get(CSTNode, [])  # type: ignore[type-abstract]
        if not converters:
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

        filters = self.filters.get(type(node), []) + self.filters.get(CSTNode, [])  # type: ignore[type-abstract]
        if filters:
            node_range = self.get_metadata(metadata.WhitespaceInclusivePositionProvider, node)
            context = Context(
                SourcePosition(coordinate, self.source_offsets.source, node_range, self.source_offsets),
                self.comments.get(coordinate.start_line),
            )
            for filter_function in filters:
                if not filter_function(node, context):
                    return True
        for converter_id in {converter.get_function_id() for converter in converters}:
            self.coordinates.append(replace(coordinate, converter_id=converter_id))

        return True
