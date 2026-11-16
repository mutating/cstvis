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

from functools import cached_property, partial
from inspect import Parameter, _empty, isclass, signature

from libcst import CSTNode, Float, Integer, SimpleString
from printo import repred
from sigmatch import PossibleCallMatcher, SignatureMismatchError

from cstvis.dto import Context

FilterOrConverterReturnValue = TypeVar('FilterOrConverterReturnValue')


def _partial_binds_node(function: Any) -> bool:
    while isinstance(function, partial):
        if function.args:
            return True
        function = function.func
    return False


def _unwrap_partial(function: Any) -> Any:
    while isinstance(function, partial):
        function = function.func
    return function


@repred(prefer_positional=True)
class CallableWrapper(Generic[FilterOrConverterReturnValue]):
    matcher = PossibleCallMatcher('.') + PossibleCallMatcher('..')

    def __init__(self, function: Union[Callable[[CSTNode], FilterOrConverterReturnValue], Callable[[CSTNode, Context], FilterOrConverterReturnValue]], meta: Optional[Dict[str, Any]] = None) -> None:
        if not self.matcher.match(function):
            raise SignatureMismatchError('A function that takes a CST node and a context is expected.')

        parameters = signature(function).parameters.values()
        if not any(parameter.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD, Parameter.VAR_POSITIONAL) for parameter in parameters) or _partial_binds_node(function):  # pragma: no branch
            raise SignatureMismatchError('A function that takes a CST node and a context is expected.')

        self.function = function
        self.meta = meta
        self._takes_positional_context = PossibleCallMatcher('..').match(function)

    def __call__(self, node: CSTNode, context: Context) -> FilterOrConverterReturnValue:
        return self.call_with_context(node, context)

    def call_with_context(self, node: CSTNode, context: Context) -> FilterOrConverterReturnValue:
        if self._has_keyword_context:
            return self.function(node, context=self._context_with_meta(context))  # type: ignore[call-arg]

        if self._takes_positional_context:
            return self.function(node, self._context_with_meta(context))  # type: ignore[call-arg]

        return self.function(node)  # type: ignore[call-arg]

    def _context_with_meta(self, context: Context) -> Context:
        return replace(context, meta=self.meta.copy() if isinstance(self.meta, dict) else None)

    @cached_property
    def _has_keyword_context(self) -> bool:
        parameters = list(signature(self.function).parameters.values())

        for parameter in parameters[1:]:
            if parameter.name == 'context' and parameter.kind == Parameter.KEYWORD_ONLY:
                return True
            if parameter.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD) and parameter.default is _empty:
                return False

        return False

    def get_function_id(self) -> str:
        function: Any = _unwrap_partial(self.function)
        if not hasattr(function, '__code__'):
            function = function.__call__

        return f'{function.__module__}:{function.__name__}:{function.__code__.co_firstlineno}'

    @cached_property
    def first_node_annotations(self) -> List[Type[CSTNode]]:
        first_parameter = next(iter(signature(self.function).parameters.values()))
        super_annotation = first_parameter.annotation if first_parameter.annotation is not _empty and first_parameter.annotation is not Any else CSTNode

        return self._separate_annotation(super_annotation)

    def _separate_annotation(self, annotation: Union[Type[CSTNode], Any]) -> List[Type[CSTNode]]:
        if isclass(annotation) and issubclass(annotation, CSTNode):
            return [annotation]

        if get_origin(annotation) is Union or get_origin(annotation) is UnionType:
            result = []
            for argument in get_args(annotation):
                result.extend(self._separate_annotation(argument))
            return result

        if annotation is int:
            return [Integer]

        if annotation is float:
            return [Float]

        if annotation is str:
            return [SimpleString]

        raise TypeError('The type annotation for the first argument of the function must be descended from the libcst.CSTNode class.')
