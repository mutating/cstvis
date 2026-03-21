from functools import wraps
from typing import (
    Callable,
    Generic,
    TypeVar,
)

from libcst import CSTNode
from printo import repred

from cstvis.dto import Context

FilterOrConverterReturnValue = TypeVar('FilterOrConverterReturnValue')

@repred(prefer_positional=True)
class CallableWrapper(Generic[FilterOrConverterReturnValue]):
    def __init__(self, filter_or_converter: Callable[[CSTNode, Context], FilterOrConverterReturnValue]) -> None:
        self.filter_or_converter = filter_or_converter
        wraps(filter_or_converter)(self)

    def __call__(self, node: CSTNode, context: Context) -> FilterOrConverterReturnValue:
        return self.filter_or_converter(node, context)

    def get_function_id(self) -> str:
        return f'{self.filter_or_converter.__module__}:{self.filter_or_converter.__name__}:{self.filter_or_converter.__code__.co_firstlineno}'
