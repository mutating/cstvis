from typing import List, Dict, Type, Callable, Optional

import libcst.matchers as matchers_module
from libcst import Add, Subtract, CSTNode, metadata
from libcst.matchers import BaseMatcherNode, TypeOf, MatcherDecoratableTransformer, leave

from cstvis.dto import Coordinate, Context


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

def leave_all(function):
    for matcher in get_all_matcher_nodes():
        function = leave(matcher)(function)

    return function


class SuperTransformer(MatcherDecoratableTransformer):
    METADATA_DEPENDENCIES = (metadata.PositionProvider,)

    def __init__(
        self,
        target_coordinate: Coordinate,
        nodes_mapping: Dict[Type[CSTNode], List[Callable[[CSTNode, Context], bool]]],
        comments: Dict[int, str],
    ):
        self.target_coordinate = target_coordinate
        self.nodes_mapping = nodes_mapping
        self.comments = comments

        super().__init__()

    @leave_all
    def leave(self, original_node, updated_node):
        position = self.get_metadata(metadata.PositionProvider, original_node)
        coordinate = Coordinate(
            file=None,
            class_name=original_node.__class__.__name__,
            start_line=position.start.line,
            start_column=position.start.column,
            end_line=position.end.line,
            end_column=position.end.column,
        )

        if coordinate == self.target_coordinate and type(original_node) in self.nodes_mapping:
            for converter in self.nodes_mapping[type(original_node)]:
                context = Context(coordinate, self.comments.get(coordinate.start_line))
                return converter(updated_node, context)
        else:
            return updated_node
