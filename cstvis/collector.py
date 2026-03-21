from dataclasses import dataclass, field
from typing import Callable, List

from libcst import CSTNode

from cstvis.dto import Context
from cstvis.wrapper import CallableWrapper


@dataclass
class Collector:
    _filters: List[CallableWrapper[bool]] = field(default_factory=list)
    _converters: List[CallableWrapper[CSTNode]] = field(default_factory=list)

    def filter(self, function: Callable[[CSTNode, Context], bool]) -> Callable[[CSTNode, Context], bool]:
        self._filters.append(CallableWrapper(function))
        return function

    def converter(self, function: Callable[[CSTNode, Context], CSTNode]) -> Callable[[CSTNode, Context], CSTNode]:
        self._converters.append(CallableWrapper(function))
        return function
