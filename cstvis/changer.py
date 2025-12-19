from collections import defaultdict
from functools import cached_property
from inspect import _empty, isclass, signature
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    List,
    Optional,
    Type,
    Union,
    get_args,
    get_origin,
)

# TODO: Delete this try-except if Python's version is >= 3.10
try:
    from types import UnionType  # type: ignore[attr-defined, unused-ignore]
except ImportError:  # pragma: no cover
    from typing import Union as UnionType  # type: ignore[assignment, unused-ignore]

from libcst import CSTNode, Float, Integer, SimpleString, metadata, parse_module

from cstvis.collector import Collector
from cstvis.dto import Context, Coordinate
from cstvis.transformers.super_transformer import SuperTransformer
from cstvis.visitors.bloodhound import Bloodhound
from cstvis.visitors.comments_aggregator import CommentsAggregator


class Changer:
    def __init__(self, source: str, collector: Optional[Collector] = None) -> None:
        self.source = source
        self.module = parse_module(source)

        self.converters_by_types: Dict[Type[CSTNode], List[Callable[[CSTNode, Context], CSTNode]]] = defaultdict(list)
        self.filters_by_types: Dict[Type[CSTNode], List[Callable[[CSTNode, Context], bool]]] = defaultdict(list)

        if collector is not None:
            for collected_filter in collector._filters:
                self.filter(collected_filter)
            for collected_converter in collector._converters:
                self.converter(collected_converter)

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
        super_annotation = first_parameter.annotation if first_parameter.annotation is not _empty else CSTNode
        if super_annotation is Any:
            super_annotation = CSTNode

        try:
            annotations = self._separate_annotation(super_annotation)
        except TypeError as e:
            raise TypeError('The type annotation for the first argument of the function must be descended from the libcst.CSTNode class (or be a libcst.CSTNode class if you want to set a filter for all nodes).') from e

        for annotation in annotations:
            self.filters_by_types[annotation].append(function)

        return function

    def converter(self, function: Callable[[CSTNode, Context], CSTNode]) -> Callable[[CSTNode, Context], CSTNode]:
        converter_signature = signature(function)
        parameters = converter_signature.parameters

        if len(parameters) != 2:
            raise ValueError(f'The converter is expected to accept 2 parameters: node and context; you have passed {len(parameters)} parameters.')

        first_parameter = converter_signature.parameters[next(iter(converter_signature.parameters))]
        super_annotation = first_parameter.annotation if first_parameter.annotation is not _empty and first_parameter.annotation is not Any else CSTNode

        annotations = self._separate_annotation(super_annotation)

        for annotation in annotations:
            self.converters_by_types[annotation].append(function)

        return function

    def iterate_coordinates(self) -> Generator[Coordinate, None, None]:
        wrapper = metadata.MetadataWrapper(self.module)
        printer = Bloodhound(self.converters_by_types, self._comments_by_lines, self.filters_by_types)

        wrapper.visit(printer)
        yield from printer.coordinates

    def apply_coordinate(self, coordinate: Coordinate) -> str:
        wrapper = metadata.MetadataWrapper(self.module)
        modified = wrapper.visit(SuperTransformer(coordinate, self.converters_by_types, self._comments_by_lines, set()))
        return modified.code

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
