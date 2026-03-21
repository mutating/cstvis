from functools import wraps
from typing import (
    Callable,
    Generic,
    TypeVar,
)

from libcst import CSTNode
from printo import repred
from sigmatch import PossibleCallMatcher, SignatureMismatchError

from cstvis.dto import Context

FilterOrConverterReturnValue = TypeVar('FilterOrConverterReturnValue')

@repred(prefer_positional=True)  # type: ignore[call-overload]
class CallableWrapper(Generic[FilterOrConverterReturnValue]):
    matcher = PossibleCallMatcher('..')

    def __init__(self, function: Callable[[CSTNode, Context], FilterOrConverterReturnValue]) -> None:
        if not self.matcher.match(function):
            raise SignatureMismatchError('A function that takes a CST node and a context is expected.')

        self.function = function
        wraps(function)(self)

    def __call__(self, node: CSTNode, context: Context) -> FilterOrConverterReturnValue:
        return self.function(node, context)

    def get_function_id(self) -> str:
        return f'{self.function.__module__}:{self.function.__name__}:{self.function.__code__.co_firstlineno}'
