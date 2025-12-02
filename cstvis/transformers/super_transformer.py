from typing import List

import libcst.matchers as matchers_module
from libcst import Add, Subtract, metadata
from libcst.matchers import BaseMatcherNode, TypeOf, MatcherDecoratableTransformer, leave


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

    @leave_all
    def leave(self, original_node, updated_node):
        position = self.get_metadata(metadata.PositionProvider, original_node)
        if isinstance(original_node, Add):
            # Возвращаем новый узел Subtract вместо Add
            return Subtract(
                whitespace_before=original_node.whitespace_before,
                whitespace_after=original_node.whitespace_after,
            )
        else:
            return updated_node
