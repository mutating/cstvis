from dataclasses import replace
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

# TODO: Delete this try-except if Python's version is >= 3.10
try:
    from types import UnionType  # type: ignore[attr-defined, unused-ignore]
except ImportError:  # pragma: no cover
    from typing import Union as UnionType  # type: ignore[assignment, unused-ignore]

from functools import cached_property
from inspect import _empty, isclass, signature

from libcst import CSTNode, Float, Integer, SimpleString
from printo import repred
from sigmatch import PossibleCallMatcher, SignatureMismatchError

from cstvis.dto import Context

FilterOrConverterReturnValue = TypeVar('FilterOrConverterReturnValue')

@repred(prefer_positional=True)
class CallableWrapper(Generic[FilterOrConverterReturnValue]):
    matcher = PossibleCallMatcher('.') + PossibleCallMatcher('..')

    def __init__(self, function: Union[Callable[[CSTNode], FilterOrConverterReturnValue], Callable[[CSTNode, Context], FilterOrConverterReturnValue]], meta: Optional[Dict[str, Any]] = None) -> None:
        if not self.matcher.match(function):
            raise SignatureMismatchError('A function that takes a CST node and a context is expected.')

        self.function = function
        self.meta = meta

    def __call__(self, node: CSTNode, context: Context) -> FilterOrConverterReturnValue:
        if PossibleCallMatcher('..').match(self.function):
            callback_context = replace(context, meta=self.meta.copy() if isinstance(self.meta, dict) else None)
            return self.function(node, callback_context)  # type: ignore[call-arg]

        return self.function(node)  # type: ignore[call-arg]

    def get_function_id(self) -> str:
        return f'{self.function.__module__}:{self.function.__name__}:{self.function.__code__.co_firstlineno}'

    @cached_property
    def first_node_annotations(self) -> List[Type[CSTNode]]:
        converter_signature = signature(self.function)

        first_parameter = converter_signature.parameters[next(iter(converter_signature.parameters))]
        super_annotation = first_parameter.annotation if first_parameter.annotation is not _empty and first_parameter.annotation is not Any else CSTNode

        return self._separate_annotation(super_annotation)

    def _separate_annotation(self, annotation: Union[Type[CSTNode], Any]) -> List[Type[CSTNode]]:
        if isclass(annotation) and issubclass(annotation, CSTNode):
            return [annotation]

        if get_origin(annotation) is Union or get_origin(annotation) is UnionType:
            result = []
            for argument in get_args(annotation):
                result += self._separate_annotation(argument)
            return result

        if annotation is int:
            return [Integer]

        if annotation is float:
            return [Float]

        if annotation is str:
            return [SimpleString]

        raise TypeError('The type annotation for the first argument of the function must be descended from the libcst.CSTNode class.')
