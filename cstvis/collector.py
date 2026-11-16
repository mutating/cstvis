from functools import partial
from typing import Any, Callable, Dict, List, Optional, Union

from printo import repred

from cstvis.converter import Converter, ConverterFilter, ConverterFunction
from cstvis.wrapper import CallableWrapper


@repred(getters={'meta': lambda x: x._meta}, filters={'meta': lambda x: x})
class Collector:
    def __init__(self, meta: Optional[Dict[str, Any]] = None) -> None:
        self._meta: Dict[str, Any] = meta if meta else {}
        self._filters: List[CallableWrapper[bool]] = []
        self._converters: List[Converter] = []

    def __add__(self, other: 'Collector') -> 'Collector':
        if not isinstance(other, type(self)):
            raise TypeError('Collector objects can only be added to other collector objects.')

        result = Collector()

        result._filters.extend(self._filters)
        result._filters.extend(other._filters)
        result._converters.extend(self._converters)
        result._converters.extend(other._converters)

        return result

    def filter(self, function: Optional[ConverterFilter] = None, meta: Optional[Dict[str, Any]] = None) -> Union[ConverterFilter, Callable[[ConverterFilter], ConverterFilter]]:
        if function is None:
            return partial(self.filter, meta=meta)  # type: ignore[return-value]

        self._filters.append(CallableWrapper(function, meta=self._merge_meta(meta)))
        return function

    def converter(self, function: Optional[ConverterFunction] = None, meta: Optional[Dict[str, Any]] = None) -> Union[Converter, Callable[[ConverterFunction], Converter]]:
        if function is None:
            return partial(self.converter, meta=meta)  # type: ignore[return-value]

        converter = Converter(function, meta=self._merge_meta(meta))
        self._converters.append(converter)
        return converter

    def _merge_meta(self, meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if meta is None:
            return self._meta.copy() if self._meta else None

        return {**self._meta, **meta}
