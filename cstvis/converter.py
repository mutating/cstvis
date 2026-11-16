from functools import partial, update_wrapper
from typing import Any, Callable, Dict, Iterable, List, Optional, Type, Union

from libcst import CSTNode
from printo import repred

from cstvis.dto import Context
from cstvis.exceptions import ConverterWrappingError
from cstvis.wrapper import CallableWrapper, _unwrap_partial

ConverterFunction = Union[Callable[[CSTNode], CSTNode], Callable[[CSTNode, Context], CSTNode]]
ConverterFilter = Union[Callable[[CSTNode], bool], Callable[[CSTNode, Context], bool]]


@repred(prefer_positional=True, getters={'function': lambda x: x.function, 'meta': lambda x: x.meta})
class Converter(CallableWrapper[CSTNode]):
    """
    Represent a converter registered in a Changer or Collector.

    Ordinary calls are forwarded to the wrapped function, and the original
    signature is preserved. The object also stores filters that restrict only
    this converter.
    """

    def __init__(self, function: ConverterFunction, meta: Optional[Dict[str, Any]] = None) -> None:
        if isinstance(_unwrap_partial(function), Converter):
            raise ConverterWrappingError('A converter cannot be wrapped in another converter.')

        super().__init__(function, meta=meta)
        update_wrapper(self, function, updated=())
        self.filters: List[CallableWrapper[bool]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> CSTNode:
        return self.function(*args, **kwargs)

    def filter(
        self,
        function: Optional[ConverterFilter] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Union[ConverterFilter, Callable[[ConverterFilter], ConverterFilter]]:
        if function is None:
            return partial(self.filter, meta=meta)  # type: ignore[return-value]

        self.filters.append(CallableWrapper(function, meta=meta))
        return function


def resolve_converters(nodes_mapping: Dict[Type[CSTNode], List[Converter]], node_type: Type[CSTNode]) -> Dict[Converter, str]:
    """Return specific and catch-all converters for a node type, with coordinate ids."""
    converters = nodes_mapping.get(node_type, []) + nodes_mapping.get(CSTNode, [])  # type: ignore[type-abstract]
    return build_converter_ids(converters)


def build_converter_ids(converters: Iterable[Converter]) -> Dict[Converter, str]:
    """
    Assign coordinate ids to converters while preserving the usual function-based format.

    If several distinct Converter objects share the same function id, later ones receive
    a numeric suffix so a coordinate always resolves back to the converter that produced it.
    """
    result: Dict[Converter, str] = {}
    occurrences: Dict[str, int] = {}

    for converter in dict.fromkeys(converters):
        function_id = converter.get_function_id()
        occurrence = occurrences.get(function_id, 0)
        occurrences[function_id] = occurrence + 1
        result[converter] = function_id if occurrence == 0 else f'{function_id}#{occurrence}'

    return result
