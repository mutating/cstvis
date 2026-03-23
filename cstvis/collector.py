from functools import partial
from typing import Any, Callable, Dict, List, Optional, Union

from libcst import CSTNode
from printo import repred

from cstvis.dto import Context
from cstvis.wrapper import CallableWrapper


@repred(getters={'meta': lambda x: x._meta}, filters={'meta': lambda x: x})
class Collector:
    def __init__(self, meta: Optional[Dict[str, Any]] = None) -> None:
        self._meta: Dict[str, Any] = meta if meta else {}
        self._filters: List[CallableWrapper[bool]] = []
        self._converters: List[CallableWrapper[CSTNode]] = []

    def __add__(self, other: 'Collector') -> 'Collector':
        if not isinstance(other, type(self)):
            raise TypeError('Collector objects can only be added to other collector objects.')

        result = Collector()

        result._filters.extend(self._filters)
        result._filters.extend(other._filters)
        result._converters.extend(self._converters)
        result._converters.extend(other._converters)

        return result

    def filter(self, function: Optional[Union[Callable[[CSTNode], bool], Callable[[CSTNode, Context], bool]]] = None, meta: Optional[Dict[str, Any]] = None) -> Union[Union[Callable[[CSTNode], bool], Callable[[CSTNode, Context], bool]], Callable[[Union[Callable[[CSTNode], bool], Callable[[CSTNode, Context], bool]]], Union[Callable[[CSTNode], bool], Callable[[CSTNode, Context], bool]]]]:
        if function is None:
            return partial(self.filter, meta=meta)  # type: ignore[return-value]

        self._add_to_collection(function, meta, self._filters)
        return function

    def converter(self, function: Optional[Union[Callable[[CSTNode], CSTNode], Callable[[CSTNode, Context], CSTNode]]] = None, meta: Optional[Dict[str, Any]] = None) -> Union[Union[Callable[[CSTNode], CSTNode], Callable[[CSTNode, Context], CSTNode]], Callable[[Union[Callable[[CSTNode], CSTNode], Callable[[CSTNode, Context], CSTNode]]], Union[Callable[[CSTNode], CSTNode], Callable[[CSTNode, Context], CSTNode]]]]:
        if function is None:
            return partial(self.converter, meta=meta)  # type: ignore[return-value]

        self._add_to_collection(function, meta, self._converters)
        return function

    def _add_to_collection(self, function, meta, collection) -> None:
        if meta is not None:
            meta = meta.copy()
            meta.update(self._meta)
        elif self._meta:
            meta = self._meta.copy()

        collection.append(CallableWrapper(function, meta=meta))
