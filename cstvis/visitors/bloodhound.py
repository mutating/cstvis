from typing import Callable, List, Dict, Type, Optional

from libcst import CSTNode, CSTVisitor, metadata

from cstvis.dto import Coordinate, Context


class Bloodhound(CSTVisitor):
    METADATA_DEPENDENCIES = (metadata.PositionProvider,)

    def __init__(
        self,
        nodes_mapping: Dict[Type[CSTNode], List[Callable[[CSTNode, Coordinate, Optional[str]], bool]]],
        comments: Dict[int, str],
        filters: Dict[Type[CSTNode], List[Callable[[CSTNode, Context], bool]]],
    ) -> None:
        self.coordinates: List[Coordinate] = []
        self.nodes_mapping = nodes_mapping
        self.comments = comments
        self.filters = filters

    def on_visit(self, node: CSTNode) -> bool:
        position = self.get_metadata(metadata.PositionProvider, node)
        coordinate = Coordinate(
            file=None,
            class_name=node.__class__.__name__,
            start_line=position.start.line,
            start_column=position.start.column,
            end_line=position.end.line,
            end_column=position.end.column,
        )

        if self.nodes_mapping.get(type(node)) or self.nodes_mapping.get(CSTNode):
            filters = self.filters.get(type(node), []) + self.filters.get(CSTNode, [])
            context = Context(coordinate, self.comments.get(coordinate.start_line))
            if filters:
                for filter in filters:
                    if not filter(node, context):
                        return True
            self.coordinates.append(
                coordinate,
            )

        return True
