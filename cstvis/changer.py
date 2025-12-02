from multiprocessing import Value
from typing import Callable, List, Dict, Generator, Union, Optional
from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict
from inspect import signature, _empty
from functools import cached_property

from libcst import Comment, CSTNode, CSTVisitor, parse_module, metadata


@dataclass
class Coordinate:
    file: Optional[Path]
    class_name: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int


class Bloodhound(CSTVisitor):
    METADATA_DEPENDENCIES = (metadata.PositionProvider,)

    def __init__(
        self,
        nodes_mapping: Dict[CSTNode, List[Callable[[CSTNode, Coordinate, Optional[str]], bool]]],
        comments: Dict[int, str],
    ) -> None:
        self.coordinates: List[Coordinate] = []
        self.nodes_mapping = nodes_mapping
        self.comments = comments

    def on_visit(self, node: CSTNode) -> bool:
        if type(node) in self.nodes_mapping:
            position = self.get_metadata(metadata.PositionProvider, node)
            print('KEK', self.comments.get(position.start.line), position.start.line)

            self.coordinates.append(
                Coordinate(
                    file=None,
                    class_name=node.__class__.__name__,
                    start_line=position.start.line,
                    start_column=position.start.column,
                    end_line=position.end.line,
                    end_column=position.end.column,
                ),
            )

        return True


class CommentsAggregator(CSTVisitor):
    METADATA_DEPENDENCIES = (metadata.PositionProvider,)

    def __init__(self) -> None:
        self.comments: Dict[int, str] = {}

    def on_visit(self, node: CSTNode) -> bool:
        if isinstance(node, Comment):
            position = self.get_metadata(metadata.PositionProvider, node)
            self.comments[position.start.line] = node.value
        return True


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
