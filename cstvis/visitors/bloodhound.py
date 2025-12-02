from typing import Callable, List, Dict, Type, Optional

from libcst import CSTNode, CSTVisitor, metadata

from cstvis.dto import Coordinate


class Bloodhound(CSTVisitor):
    METADATA_DEPENDENCIES = (metadata.PositionProvider,)

    def __init__(
        self,
        nodes_mapping: Dict[Type[CSTNode], List[Callable[[CSTNode, Coordinate, Optional[str]], bool]]],
        comments: Dict[int, str],
    ) -> None:
        self.coordinates: List[Coordinate] = []
        self.nodes_mapping = nodes_mapping
        self.comments = comments

    def on_visit(self, node: CSTNode) -> bool:
        if type(node) in self.nodes_mapping or CSTNode in self.nodes_mapping:
            position = self.get_metadata(metadata.PositionProvider, node)

            self.coordinates.append(
                Coordinate(
                    file=None,
                    class_name=node.__class__.__name__,
                    start_line=position.start.line,
                    start_column=position.start.column,
                    end_line=position.end.line,
                    end_column=position.end.column,
                ),
            )

        return True
