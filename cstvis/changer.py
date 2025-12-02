from typing import Callable, List, Dict, Generator, Optional
from pathlib import Path
from collections import defaultdict
from inspect import signature, _empty
from functools import cached_property

from libcst import CSTNode, parse_module, metadata

from cstvis.visitors.comments_aggregator import CommentsAggregator
from cstvis.visitors.bloodhound import Bloodhound
from cstvis.dto import Coordinate


class Changer:
    def __init__(self, source: str) -> None:
        self.source = source
        self.module = parse_module(source)

        self.filters = []
        self.converters = []

        self.converters_by_types = defaultdict(list)

    @cached_property
    def comments_by_lines(self) -> Dict[int, str]:
        wrapper = metadata.MetadataWrapper(self.module)
        aggregator = CommentsAggregator()
        wrapper.visit(aggregator)
        print(aggregator.comments)
        return aggregator.comments

    def filter(self, function: Callable[[CSTNode, Coordinate, Optional[str], List[str]], bool]) -> Callable[[CSTNode, Coordinate, Optional[str], List[str]], bool]:
        self.filters.append(function)
        return function

    def converter(self, function: Callable[[CSTNode, Coordinate, Optional[str]], bool]) -> Callable[[CSTNode, Coordinate, Optional[str]], bool]:
        converter_signature = signature(function)
        parameters = converter_signature.parameters

        if len(parameters) != 3:
            raise ValueError

        first_parameter = converter_signature.parameters[list(converter_signature.parameters)[0]]
        annotation = first_parameter.annotation if first_parameter.annotation is not _empty else CSTNode

        if not issubclass(annotation, CSTNode):
            raise ValueError

        self.converters.append(function)
        self.converters_by_types[annotation].append(function)
        return function

    def iterate_coordinates(self) -> Generator[Coordinate, None, None]:
        wrapper = metadata.MetadataWrapper(self.module)
        printer = Bloodhound(self.converters_by_types, self.comments_by_lines)

        wrapper.visit(printer)
        yield from printer.coordinates

    def apply_coordinate(self, coordinate: Coordinate) -> None:
        # TODO: fill it
        pass

    def change(self) -> str:
        # TODO: fill it
        return self.source
