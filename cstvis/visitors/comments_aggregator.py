from typing import Dict

from libcst import Comment, CSTNode, CSTVisitor, metadata


class CommentsAggregator(CSTVisitor):
    METADATA_DEPENDENCIES = (metadata.PositionProvider,)

    def __init__(self) -> None:
        self.comments: Dict[int, str] = {}

    def on_visit(self, node: CSTNode) -> bool:
        if isinstance(node, Comment):
            position = self.get_metadata(metadata.PositionProvider, node)
            self.comments[position.start.line] = node.value[1:]
        return True
