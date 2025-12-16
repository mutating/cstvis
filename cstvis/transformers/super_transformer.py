from typing import Any, Callable, Dict, List, Type

import libcst.matchers as matchers_module
from libcst import CSTNode, metadata
from libcst.matchers import (
    BaseMatcherNode,
    MatcherDecoratableTransformer,
    TypeOf,
    leave,
)

from cstvis.dto import Context, Coordinate


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
    ):
        self.target_coordinate = target_coordinate
        self.nodes_mapping = nodes_mapping
        self.comments = comments

        super().__init__()

    @leave_all
    def leave(self, original_node, updated_node):  # type: ignore[no-untyped-def]
        position = self.get_metadata(metadata.PositionProvider, original_node)
        coordinate = Coordinate(
            file=None,
            class_name=original_node.__class__.__name__,
            start_line=position.start.line,
            start_column=position.start.column,
            end_line=position.end.line,
            end_column=position.end.column,
        )

        if coordinate == self.target_coordinate and self.nodes_mapping.get(type(original_node)):
            context = Context(coordinate, self.comments.get(coordinate.start_line))
            converters = self.nodes_mapping[type(original_node)]
            return converters[0](updated_node, context)
        return updated_node
