from typing import Any, Dict, List, Optional

from libcst import CSTNode, CSTVisitor
from libcst.metadata import CodePosition, CodeRange

from cstvis import Context, Coordinate
from cstvis.dto import SourcePosition


class _NodeCollector(CSTVisitor):
    """Collect nodes in CST traversal order."""

    def __init__(self) -> None:
        self.nodes: List[CSTNode] = []

    def on_visit(self, node: CSTNode) -> bool:
        self.nodes.append(node)
        return True


def collect_nodes(module: CSTNode) -> List[CSTNode]:
    """Return all nodes of the module in plain CST traversal order."""
    collector = _NodeCollector()
    module.visit(collector)
    return collector.nodes


def make_add_context(meta: Optional[Dict[str, Any]] = None) -> Context:
    """Build a minimal Context for an Add node in `1 + 2`."""
    coordinate = Coordinate(None, 'Add', 1, 2, 1, 3)
    node_range = CodeRange(CodePosition(1, 1), CodePosition(1, 4))
    position = SourcePosition(coordinate, '1 + 2', node_range, lambda _node_range: (1, 4))
    return Context(position, None, meta)


def make_integer_context(meta: Optional[Dict[str, Any]] = None, *, comment: Optional[str] = None) -> Context:
    """Build a Context for a single Integer node at column zero."""
    coordinate = Coordinate(None, 'Integer', 1, 0, 1, 1)
    node_range = CodeRange(CodePosition(1, 0), CodePosition(1, 1))
    position = SourcePosition(coordinate, '1', node_range, lambda _node_range: (0, 1))
    return Context(position, comment, meta)

