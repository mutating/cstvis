from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

from metacode import ParsedComment, parse


@dataclass
class Coordinate:
    file: Optional[Path]
    class_name: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    converter_id: Optional[str] = None

@dataclass
class Context:
    coordinate: Coordinate
    comment: Optional[str]

    def get_metacodes(self, key: Union[str, List[str]]) -> List[ParsedComment]:
        if self.comment is None:
            return []
        return parse(self.comment, key)
