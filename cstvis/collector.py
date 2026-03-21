from dataclasses import dataclass, field
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Union

from libcst import CSTNode

from cstvis.dto import Context
from cstvis.wrapper import CallableWrapper


@dataclass
class Collector:
    _filters: List[CallableWrapper[bool]] = field(default_factory=list)
    _converters: List[CallableWrapper[CSTNode]] = field(default_factory=list)

    def filter(self, function: Optional[Union[Callable[[CSTNode], bool], Callable[[CSTNode, Context], bool]]] = None, meta: Optional[Dict[str, Any]] = None) -> Union[Union[Callable[[CSTNode], bool], Callable[[CSTNode, Context], bool]], Callable[[Union[Callable[[CSTNode], bool], Callable[[CSTNode, Context], bool]]], Union[Callable[[CSTNode], bool], Callable[[CSTNode, Context], bool]]]]:
        if function is None:
            return partial(self.filter, meta=meta)  # type: ignore[return-value]

        self._filters.append(CallableWrapper(function, meta=meta))
        return function

    def converter(self, function: Optional[Union[Callable[[CSTNode], CSTNode], Callable[[CSTNode, Context], CSTNode]]] = None, meta: Optional[Dict[str, Any]] = None) -> Union[Union[Callable[[CSTNode], CSTNode], Callable[[CSTNode, Context], CSTNode]], Callable[[Union[Callable[[CSTNode], CSTNode], Callable[[CSTNode, Context], CSTNode]]], Union[Callable[[CSTNode], CSTNode], Callable[[CSTNode, Context], CSTNode]]]]:
        if function is None:
            return partial(self.converter, meta=meta)  # type: ignore[return-value]

        self._converters.append(CallableWrapper(function, meta=meta))
        return function
