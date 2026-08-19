from typing import Any, Callable, Dict, List, Set, Type

import libcst.matchers as matchers_module
from libcst import CSTNode, metadata
from libcst.matchers import (
    BaseMatcherNode,
    MatcherDecoratableTransformer,
    TypeOf,
    leave,
)

from cstvis.dto import Context, Coordinate, SourcePosition
from cstvis.source_offsets import SourceOffsetResolver
from cstvis.wrapper import CallableWrapper


def get_all_matcher_nodes() -> List[BaseMatcherNode]:
    result = []

    for name in dir(matchers_module):
        attribute = getattr(matchers_module, name)
        try:
            if issubclass(attribute, BaseMatcherNode) and attribute is not BaseMatcherNode and attribute is not TypeOf:
                result.append(attribute())
        except TypeError:
            pass

    return result

def leave_all(function: Callable[[Any, CSTNode, CSTNode], CSTNode]) -> Callable[[Any, CSTNode, CSTNode], CSTNode]:
    for matcher in get_all_matcher_nodes():
        function = leave(matcher)(function)

    return function


class SuperTransformer(MatcherDecoratableTransformer):
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
        nodes_ids: Set[int],
        source_offsets: SourceOffsetResolver,
    ):
        self.target_coordinate = target_coordinate
        self.nodes_mapping = nodes_mapping
        self.comments = comments
        self.nodes_ids = nodes_ids
        self.source_offsets = source_offsets

        super().__init__()

    @leave_all
    def leave(self, original_node, updated_node):  # type: ignore[no-untyped-def]
        if id(original_node) in self.nodes_ids:
            return updated_node
        self.nodes_ids.add(id(original_node))

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
