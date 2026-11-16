from collections import defaultdict
from functools import cached_property, partial
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    List,
    Optional,
    Tuple,
    Type,
    Union,
)

from libcst import CSTNode, metadata, parse_module

from cstvis.collector import Collector
from cstvis.converter import Converter, ConverterFilter, ConverterFunction
from cstvis.dto import Coordinate
from cstvis.source_offsets import SourceOffsetResolver, restore_codegen_prefix
from cstvis.transformers.super_transformer import SuperTransformer
from cstvis.visitors.bloodhound import Bloodhound
from cstvis.visitors.comments_aggregator import CommentsAggregator
from cstvis.wrapper import CallableWrapper


class Changer:
    def __init__(self, source: str, collector: Optional[Collector] = None) -> None:
        self.source = source
        self.module = parse_module(source)

        self.converters_by_types: Dict[Type[CSTNode], List[Converter]] = defaultdict(list)
        self.filters_by_types: Dict[Type[CSTNode], List[CallableWrapper[bool]]] = defaultdict(list)

        if collector is not None:
            for collected_filter in collector._filters:
                self._register_filter(collected_filter)
            for collected_converter in collector._converters:
                self._register_converter(collected_converter)

    @cached_property
    def _traversal(self) -> Tuple[metadata.MetadataWrapper, SourceOffsetResolver]:
        wrapper = metadata.MetadataWrapper(self.module)
        node_ranges = wrapper.resolve(metadata.WhitespaceInclusivePositionProvider)
        return wrapper, SourceOffsetResolver(wrapper.module, self.source, node_ranges.values())

    @cached_property
    def _comments_by_lines(self) -> Dict[int, str]:
        aggregator = CommentsAggregator()
        self._traversal[0].visit(aggregator)
        return aggregator.comments

    def filter(self, function: Optional[ConverterFilter] = None, meta: Optional[Dict[str, Any]] = None) -> Union[ConverterFilter, Callable[[ConverterFilter], ConverterFilter]]:
        if function is None:
            return partial(self.filter, meta=meta)  # type: ignore[return-value]

        self._register_filter(CallableWrapper(function, meta=meta))
        return function

    def converter(self, function: Optional[ConverterFunction] = None, meta: Optional[Dict[str, Any]] = None) -> Union[Converter, Callable[[ConverterFunction], Converter]]:
        if function is None:
            return partial(self.converter, meta=meta)  # type: ignore[return-value]

        converter = Converter(function, meta=meta)
        self._register_converter(converter)
        return converter

    def _register_filter(self, wrapper: CallableWrapper[bool]) -> None:
        for annotation in wrapper.first_node_annotations:
            self.filters_by_types[annotation].append(wrapper)

    def _register_converter(self, converter: Converter) -> None:
        for annotation in converter.first_node_annotations:
            self.converters_by_types[annotation].append(converter)

    def iterate_coordinates(self) -> Generator[Coordinate, None, None]:
        wrapper, source_offsets = self._traversal
        printer = Bloodhound(self.converters_by_types, self._comments_by_lines, self.filters_by_types, source_offsets)

        wrapper.visit(printer)
        yield from printer.coordinates

    def apply_coordinate(self, coordinate: Coordinate) -> str:
        wrapper, source_offsets = self._traversal
        modified = wrapper.visit(SuperTransformer(coordinate, self.converters_by_types, self._comments_by_lines, source_offsets))
        return restore_codegen_prefix(self.source, modified.code)
