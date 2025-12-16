from collections import defaultdict
from functools import cached_property
from inspect import _empty, signature
from typing import Any, Callable, Dict, Generator, List, Type

from libcst import CSTNode, metadata, parse_module

from cstvis.dto import Context, Coordinate
from cstvis.errors import TwoConvertersForOneNodeError
from cstvis.transformers.super_transformer import SuperTransformer
from cstvis.visitors.bloodhound import Bloodhound
from cstvis.visitors.comments_aggregator import CommentsAggregator


class Changer:
    def __init__(self, source: str) -> None:
        self.source = source
        self.module = parse_module(source)

        self.converters_by_types: Dict[Type[CSTNode], List[Callable[[CSTNode, Context], CSTNode]]] = defaultdict(list)
        self.filters_by_types: Dict[Type[CSTNode], List[Callable[[CSTNode, Context], bool]]] = defaultdict(list)

    @cached_property
    def _comments_by_lines(self) -> Dict[int, str]:
        wrapper = metadata.MetadataWrapper(self.module)
        aggregator = CommentsAggregator()
        wrapper.visit(aggregator)
        return aggregator.comments

    def filter(self, function: Callable[[CSTNode, Context], bool]) -> Callable[[CSTNode, Context], bool]:
        converter_signature = signature(function)
        parameters = converter_signature.parameters

        if len(parameters) != 2:
            raise ValueError(f'The filter is expected to accept 2 parameters: node and context; you have passed {len(parameters)} parameters.')

        first_parameter = converter_signature.parameters[next(iter(converter_signature.parameters))]
        annotation = first_parameter.annotation if first_parameter.annotation is not _empty else CSTNode
        if annotation is Any:
            annotation = CSTNode

        if not issubclass(annotation, CSTNode):
            raise TypeError('The type annotation for the first argument of the function must be descended from the libcst.CSTNode class (or be a libcst.CSTNode class if you want to set a filter for all nodes).')

        self.filters_by_types[annotation].append(function)
        return function

    def converter(self, function: Callable[[CSTNode, Context], CSTNode]) -> Callable[[CSTNode, Context], CSTNode]:
        converter_signature = signature(function)
        parameters = converter_signature.parameters

        if len(parameters) != 2:
            raise ValueError(f'The converter is expected to accept 2 parameters: node and context; you have passed {len(parameters)} parameters.')

        first_parameter = converter_signature.parameters[next(iter(converter_signature.parameters))]
        annotation = first_parameter.annotation if first_parameter.annotation is not _empty and first_parameter.annotation is not Any else CSTNode

        if annotation is CSTNode or not issubclass(annotation, CSTNode):
            raise TypeError('The type annotation for the first argument of the function must be descended from the libcst.CSTNode class.')

        if annotation in self.converters_by_types:
            raise TwoConvertersForOneNodeError('You cannot assign 2 or more converters to the same subtype of libcst.CSTNode.')

        self.converters_by_types[annotation].append(function)
        return function

    def iterate_coordinates(self) -> Generator[Coordinate, None, None]:
        wrapper = metadata.MetadataWrapper(self.module)
        printer = Bloodhound(self.converters_by_types, self._comments_by_lines, self.filters_by_types)

        wrapper.visit(printer)
        yield from printer.coordinates

    def apply_coordinate(self, coordinate: Coordinate) -> str:
        wrapper = metadata.MetadataWrapper(self.module)
        modified = wrapper.visit(SuperTransformer(coordinate, self.converters_by_types, self._comments_by_lines))
        return modified.code
