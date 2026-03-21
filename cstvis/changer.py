from collections import defaultdict
from functools import cached_property, partial
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    List,
    Optional,
    Type,
    Union,
)

from libcst import CSTNode, metadata, parse_module

from cstvis.collector import Collector
from cstvis.dto import Context, Coordinate
from cstvis.transformers.super_transformer import SuperTransformer
from cstvis.visitors.bloodhound import Bloodhound
from cstvis.visitors.comments_aggregator import CommentsAggregator
from cstvis.wrapper import CallableWrapper


class Changer:
    def __init__(self, source: str, collector: Optional[Collector] = None) -> None:
        self.source = source
        self.module = parse_module(source)

        self.converters_by_types: Dict[Type[CSTNode], List[CallableWrapper[CSTNode]]] = defaultdict(list)
        self.filters_by_types: Dict[Type[CSTNode], List[CallableWrapper[bool]]] = defaultdict(list)

        if collector is not None:
            for collected_filter in collector._filters:
                self.filter(collected_filter.function)
            for collected_converter in collector._converters:
                self.converter(collected_converter.function)

    @cached_property
    def _comments_by_lines(self) -> Dict[int, str]:
        wrapper = metadata.MetadataWrapper(self.module)
        aggregator = CommentsAggregator()
        wrapper.visit(aggregator)
        return aggregator.comments

    def filter(self, function: Optional[Union[Callable[[CSTNode], bool], Callable[[CSTNode, Context], bool]]] = None, meta: Optional[Dict[str, Any]] = None) -> Union[Union[Callable[[CSTNode], bool], Callable[[CSTNode, Context], bool]], Callable[[Union[Callable[[CSTNode], bool], Callable[[CSTNode, Context], bool]]], Union[Callable[[CSTNode], bool], Callable[[CSTNode, Context], bool]]]]:
        if function is None:
            return partial(self.filter, meta=meta)  # type: ignore[return-value]

        wrapper = CallableWrapper(function, meta=meta)

        for annotation in wrapper.first_node_annotations:
            self.filters_by_types[annotation].append(wrapper)

        return function

    def converter(self, function: Optional[Union[Callable[[CSTNode], CSTNode], Callable[[CSTNode, Context], CSTNode]]] = None, meta: Optional[Dict[str, Any]] = None) -> Union[Union[Callable[[CSTNode], CSTNode], Callable[[CSTNode, Context], CSTNode]], Callable[[Union[Callable[[CSTNode], CSTNode], Callable[[CSTNode, Context], CSTNode]]], Union[Callable[[CSTNode], CSTNode], Callable[[CSTNode, Context], CSTNode]]]]:
        if function is None:
            return partial(self.converter, meta=meta)  # type: ignore[return-value]

        wrapper = CallableWrapper(function, meta=meta)

        for annotation in wrapper.first_node_annotations:
            self.converters_by_types[annotation].append(wrapper)

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
