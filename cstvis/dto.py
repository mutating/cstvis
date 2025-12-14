from typing import List, Union, Optional
from dataclasses import dataclass
from pathlib import Path

from metacode import parse, ParsedComment


@dataclass
class Coordinate:
    file: Optional[Path]
    class_name: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int

@dataclass
class Context:
    coordinate: Coordinate
    comment: Optional[str]

    def get_metacodes(self, key: Union[str, List[str]]) -> List[ParsedComment]:
        if self.comment is None:
            return []
        return parse(self.comment, key)
