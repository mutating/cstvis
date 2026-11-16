from typing import Dict, Iterable, List, Optional, Set, Tuple

from libcst import Module
from libcst._nodes.internal import CodegenState
from libcst.metadata import CodePosition, CodeRange


class _SourceOffsetCodegenState(CodegenState):
    """
    Align LibCST code-generation positions with the original source string.

    Generated positions can diverge from original-source offsets when LibCST
    omits source text such as an initial BOM, form-feed prefixes, or explicit
    line continuations. Token-by-token alignment preserves those characters as
    well as Unicode and mixed LF, CRLF, and CR line endings in the resulting
    source partition.
    """

    def __init__(self, module: Module, source: str, target_positions: Set[CodePosition]) -> None:
        super().__init__(default_indent=module.default_indent, default_newline=module.default_newline)
        self.source = source
        self.source_offset = int(source.startswith('\ufeff'))
        self.line = 1
        self.column = 0
        self.target_positions = target_positions
        self.right_position_offsets: Dict[CodePosition, int] = {}

    def _record_right_position(self, source_offset: int) -> None:
        position = CodePosition(self.line, self.column)
        if position in self.target_positions:
            self.right_position_offsets[position] = source_offset

    def _consume_source_token(self, value: str, search_forward: bool) -> Optional[int]:
        if self.source.startswith(value, self.source_offset):
            match_start = self.source_offset
        elif search_forward:
            match_start = self.source.find(value, self.source_offset)
        else:
            match_start = -1

        if match_start >= 0:
            self.source_offset = match_start + len(value)
            return match_start
        return None

    def _add_generated_token(self, value: str, search_forward: bool) -> None:
        source_start = self._consume_source_token(value, search_forward)
        aligned_source_offset = self.source_offset if source_start is None else source_start
        self._record_right_position(aligned_source_offset)

        cursor = 0
        while cursor < len(value):
            if value[cursor] == '\r' and cursor + 1 < len(value) and value[cursor + 1] == '\n':
                cursor += 2
                self.line += 1
                self.column = 0
            elif value[cursor] in {'\r', '\n'}:
                cursor += 1
                self.line += 1
                self.column = 0
            else:
                cursor += 1
                self.column += 1

            position_source_offset = self.source_offset if source_start is None else source_start + cursor
            self._record_right_position(position_source_offset)

    def add_indent_tokens(self) -> None:
        for token in self.indent_tokens:
            self._add_generated_token(token, search_forward=False)
        self.tokens.extend(self.indent_tokens)

    def add_token(self, value: str) -> None:
        self._add_generated_token(value, search_forward=True)
        self.tokens.append(value)


class SourceOffsetResolver:
    """
    Lazily map registered whitespace-inclusive ranges to source offsets.

    The first requested range triggers one shared code-generation pass for all
    positions registered at construction. Later ranges reuse the cached
    character offsets. Alignment reads the original source directly without
    copying it in full or splitting it into lines.
    """

    def __init__(self, module: Module, source: str, node_ranges: Iterable[CodeRange]) -> None:
        self.module = module
        self.source = source
        self.target_positions = {position for node_range in node_ranges for position in (node_range.start, node_range.end)}
        self._offsets: Dict[CodePosition, int] = {}

    def __call__(self, node_range: CodeRange) -> Tuple[int, int]:
        """Return character offsets for a range registered at construction."""
        if not self._offsets:
            state = _SourceOffsetCodegenState(self.module, self.source, self.target_positions)
            self.module._codegen(state)
            state._record_right_position(state.source_offset)
            self._offsets.update(state.right_position_offsets)
        return self._offsets[node_range.start], self._offsets[node_range.end]


def _scan_leading_trivia(text: str) -> Tuple[int, List[Tuple[str, str]]]:
    """Return the leading-trivia end index and comments with their indentation."""
    comments = []
    index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if character in ' \t\f\r\n' or (character == '\ufeff' and index == 0):
            index += 1
        elif character == '\\' and index + 1 < length and text[index + 1] in '\r\n':
            index += 1
            if text[index] == '\r' and index + 1 < length and text[index + 1] == '\n':
                index += 1
            index += 1
        elif character == '#':
            start = index
            while index < length and text[index] not in '\r\n':
                index += 1
            line_start = max(text.rfind('\n', 0, start), text.rfind('\r', 0, start)) + 1
            indent = text[line_start:start].replace('\ufeff', '').replace('\f', '')
            comments.append((indent, text[start:index]))
        else:
            return index, comments
    return index, comments


def _is_subsequence(candidate: str, source: str) -> bool:
    iterator = iter(source)
    return all(character in iterator for character in candidate)


def restore_codegen_prefix(source: str, generated: str) -> str:
    """Restore only leading source trivia that LibCST codegen omitted."""
    source_end, source_comments = _scan_leading_trivia(source)
    generated_end, generated_comments = _scan_leading_trivia(generated)
    if generated_comments != source_comments:
        return generated
    source_prefix = '' if source_end == 0 else source[:source_end]
    if not _is_subsequence(generated[:generated_end], source_prefix):
        return generated
    return source_prefix + generated[generated_end:]
