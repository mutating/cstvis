from typing import Any, Callable, Dict, List, Set, Type

import libcst.matchers as matchers_module
from libcst import CSTNode, metadata
from libcst.matchers import (
    BaseMatcherNode,
    MatcherDecoratableTransformer,
    TypeOf,
    leave,
)

from cstvis.dto import Context, Coordinate
from cstvis.utils.function_id import get_function_id


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
    METADATA_DEPENDENCIES = (metadata.PositionProvider,)

    def __init__(
        self,
        target_coordinate: Coordinate,
        nodes_mapping: Dict[Type[CSTNode], List[Callable[[CSTNode, Context], CSTNode]]],
        comments: Dict[int, str],
        nodes_ids: Set[int],
    ):
        self.target_coordinate = target_coordinate
        self.nodes_mapping = nodes_mapping
        self.comments = comments
        self.nodes_ids = nodes_ids

        super().__init__()

    @leave_all
    def leave(self, original_node, updated_node):  # type: ignore[no-untyped-def]
        if id(original_node) in self.nodes_ids:
            return updated_node
        self.nodes_ids.add(id(original_node))

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

        converters = self.nodes_mapping.get(type(original_node), []) + self.nodes_mapping.get(CSTNode, [])  # type: ignore[type-abstract]

        if coordinate == target_coordinate_without_converter_id and converters:
            context = Context(coordinate, self.comments.get(coordinate.start_line))
            for converter in converters:  # pragma: no branch
                if get_function_id(converter) == self.target_coordinate.converter_id:
                    return converter(updated_node, context)
        return updated_node
