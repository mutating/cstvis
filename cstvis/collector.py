from dataclasses import dataclass, field
from functools import partial
from typing import Callable, List, Optional, Union

from libcst import CSTNode

from cstvis.dto import Context
from cstvis.wrapper import CallableWrapper


@dataclass
class Collector:
    _filters: List[CallableWrapper[bool]] = field(default_factory=list)
    _converters: List[CallableWrapper[CSTNode]] = field(default_factory=list)

    def filter(self, function: Optional[Union[Callable[[CSTNode], bool], Callable[[CSTNode, Context], bool]]] = None) -> Union[Union[Callable[[CSTNode], bool], Callable[[CSTNode, Context], bool]], Callable[[Union[Callable[[CSTNode], bool], Callable[[CSTNode, Context], bool]]], Union[Callable[[CSTNode], bool], Callable[[CSTNode, Context], bool]]]]:
        if function is None:
            return partial(self.filter)

        self._filters.append(CallableWrapper(function))
        return function

    def converter(self, function: Optional[Union[Callable[[CSTNode], CSTNode], Callable[[CSTNode, Context], CSTNode]]] = None) -> Union[Union[Callable[[CSTNode], CSTNode], Callable[[CSTNode, Context], CSTNode]], Callable[[Union[Callable[[CSTNode], CSTNode], Callable[[CSTNode, Context], CSTNode]]], Union[Callable[[CSTNode], CSTNode], Callable[[CSTNode, Context], CSTNode]]]]:
        if function is None:
            return partial(self.converter)

        self._converters.append(CallableWrapper(function))
        return function
