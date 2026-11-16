from dataclasses import replace
from typing import Dict, List, Type

from libcst import CSTNode, CSTTransformer, metadata

from cstvis.converter import Converter, resolve_converters
from cstvis.dto import Context, Coordinate, SourcePosition
from cstvis.source_offsets import SourceOffsetResolver


class SuperTransformer(CSTTransformer):
    """
    Apply one conversion with positions from the original node.

    Public coordinates use ``PositionProvider``; contextual ranges use the
    additional ``WhitespaceInclusivePositionProvider`` metadata pass. Reading
    ``Context.position`` later resolves the original node's source offsets.
    """

    METADATA_DEPENDENCIES = (metadata.PositionProvider, metadata.WhitespaceInclusivePositionProvider)

    def __init__(
        self,
        target_coordinate: Coordinate,
        nodes_mapping: Dict[Type[CSTNode], List[Converter]],
        comments: Dict[int, str],
        source_offsets: SourceOffsetResolver,
    ):
        self.target_coordinate = target_coordinate
        self.target_coordinate_without_converter_id = replace(
            target_coordinate,
            file=None,
            converter_id=None,
        )
        self.nodes_mapping = nodes_mapping
        self.comments = comments
        self.source_offsets = source_offsets

        super().__init__()

    # LibCST's generic signature cannot express supported cross-type replacements.
    def on_leave(self, original_node: CSTNode, updated_node: CSTNode) -> CSTNode:  # type: ignore[override]
        if original_node.__class__.__name__ != self.target_coordinate.class_name:
            return updated_node

        position = self.get_metadata(metadata.PositionProvider, original_node)
        coordinate = Coordinate(
            file=None,
            class_name=original_node.__class__.__name__,
            start_line=position.start.line,
            start_column=position.start.column,
            end_line=position.end.line,
            end_column=position.end.column,
        )
        if coordinate == self.target_coordinate_without_converter_id:
            converter_ids = resolve_converters(self.nodes_mapping, type(original_node))
            for converter, converter_id in converter_ids.items():  # pragma: no branch
                if converter_id == self.target_coordinate.converter_id:
                    node_range = self.get_metadata(metadata.WhitespaceInclusivePositionProvider, original_node)
                    context = Context(
                        SourcePosition(coordinate, self.source_offsets.source, node_range, self.source_offsets),
                        self.comments.get(coordinate.start_line),
                    )
                    return converter.call_with_context(updated_node, context)
        return updated_node
