from multiprocessing import Value
from typing import Callable, List, Dict, Generator, Union, Optional
from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict
from inspect import signature, _empty

from libcst import CSTNode, CSTVisitor, parse_module, metadata


@dataclass
class Coordinate:
    file: Optional[Path]
    class_name: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int

@dataclass
class Comment:
    coordinate: Coordinate
    text: str

class Bloodhound(CSTVisitor):
    METADATA_DEPENDENCIES = (metadata.PositionProvider,)

    def __init__(self, nodes_mapping: Dict[CSTNode, List[Callable[[CSTNode, Coordinate, Optional[str]], bool]]]) -> None:
        self.coordinates: List[Coordinate] = []
        self.nodes_mapping = nodes_mapping

    def on_visit(self, node: CSTNode) -> bool:
        if type(node) in self.nodes_mapping:
            position = self.get_metadata(metadata.PositionProvider, node)

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


class Changer:
    def __init__(self, source: str) -> None:
        self.source = source
        self.module = parse_module(source)

        self.filters = []
        self.converters = []

        self.converters_by_types = defaultdict(list)

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
        printer = Bloodhound(self.converters_by_types)

        wrapper.visit(printer)
        yield from printer.coordinates

    def apply_coordinate(self, coordinate: Coordinate) -> None:
        # TODO: fill it
        pass

    def change(self) -> str:
        # TODO: fill it
        return self.source
