from typing import List, Callable
from dataclasses import dataclass, field

from libcst import CSTNode

from cstvis.dto import Context


@dataclass
class Collector:
    filters: List[Callable[[CSTNode, Context], bool]] = field(default_factory=list)
    converters: List[Callable[[CSTNode, Context], CSTNode]] = field(default_factory=list)

    def filter(self, function: Callable[[CSTNode, Context], bool]) -> Callable[[CSTNode, Context], bool]:
        self.filters.append(function)
        return function

    def converter(self, function: Callable[[CSTNode, Context], CSTNode]) -> Callable[[CSTNode, Context], CSTNode]:
        self.converters.append(function)
        return function
