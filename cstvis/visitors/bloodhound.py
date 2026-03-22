from copy import deepcopy
from typing import Dict, List, Type

from libcst import CSTNode, CSTVisitor, metadata

from cstvis.dto import Context, Coordinate
from cstvis.wrapper import CallableWrapper


class Bloodhound(CSTVisitor):
    METADATA_DEPENDENCIES = (metadata.PositionProvider,)

    def __init__(
        self,
        nodes_mapping: Dict[Type[CSTNode], List[CallableWrapper[CSTNode]]],
        comments: Dict[int, str],
        filters: Dict[Type[CSTNode], List[CallableWrapper[bool]]],
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

        converters = self.nodes_mapping.get(type(node), []) + self.nodes_mapping.get(CSTNode, [])  # type: ignore[type-abstract]

        if converters:
            filters = self.filters.get(type(node), []) + self.filters.get(CSTNode, [])  # type: ignore[type-abstract]
            context = Context(coordinate, self.comments.get(coordinate.start_line))
            if filters:
                for filter_function in filters:
                    if not filter_function(node, context):
                        return True
            for converter_id in set([x.get_function_id() for x in converters]):
                emitting_coordinate = deepcopy(coordinate)
                emitting_coordinate.converter_id = converter_id
                self.coordinates.append(
                    emitting_coordinate,
                )

        return True
