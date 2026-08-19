from typing import Dict, List, Type

from libcst import CSTNode, CSTTransformer, metadata

from cstvis.dto import Context, Coordinate, SourcePosition
from cstvis.source_offsets import SourceOffsetResolver
from cstvis.wrapper import CallableWrapper


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
        nodes_mapping: Dict[Type[CSTNode], List[CallableWrapper[CSTNode]]],
        comments: Dict[int, str],
        source_offsets: SourceOffsetResolver,
    ):
        self.target_coordinate = target_coordinate
        self.nodes_mapping = nodes_mapping
        self.comments = comments
        self.source_offsets = source_offsets

        super().__init__()

    # LibCST's generic signature cannot express supported cross-type replacements.
    def on_leave(self, original_node: CSTNode, updated_node: CSTNode) -> CSTNode:  # type: ignore[override]
        converters = self.nodes_mapping.get(type(original_node), []) + self.nodes_mapping.get(CSTNode, [])  # type: ignore[type-abstract]
        if not converters:
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
        target_coordinate_without_converter_id = Coordinate(
            file=None,
            class_name=self.target_coordinate.class_name,
            start_line=self.target_coordinate.start_line,
            start_column=self.target_coordinate.start_column,
            end_line=self.target_coordinate.end_line,
            end_column=self.target_coordinate.end_column,
        )

        if coordinate == target_coordinate_without_converter_id:
            for converter in converters:  # pragma: no branch
                if converter.get_function_id() == self.target_coordinate.converter_id:
                    node_range = self.get_metadata(metadata.WhitespaceInclusivePositionProvider, original_node)
                    context = Context(
                        SourcePosition(coordinate, self.source_offsets.source, node_range, self.source_offsets),
                        self.comments.get(coordinate.start_line),
                    )
                    return converter(updated_node, context)
        return updated_node
