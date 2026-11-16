from unittest.mock import patch

import pytest
from libcst import (
    Add,
    Assign,
    BinaryOperation,
    EmptyLine,
    FunctionDef,
    Integer,
    Module,
    Name,
    Parameters,
    SimpleStatementLine,
    SimpleString,
    Subtract,
    parse_module,
)
from libcst.metadata import (
    CodePosition,
    CodeRange,
    MetadataWrapper,
    WhitespaceInclusivePositionProvider,
)

import cstvis.source_offsets as source_offsets_module
from cstvis import Changer, Context, Coordinate
from cstvis.dto import SourcePosition
from cstvis.source_offsets import SourceOffsetResolver


@pytest.mark.parametrize(
    ('source', 'position'),
    [
        pytest.param('', CodePosition(1, 0), id='empty-source'),
        pytest.param('x=1', CodePosition(2, 0), id='virtual-eof'),
        pytest.param('x=1\n', CodePosition(2, 0), id='physical-eof'),
        pytest.param('x=1\n\f', CodePosition(3, 0), id='form-feed-after-code'),
        pytest.param('\ufeff', CodePosition(1, 0), id='bom-only'),
        pytest.param('\ufeffx=1\n', CodePosition(2, 0), id='bom-and-code'),
    ],
)
def test_source_offset_resolver_returns_exact_eof_offsets(source, position):
    """
    EOF positions resolve exactly to `len(source)` for empty input, physical and
    virtual EOF positions, sources with an initial BOM omitted by LibCST codegen,
    and sources with trailing form feeds.
    """
    node_range = CodeRange(position, position)
    module = parse_module(source)
    resolver = SourceOffsetResolver(module, source, [node_range])

    assert resolver(node_range) == (len(source), len(source))


def test_source_offset_resolver_batches_unique_ranges_and_caches_codegen():
    """
    One lazy codegen pass resolves every unique registered endpoint and serves later ranges from cache.
    """
    source = 'a = 1 + 2\nb = 3 * 4\n'
    module = parse_module(source)
    add_range = CodeRange(CodePosition(1, 5), CodePosition(1, 8))
    multiply_range = CodeRange(CodePosition(2, 5), CodePosition(2, 8))
    registered_ranges = iter((add_range, add_range, multiply_range))

    with patch('cstvis.source_offsets._SourceOffsetCodegenState', wraps=source_offsets_module._SourceOffsetCodegenState) as create_state:
        resolver = SourceOffsetResolver(module, source, registered_ranges)

        assert resolver.target_positions == {add_range.start, add_range.end, multiply_range.start, multiply_range.end}
        assert create_state.call_count == 0
        assert resolver(multiply_range) == (15, 18)
        assert create_state.call_count == 1
        assert set(resolver._offsets) == resolver.target_positions
        assert resolver(add_range) == (5, 8)
        assert resolver(multiply_range) == (15, 18)
        assert create_state.call_count == 1


@pytest.mark.parametrize(
    ('unknown_range', 'missing_endpoint'),
    [
        pytest.param(
            CodeRange(CodePosition(1, 0), CodePosition(1, 4)),
            CodePosition(1, 0),
            id='unknown-start',
        ),
        pytest.param(
            CodeRange(CodePosition(1, 1), CodePosition(1, 5)),
            CodePosition(1, 5),
            id='unknown-end',
        ),
    ],
)
def test_source_offset_resolver_rejects_unknown_endpoint(unknown_range, missing_endpoint):
    """
    A range with either endpoint absent from the registered target positions is
    rejected on the first resolver call, even when its other endpoint is known.
    """
    source = '1 + 2'
    registered_range = CodeRange(CodePosition(1, 1), CodePosition(1, 4))
    resolver = SourceOffsetResolver(parse_module(source), source, [registered_range])

    assert resolver(registered_range) == (1, 4)

    fresh_resolver = SourceOffsetResolver(parse_module(source), source, [registered_range])
    with pytest.raises(KeyError) as error:
        fresh_resolver(unknown_range)

    assert error.value.args == (missing_endpoint,)
    assert fresh_resolver(registered_range) == (1, 4)

    with pytest.raises(KeyError):
        resolver(unknown_range)

    assert resolver(registered_range) == (1, 4)


@pytest.mark.parametrize(
    'source',
    [
        pytest.param(
            '@decorator\ndef function(value: int = 1):\n\ttext = f"{value}"\n\treturn (text, value + 1)\n',
            id='grammar-and-tab-indent',
        ),
        pytest.param(
            '\ufeffhead = "🙂e\u0301"\r\nvalue = 1 + 2\r',
            id='bom-unicode-and-mixed-newlines',
        ),
        pytest.param(
            'if True:\n    x=0\n\\\nresult    = 1 + 2\n',
            id='codegen-omitted-continuation',
        ),
    ],
)
def test_source_offset_resolver_preserves_global_range_invariants(source):
    """
    Every `WhitespaceInclusivePositionProvider` range stays within the source,
    and its endpoints map monotonically to offsets. Shared endpoints resolve
    consistently, and batched and reverse-order resolution return the same
    offsets; a resolver built for a single zero-width endpoint range returns that
    endpoint's offset.
    """
    wrapper = MetadataWrapper(parse_module(source))
    node_ranges = list(wrapper.resolve(WhitespaceInclusivePositionProvider).values())
    assert node_ranges
    forward_resolver = SourceOffsetResolver(wrapper.module, source, node_ranges)
    reverse_resolver = SourceOffsetResolver(wrapper.module, source, reversed(node_ranges))

    for node_range in reversed(node_ranges):
        reverse_resolver(node_range)

    position_offsets = {}
    for node_range in node_ranges:
        start_offset, end_offset = forward_resolver(node_range)
        assert 0 <= start_offset <= end_offset <= len(source)
        assert reverse_resolver(node_range) == (start_offset, end_offset)

        for position, offset in ((node_range.start, start_offset), (node_range.end, end_offset)):
            if position in position_offsets:
                assert position_offsets[position] == offset
            else:
                position_offsets[position] = offset
                zero_width_range = CodeRange(position, position)
                single_resolver = SourceOffsetResolver(parse_module(source), source, [zero_width_range])
                assert single_resolver(zero_width_range) == (offset, offset)

    ordered_offsets = [
        position_offsets[position]
        for position in sorted(position_offsets, key=lambda position: (position.line, position.column))
    ]
    assert ordered_offsets == sorted(ordered_offsets)
    assert ordered_offsets[-1] == len(source)
    assert len(set(ordered_offsets)) > 1


def test_code_fragments_cover_single_node_and_file_boundaries():
    """
    Nodes that cover the whole file leave both surrounding fragments empty; a
    node starting at the file start leaves `code_before` empty, and a node ending
    at the file end leaves `code_after` empty.
    """
    single_node_changer = Changer('1')
    single_node_contexts = []

    @single_node_changer.converter
    def convert_single_node(node: Integer) -> Integer:
        return node

    @single_node_changer.filter
    def capture_single_node(node: Integer, context: Context) -> bool:  # noqa: ARG001
        single_node_contexts.append(context)
        return True

    assert len(list(single_node_changer.iterate_coordinates())) == 1
    assert len(single_node_contexts) == 1
    single_node_context = single_node_contexts[0]
    assert single_node_context.position.code_before == ''
    assert single_node_context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(1, 1))
    assert single_node_context.position.code_after == ''
    assert single_node_context.position.code_before + '1' + single_node_context.position.code_after == single_node_context.position.source

    boundary_changer = Changer('x = 1')
    first_node_contexts = []
    last_node_contexts = []

    @boundary_changer.converter
    def convert_first_node(node: Name) -> Name:
        return node

    @boundary_changer.converter
    def convert_last_node(node: Integer) -> Integer:
        return node

    @boundary_changer.filter
    def capture_first_node(node: Name, context: Context) -> bool:  # noqa: ARG001
        first_node_contexts.append(context)
        return True

    @boundary_changer.filter
    def capture_last_node(node: Integer, context: Context) -> bool:  # noqa: ARG001
        last_node_contexts.append(context)
        return True

    assert len(list(boundary_changer.iterate_coordinates())) == 2
    assert len(first_node_contexts) == 1
    assert len(last_node_contexts) == 1
    first_node_context = first_node_contexts[0]
    assert first_node_context.position.code_before == ''
    assert first_node_context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(1, 1))
    assert first_node_context.position.code_after == ' = 1'
    assert first_node_context.position.code_before + 'x' + first_node_context.position.code_after == first_node_context.position.source

    last_node_context = last_node_contexts[0]
    assert last_node_context.position.code_before == 'x = '
    assert last_node_context.position.node_range == CodeRange(CodePosition(1, 4), CodePosition(1, 5))
    assert last_node_context.position.code_after == ''
    assert last_node_context.position.code_before + '1' + last_node_context.position.code_after == last_node_context.position.source


def test_code_fragments_partition_zero_width_parameters():
    """
    A zero-width `Parameters` node splits the non-empty source at its own
    position, leaving the text immediately before and after it in `code_before`
    and `code_after`.
    """
    source = 'def f():\n    pass\n'
    changer = Changer(source)
    calls = []
    contexts = []

    @changer.converter
    def convert(node: Parameters) -> Parameters:
        calls.append(node)
        return node

    @changer.filter
    def capture(node: Parameters, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert calls == []
    assert changer.apply_coordinate(coordinates[0]) == source
    assert len(calls) == 1
    assert isinstance(calls[0], Parameters)
    assert len(contexts) == 1
    context = contexts[0]
    expected_node_source_span = ''
    assert context.position.node_range == CodeRange(CodePosition(1, 6), CodePosition(1, 6))
    assert context.position.start_offset == context.position.end_offset == 6
    assert context.position.code_before == 'def f('
    assert context.position.code_after == '):\n    pass\n'
    assert context.position.code_before + expected_node_source_span + context.position.code_after == context.position.source


def test_code_fragments_handle_later_statement_without_final_newline():
    """
    At virtual EOF, `SourcePosition` places the preceding CRLF in `code_before`
    and leaves `code_after` empty. The physical statement text (`'x = 1'`) has no
    trailing newline, although its whitespace-inclusive range ends at
    `CodePosition(3, 0)`.
    """
    source = 'head = 0\r\nx = 1'
    changer = Changer(source)
    calls = []
    contexts = []

    @changer.converter
    def convert(node: SimpleStatementLine) -> SimpleStatementLine:
        calls.append(node)
        assignment = node.body[0]
        assert isinstance(assignment, Assign)
        return node.with_changes(body=[assignment.with_changes(value=Integer('2'))])

    @changer.filter
    def capture(node: SimpleStatementLine, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 2
    assert calls == []
    assert changer.apply_coordinate(coordinates[1]) == 'head = 0\r\nx = 2'
    assert len(calls) == 1
    assert len(contexts) == 2
    context = contexts[1]
    assert context.position.node_range == CodeRange(CodePosition(2, 0), CodePosition(3, 0))
    assert context.position.code_before == 'head = 0\r\n'
    assert context.position.code_after == ''
    assert context.position.code_before + 'x = 1' + context.position.code_after == context.position.source


def test_code_fragments_preserve_semicolon_owned_trivia():
    """
    The first Assign's span includes its trailing semicolon and space, so
    `code_after` starts with the second statement.
    """
    source = 'x=1; y=2\n'
    changer = Changer(source)
    calls = []
    contexts = []

    @changer.converter
    def convert(node: Assign) -> Assign:
        calls.append(node)
        return node.with_changes(targets=[node.targets[0].with_changes(target=Name('z'))])

    @changer.filter
    def capture(node: Assign, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 2
    assert calls == []
    assert changer.apply_coordinate(coordinates[0]) == 'z=1; y=2\n'
    assert len(calls) == 1
    assert len(contexts) == 2
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(1, 5))
    assert context.position.code_before == ''
    assert context.position.code_after == 'y=2\n'
    assert context.position.code_before + 'x=1; ' + context.position.code_after == context.position.source


def test_code_fragments_preserve_decorators_and_surrounding_comments():
    """
    The FunctionDef span includes decorators, an indented body, and newlines but
    excludes surrounding comments.
    """
    source = '# h\n@dec\ndef f(x: int = 1):\n    return x\n# f\n'
    changer = Changer(source)
    calls = []
    contexts = []

    @changer.converter
    def convert(node: FunctionDef) -> FunctionDef:
        calls.append(node)
        return node.with_changes(name=Name('g'))

    @changer.filter
    def capture(node: FunctionDef, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert calls == []
    assert changer.apply_coordinate(coordinates[0]) == '# h\n@dec\ndef g(x: int = 1):\n    return x\n# f\n'
    assert len(calls) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.coordinate == Coordinate(None, 'FunctionDef', 3, 0, 4, 12)
    assert context.position.node_range == CodeRange(CodePosition(2, 0), CodePosition(5, 0))
    assert context.position.code_before == '# h\n'
    assert context.position.code_after == '# f\n'
    assert context.position.code_before + '@dec\ndef f(x: int = 1):\n    return x\n' + context.position.code_after == context.position.source


def test_code_fragments_preserve_nested_indentation_and_comments():
    """
    A nested statement's whitespace-inclusive span includes its ambient
    indentation and leading comment.

    `code_before` and `code_after` contain only the outer header and footer,
    while the leading and inline comments and the multiline assignment remain
    inside the span.
    """
    source = '# header\nif True:\n    # lead\n    value = (\n        1 + 2  # inner\n    )\n# footer\n'
    changer = Changer(source)
    calls = []
    contexts = []

    @changer.converter
    def convert(node: SimpleStatementLine) -> SimpleStatementLine:
        calls.append(node)
        assignment = node.body[0]
        assert isinstance(assignment, Assign)
        return node.with_changes(
            body=[assignment.with_changes(targets=[assignment.targets[0].with_changes(target=Name('changed'))])],
        )

    @changer.filter
    def capture(node: SimpleStatementLine, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert calls == []
    assert changer.apply_coordinate(coordinates[0]) == '# header\nif True:\n    # lead\n    changed = (\n        1 + 2  # inner\n    )\n# footer\n'
    assert len(calls) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.coordinate == Coordinate(None, 'SimpleStatementLine', 4, 4, 6, 5)
    assert context.position.node_range == CodeRange(CodePosition(3, 0), CodePosition(7, 0))
    assert context.position.code_before == '# header\nif True:\n'
    assert context.position.code_after == '# footer\n'
    assert context.position.code_before + '    # lead\n    value = (\n        1 + 2  # inner\n    )\n' + context.position.code_after == context.position.source


def test_codegen_indent_does_not_search_forward_in_source():
    """
    After an omitted line continuation, the `result` name is mapped to its own
    occurrence: `code_before` includes the continuation line, and the four spaces
    after the name stay in `code_after` instead of being treated as a later
    indentation match.
    """
    source = 'if True:\n    x=0\n\\\nresult    = 1 + 2\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Name) -> Name:
        return node

    @changer.filter
    def capture(node: Name, context: Context) -> bool:
        if node.value != 'result':
            return False
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(3, 4), CodePosition(3, 10))
    assert context.position.code_before == 'if True:\n    x=0\n\\\n'
    assert context.position.code_after == '    = 1 + 2\n'
    assert context.position.code_before + 'result' + context.position.code_after == context.position.source


@pytest.mark.parametrize(
    ('indent', 'expected_range'),
    [
        pytest.param('\t', CodeRange(CodePosition(2, 11), CodePosition(2, 14)), id='tab'),
        pytest.param('  ', CodeRange(CodePosition(2, 12), CodePosition(2, 15)), id='two-spaces'),
    ],
)
def test_code_fragments_follow_module_default_indent(indent, expected_range):
    """
    Nested Add fragments use LibCST's inferred tab or two-space default indent instead of four hard-coded spaces.
    """
    source = f'if True:\n{indent}result = 1 + 2\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add) -> Add:
        return node

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == expected_range
    assert context.position.code_before == f'if True:\n{indent}result = 1'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + ' + ' + context.position.code_after == context.position.source


@pytest.mark.parametrize(
    'newline',
    [
        pytest.param('\r\n', id='crlf'),
        pytest.param('\r', id='bare-cr'),
    ],
)
def test_code_fragments_follow_module_default_newline_at_node_boundary(newline):
    """
    An Assign ending immediately before CRLF or bare CR leaves the complete inferred newline in code_after.
    """
    source = f'head=0{newline}x=1'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Assign) -> Assign:
        return node

    @changer.filter
    def capture(node: Assign, context: Context) -> bool:  # noqa: ARG001
        if context.position.coordinate.start_line != 1:
            return False
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(1, 6))
    assert context.position.code_before == ''
    assert context.position.code_after == f'{newline}x=1'
    assert context.position.code_before + 'head=0' + context.position.code_after == context.position.source


def test_code_fragments_preserve_multiline_parenthesized_expression():
    """
    A multiline BinaryOperation span includes its parentheses, continuation indentation, and inline comment.
    """
    source = '# header\nif True:\n    value = (\n        1 + 2  # inner\n    )\n# footer\n'
    changer = Changer(source)
    contexts = []
    calls = []

    @changer.converter
    def convert(node: BinaryOperation) -> BinaryOperation:
        calls.append(node)
        assert isinstance(node.operator, Add)
        return node.with_changes(
            operator=Subtract(
                whitespace_before=node.operator.whitespace_before,
                whitespace_after=node.operator.whitespace_after,
            ),
        )

    @changer.filter
    def capture(node: BinaryOperation, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert calls == []
    assert changer.apply_coordinate(coordinates[0]) == '# header\nif True:\n    value = (\n        1 - 2  # inner\n    )\n# footer\n'
    assert len(calls) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(3, 12), CodePosition(5, 5))
    assert context.position.code_before == '# header\nif True:\n    value = '
    assert context.position.code_after == '\n# footer\n'
    assert context.position.code_before + '(\n        1 + 2  # inner\n    )' + context.position.code_after == context.position.source


def test_code_fragments_select_correct_repeated_occurrence():
    """
    Distinct ranges partition identical Add occurrences instead of using the first textual match.
    """
    source = 'foo = foo + foo\nfoo = foo + foo\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add) -> Subtract:
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 2
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == [
        'foo = foo - foo\nfoo = foo + foo\n',
        'foo = foo + foo\nfoo = foo - foo\n',
    ]
    first_context, second_context = contexts
    assert first_context.position.node_range == CodeRange(CodePosition(1, 9), CodePosition(1, 12))
    assert first_context.position.code_before == 'foo = foo'
    assert first_context.position.code_after == 'foo\nfoo = foo + foo\n'
    assert first_context.position.code_before + ' + ' + first_context.position.code_after == first_context.position.source
    assert second_context.position.node_range == CodeRange(CodePosition(2, 9), CodePosition(2, 12))
    assert second_context.position.code_before == 'foo = foo + foo\nfoo = foo'
    assert second_context.position.code_after == 'foo\n'
    assert second_context.position.code_before + ' + ' + second_context.position.code_after == second_context.position.source


def test_code_fragments_map_add_after_repeated_identifier_with_omitted_prefix():
    """
    The `Add` in `result = result + 1` is mapped after the repeated identifier;
    the codegen-omitted form feed and the retained leading comment stay in
    `code_before`, and the fragments reconstruct the source.
    """
    source = '# result\n\fresult = result + 1\n'
    changer = Changer(source)
    calls = []
    contexts = []

    @changer.converter
    def convert(node: Add) -> Subtract:
        calls.append(node)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert calls == []
    assert changer.apply_coordinate(coordinates[0]) == '# result\n\fresult = result - 1\n'
    assert len(calls) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(2, 15), CodePosition(2, 18))
    assert context.position.start_offset == 25
    assert context.position.end_offset == 28
    assert context.position.code_before == '# result\n\fresult = result'
    assert context.position.code_after == '1\n'
    assert context.position.code_before + ' + ' + context.position.code_after == context.position.source


def test_code_fragments_map_later_node_across_mixed_newlines():
    """
    A third-line Add maps across preceding CRLF and bare CR while preserving the following LF.
    """
    source = 'first=0\r\nsecond=1\rthird = 2  +\t3\nlast=4'
    changer = Changer(source)
    calls = []
    contexts = []

    @changer.converter
    def convert(node: Add) -> Subtract:
        calls.append(node)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert calls == []
    assert changer.apply_coordinate(coordinates[0]) == 'first=0\r\nsecond=1\rthird = 2  -\t3\nlast=4'
    assert len(calls) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(3, 9), CodePosition(3, 13))
    assert context.position.code_before == 'first=0\r\nsecond=1\rthird = 2'
    assert context.position.code_after == '3\nlast=4'
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


@pytest.mark.parametrize(
    ('source', 'expected_range', 'expected_before', 'expected_after', 'expected_source'),
    [
        pytest.param(
            'header = "🙂e\u0301"\nvalue = π  +\t2\n',
            CodeRange(CodePosition(2, 9), CodePosition(2, 13)),
            'header = "🙂e\u0301"\nvalue = π',
            '2\n',
            'header = "🙂e\u0301"\nvalue = π  -\t2\n',
            id='next-line',
        ),
        pytest.param(
            'header = "🙂e\u0301"; value = π  +\t2\n',
            CodeRange(CodePosition(1, 25), CodePosition(1, 29)),
            'header = "🙂e\u0301"; value = π',
            '2\n',
            'header = "🙂e\u0301"; value = π  -\t2\n',
            id='same-line',
        ),
    ],
)
def test_code_fragments_count_unicode_as_python_characters(
    source, expected_range, expected_before, expected_after, expected_source,
):
    """
    Non-BMP and combining characters count as Python characters in both LibCST
    columns and source offsets, on the Add's line and on a preceding line.
    """
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add) -> Subtract:
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == expected_source
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == expected_range
    assert context.position.code_before == expected_before
    assert context.position.code_after == expected_after
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


def test_code_fragments_preserve_bom_before_later_node():
    """
    Absolute offsets include the initial BOM and the non-BMP and combining
    characters on the first line before the second-line `Add`.

    The BOM stays in `code_before`: it contributes to absolute source offsets but
    does not change the `Add` node's LibCST range.
    """
    source = '\ufeffheader = "🙂e\u0301"\nvalue = 1  +\t2\ntail = 3\n'
    changer = Changer(source)
    calls = []
    contexts = []

    @changer.converter
    def convert(node: Add) -> Subtract:
        calls.append(node)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert calls == []
    assert changer.apply_coordinate(coordinates[0]) == '\ufeffheader = "🙂e\u0301"\nvalue = 1  -\t2\ntail = 3\n'
    assert len(calls) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(2, 9), CodePosition(2, 13))
    assert context.position.start_offset == 25
    assert context.position.end_offset == 29
    assert context.position.code_before == '\ufeffheader = "🙂e\u0301"\nvalue = 1'
    assert context.position.code_after == '2\ntail = 3\n'
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


def test_internal_bom_does_not_shift_initial_source_offset():
    """
    A BOM inside a string does not trigger the one-character offset reserved for an initial BOM.
    """
    source = 'prefix = "\ufeff"\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Name) -> Name:
        return node

    @changer.filter
    def capture(node: Name, context: Context) -> bool:
        if node.value != 'prefix':
            return False
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(1, 6))
    assert context.position.code_before == ''
    assert context.position.code_after == ' = "\ufeff"\n'
    assert context.position.code_before + 'prefix' + context.position.code_after == context.position.source


@pytest.mark.parametrize(
    ('source', 'replacement', 'expected_sources'),
    [
        pytest.param(
            '# header\nx = 9 + 1\n',
            '10',
            ['# header\nx = 10 + 1\n', '# header\nx = 9 + 10\n'],
            id='growing-comment-prefix',
        ),
        pytest.param(
            '\ufeffx = 9 + 1\n',
            '10',
            ['\ufeffx = 10 + 1\n', '\ufeffx = 9 + 10\n'],
            id='growing-bom',
        ),
        pytest.param(
            '# header\nx = 100 + 200\n',
            '1',
            ['# header\nx = 1 + 200\n', '# header\nx = 100 + 1\n'],
            id='shrinking-comment-prefix',
        ),
        pytest.param(
            '\ufeffx = 100 + 200\n',
            '1',
            ['\ufeffx = 1 + 200\n', '\ufeffx = 100 + 1\n'],
            id='shrinking-bom',
        ),
        pytest.param(
            '\fresult = 9 + 1\n',
            '10',
            ['\fresult = 10 + 1\n', '\fresult = 9 + 10\n'],
            id='growing-form-feed',
        ),
        pytest.param(
            '\fresult = 100 + 200\n',
            '1',
            ['\fresult = 1 + 200\n', '\fresult = 100 + 1\n'],
            id='shrinking-form-feed',
        ),
        pytest.param(
            '\\\nresult = 9 + 1\n',
            '10',
            ['\\\nresult = 10 + 1\n', '\\\nresult = 9 + 10\n'],
            id='growing-line-continuation',
        ),
        pytest.param(
            '\\\nresult = 100 + 200\n',
            '1',
            ['\\\nresult = 1 + 200\n', '\\\nresult = 100 + 1\n'],
            id='shrinking-line-continuation',
        ),
        pytest.param(
            'if True:\n\tresult = 9 + 1\n',
            '10',
            ['if True:\n\tresult = 10 + 1\n', 'if True:\n\tresult = 9 + 10\n'],
            id='tab-indent',
        ),
        pytest.param(
            'if True:\n  result = 9 + 1\n',
            '10',
            ['if True:\n  result = 10 + 1\n', 'if True:\n  result = 9 + 10\n'],
            id='two-space-indent',
        ),
    ],
)
def test_apply_coordinate_restores_prefix_across_replacement_lengths(source, replacement, expected_sources):
    """Longer and shorter replacements preserve a leading comment, BOM, or tab/two-space indentation and restore an omitted form-feed or line-continuation prefix."""
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Integer, context: Context):
        contexts.append(context)
        return node.with_changes(value=replacement)

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 2
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == expected_sources
    assert len(contexts) == 2
    for context in contexts:
        position = context.position
        assert position.source == source
        assert position.coordinate.class_name == 'Integer'
        assert position.code_before + source[position.start_offset:position.end_offset] + position.code_after == source


@pytest.mark.parametrize(
    ('source', 'expected_end_position'),
    [
        pytest.param('', CodePosition(1, 0), id='empty-source'),
        pytest.param('x=1\n', CodePosition(2, 0), id='ordinary-source'),
    ],
)
def test_module_span_covers_empty_and_nonempty_sources_completely(source, expected_end_position):
    """
    The Module span covers the entire source for both empty and non-empty inputs;
    empty input has a zero-width range, and neither case has surrounding
    fragments.
    """
    changer = Changer(source)
    contexts = []
    calls = []

    @changer.converter
    def convert(node: Module, context: Context) -> Module:
        calls.append(node)
        contexts.append(context)
        return node

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    coordinate = coordinates[0]
    assert calls == []
    assert changer.apply_coordinate(coordinate) == source
    assert len(calls) == 1
    assert isinstance(calls[0], Module)
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.start_offset == 0
    assert context.position.end_offset == len(source)
    assert context.position.node_range == CodeRange(CodePosition(1, 0), expected_end_position)
    assert context.position.code_before == ''
    assert context.position.code_after == ''
    assert context.position.code_before + source + context.position.code_after == context.position.source


def test_module_range_leaves_bom_in_code_before():
    """
    LibCST excludes an initial U+FEFF BOM from Module's range; SourcePosition keeps it in code_before.
    """
    source = '\ufeffx=1\n'
    changer = Changer(source)
    contexts = []
    calls = []

    @changer.converter
    def convert(node: Module, context: Context) -> Module:
        calls.append(node)
        contexts.append(context)
        return node

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    coordinate = coordinates[0]
    assert calls == []
    assert changer.apply_coordinate(coordinate) == source
    assert len(calls) == 1
    assert isinstance(calls[0], Module)
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.start_offset == 1
    assert context.position.end_offset == len(source)
    assert context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(2, 0))
    assert context.position.code_before == '\ufeff'
    assert context.position.code_after == ''
    assert context.position.code_before + 'x=1\n' + context.position.code_after == context.position.source


@pytest.mark.parametrize(
    ('source', 'expected_before', 'expected_module_span', 'expected_start_offset', 'expected_end_offset'),
    [
        pytest.param('\f', '', '\f', 0, 1, id='form-feed-only'),
        pytest.param(' \f', '', ' \f', 0, 2, id='space-and-form-feed'),
        pytest.param('\ufeff\f', '\ufeff', '\f', 1, 2, id='bom-and-form-feed'),
    ],
)
def test_module_fragments_keep_eof_form_feed_in_module_span(
    source, expected_before, expected_module_span, expected_start_offset, expected_end_offset,
):
    """
    An EOF form feed remains in Module's span for whitespace-only files. An
    initial BOM, when present, stays in `code_before` and is not part of the
    span.
    """
    changer = Changer(source)
    contexts = []
    calls = []

    @changer.converter
    def convert(node: Module, context: Context) -> Module:
        calls.append(node)
        contexts.append(context)
        return node

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    coordinate = coordinates[0]
    assert calls == []
    assert changer.apply_coordinate(coordinate) == source
    assert len(calls) == 1
    assert isinstance(calls[0], Module)
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.start_offset == expected_start_offset
    assert context.position.end_offset == expected_end_offset
    assert context.position.code_before == expected_before
    assert context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(2, 0))
    assert context.position.code_after == ''
    assert context.position.code_before + expected_module_span + context.position.code_after == context.position.source


@pytest.mark.parametrize(
    ('prefix', 'expected_libcst_line'),
    [
        pytest.param('\f', 1, id='form-feed'),
        pytest.param('\t\f', 1, id='tab-and-form-feed'),
        pytest.param(' \f', 1, id='space-and-form-feed'),
        pytest.param('\ufeff\f', 1, id='bom-and-form-feed'),
        pytest.param('\\\n', 1, id='lf-continuation'),
        pytest.param('\\\r', 1, id='cr-continuation'),
        pytest.param('\\\r\n', 1, id='crlf-continuation'),
        pytest.param('\f\\\n', 1, id='form-feed-and-continuation'),
        pytest.param('\ufeff\\\n', 1, id='bom-and-continuation'),
        pytest.param('\\\n\t\f', 1, id='continued-tab-and-form-feed'),
        pytest.param('\n\f', 2, id='blank-line-before-form-feed'),
        pytest.param('# lead\n \f', 2, id='comment-before-form-feed'),
        pytest.param('\n\\\n', 2, id='blank-line-before-continuation'),
        pytest.param('# lead\r\n\\\r\n', 2, id='crlf-comment-before-continuation'),
    ],
)
def test_code_fragments_preserve_codegen_omitted_prefix(prefix, expected_libcst_line):
    """Codegen-omitted form feeds and line continuations stay in `code_before` and do not advance LibCST's line counter; a real blank or comment line in the prefix does."""
    source = f'{prefix}result = 1  + 2\n'
    changer = Changer(source)
    filter_contexts = []
    converter_contexts = []
    converter_calls = []

    @changer.converter
    def convert(node: Add, context: Context) -> Subtract:
        converter_contexts.append(context)
        converter_calls.append(node)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        filter_contexts.append(context)
        return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert converter_calls == []
    assert changer.apply_coordinate(coordinates[0]) == f'{prefix}result = 1  - 2\n'
    assert len(converter_calls) == 1
    assert isinstance(converter_calls[0], Add)
    assert len(filter_contexts) == 1
    context = filter_contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(expected_libcst_line, 10), CodePosition(expected_libcst_line, 14))
    assert context.position.code_before == f'{prefix}result = 1'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + '  + ' + context.position.code_after == context.position.source
    assert len(converter_contexts) == 1
    converter_position = converter_contexts[0].position
    assert converter_position.node_range == context.position.node_range
    assert converter_position.code_before == context.position.code_before
    assert converter_position.code_after == context.position.code_after


def test_code_fragments_preserve_nested_form_feed_indentation():
    """
    A form feed in suite indentation affects LibCST columns without misaligning nested fragments.
    """
    source = 'if True:\n\f    result = 1  + 2\n'
    changer = Changer(source)
    contexts = []
    calls = []

    @changer.converter
    def convert(node: Add) -> Subtract:
        calls.append(node)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert calls == []
    assert changer.apply_coordinate(coordinates[0]) == 'if True:\n\f    result = 1  - 2\n'
    assert len(calls) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(2, 15), CodePosition(2, 19))
    assert context.position.code_before == 'if True:\n\f    result = 1'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + '  + ' + context.position.code_after == context.position.source


@pytest.mark.parametrize(
    ('source', 'expected_range', 'expected_before', 'expected_after', 'expected_source'),
    [
        pytest.param(
            'value = (\n\f1  +\t2\n)\n',
            CodeRange(CodePosition(2, 2), CodePosition(2, 6)),
            'value = (\n\f1',
            '2\n)\n',
            'value = (\n\f1  -\t2\n)\n',
            id='form-feed-in-parenthesized-expression',
        ),
        pytest.param(
            'value=(\n\\\n1  +\t2\n)\n',
            CodeRange(CodePosition(3, 1), CodePosition(3, 5)),
            'value=(\n\\\n1',
            '2\n)\n',
            'value=(\n\\\n1  -\t2\n)\n',
            id='continuation-in-parenthesized-expression',
        ),
        pytest.param(
            's = f"""\n\f{1  +\t2}\n"""\n',
            CodeRange(CodePosition(2, 3), CodePosition(2, 7)),
            's = f"""\n\f{1',
            '2}\n"""\n',
            's = f"""\n\f{1  -\t2}\n"""\n',
            id='form-feed-in-fstring',
        ),
        pytest.param(
            's = """\n\\\ntext\n"""\nresult=π  +\t2\n',
            CodeRange(CodePosition(5, 8), CodePosition(5, 12)),
            's = """\n\\\ntext\n"""\nresult=π',
            '2\n',
            's = """\n\\\ntext\n"""\nresult=π  -\t2\n',
            id='continuation-in-preceding-triple-string',
        ),
    ],
)
def test_code_fragments_preserve_alignment_across_parser_contexts(
    source, expected_range, expected_before, expected_after, expected_source,
):
    """Fragments align around an `Add` for an omitted form feed or continuation inside parentheses, a form feed inside an f-string, and a continuation inside a preceding triple-quoted string. Applying the coordinate rewrites only the `Add`, leaving the surrounding text intact."""
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add) -> Subtract:
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == expected_source
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == expected_range
    assert context.position.code_before == expected_before
    assert context.position.code_after == expected_after
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


def test_code_fragments_keep_continuation_after_indented_suite():
    """A line continuation after an indented suite stays in the preceding fragment; the `Add` range points at the continued line."""
    source = 'if True:\n    x = 0\n\\\nresult = 1  +\t2\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add) -> Add:
        return node

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(3, 14), CodePosition(3, 18))
    assert context.position.code_before == 'if True:\n    x = 0\n\\\nresult = 1'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


@pytest.mark.xfail(
    reason='LibCST codegen reindents a suite-level continuation',
    strict=True,
    raises=AssertionError,
)
def test_apply_coordinate_continuation_reindent_limitation_after_indented_suite():
    """A change to the continued statement stays out of the preceding suite; this documents the current LibCST codegen limitation."""
    source = 'if True:\n    x = 0\n\\\nresult = 1  +\t2\n'
    changer = Changer(source)

    @changer.converter
    def convert(node: Add) -> Subtract:
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    coordinate = next(changer.iterate_coordinates())

    assert changer.apply_coordinate(coordinate) == 'if True:\n    x = 0\n\\\nresult = 1  -\t2\n'


def test_code_fragments_align_nested_string_matching_enclosing_fstring_quotes():
    """
    A nested SimpleString that reuses the enclosing f-string's triple quotes has
    a span that includes the surrounding parentheses but not the closing brace.
    """
    source = 'value = f"""{("""inner\n\fbody""")}\ntail"""\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: SimpleString) -> SimpleString:
        return node

    @changer.filter
    def capture(node: SimpleString, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 13), CodePosition(2, 9))
    assert context.position.code_before == 'value = f"""{'
    assert context.position.code_after == '}\ntail"""\n'
    assert context.position.code_before + '("""inner\n\fbody""")' + context.position.code_after == context.position.source


def test_pipeline_and_direct_source_positions_partition_form_feed_identically():
    """A directly constructed `SourcePosition` matches the pipeline position: the first statement's span absorbs the form feed, while the later statement keeps it in `code_before`."""
    source = 'x=1\n\fresult=2\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: SimpleStatementLine) -> SimpleStatementLine:
        return node

    @changer.filter
    def capture(node: SimpleStatementLine, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 2
    first_context, second_context = contexts
    assert first_context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(2, 0))
    assert first_context.position.code_before == ''
    assert first_context.position.code_after == 'result=2\n'
    assert first_context.position.code_before + 'x=1\n\f' + first_context.position.code_after == first_context.position.source
    direct_resolver = SourceOffsetResolver(
        parse_module(source),
        source,
        [first_context.position.node_range],
    )
    direct_position = SourcePosition(
        Coordinate(None, 'SimpleStatementLine', 1, 0, 1, 3),
        source,
        CodeRange(CodePosition(1, 0), CodePosition(2, 0)),
        direct_resolver,
    )
    assert direct_position == first_context.position
    assert direct_position.start_offset == 0
    assert direct_position.end_offset == 5
    assert direct_position.code_before == first_context.position.code_before
    assert direct_position.code_after == first_context.position.code_after
    assert second_context.position.node_range == CodeRange(CodePosition(2, 0), CodePosition(3, 0))
    assert second_context.position.code_before == 'x=1\n\f'
    assert second_context.position.code_after == ''
    assert second_context.position.code_before + 'result=2\n' + second_context.position.code_after == second_context.position.source
    direct_second_resolver = SourceOffsetResolver(
        parse_module(source),
        source,
        [second_context.position.node_range],
    )
    direct_second_position = SourcePosition(
        Coordinate(None, 'SimpleStatementLine', 2, 0, 2, 8),
        source,
        CodeRange(CodePosition(2, 0), CodePosition(3, 0)),
        direct_second_resolver,
    )
    assert direct_second_position == second_context.position
    assert direct_second_position.start_offset == 5
    assert direct_second_position.end_offset == 14
    assert direct_second_position.code_before == second_context.position.code_before
    assert direct_second_position.code_after == second_context.position.code_after


@pytest.mark.parametrize(
    'source',
    ['# comment', '# comment\n', '# comment\r', '# comment\r\n'],
    ids=['no-newline', 'lf', 'cr', 'crlf'],
)
def test_apply_coordinate_preserves_comment_only_source(source):
    """
    Identity conversion preserves a comment-only source with or without a
    trailing newline.
    """
    changer = Changer(source)
    calls = []

    @changer.converter
    def convert(node: Module) -> Module:
        calls.append(node)
        return node

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    coordinate = coordinates[0]

    assert calls == []
    assert changer.apply_coordinate(coordinate) == source
    assert len(calls) == 1
    assert isinstance(calls[0], Module)


@pytest.mark.parametrize(
    ('source', 'expected_source'),
    [
        pytest.param('\fresult = 1  + 2\n', '\fresult = 1  - 2\n', id='form-feed'),
        pytest.param('\\\nresult = 1  + 2\n', '\\\nresult = 1  - 2\n', id='line-continuation'),
        pytest.param('\ufeffresult = 1  + 2\n', '\ufeffresult = 1  - 2\n', id='bom'),
        pytest.param('\\\r\nresult = 1  + 2\n', '\\\r\nresult = 1  - 2\n', id='crlf-line-continuation'),
        pytest.param('# header\nresult = 1  + 2\n', '# header\nresult = 1  - 2\n', id='comment-prefix'),
        pytest.param(
            '# lead\rresult = 1  + 2\n',
            '# lead\rresult = 1  - 2\n',
            id='bare-cr-comment-prefix',
        ),
        pytest.param(
            '# first\n# second\nresult = 1  + 2\n',
            '# first\n# second\nresult = 1  - 2\n',
            id='multiple-comments',
        ),
        pytest.param(
            'result = 1  + 2  # tail',
            'result = 1  - 2  # tail',
            id='trailing-comment-without-final-newline',
        ),
        pytest.param(
            '# first\n# second\nresult = 1  + 2  # tail',
            '# first\n# second\nresult = 1  - 2  # tail',
            id='multiple-comments-and-trailing-comment',
        ),
        pytest.param('\ufeff# header\nresult = 1  + 2\n', '\ufeff# header\nresult = 1  - 2\n', id='bom-and-comment'),
        pytest.param(
            'first=0\r\nsecond=1\rthird = 2  +\t3\nlast=4',
            'first=0\r\nsecond=1\rthird = 2  -\t3\nlast=4',
            id='mixed-newlines',
        ),
        pytest.param('x = 1 + 2', 'x = 1 - 2', id='virtual-eof'),
    ],
)
def test_apply_coordinate_preserves_source_formatting_after_conversion(source, expected_source):
    """
    A real conversion preserves leading omitted prefixes, comments, BOM, mixed
    newlines, and a missing final newline while rewriting only the selected Add.
    """
    changer = Changer(source)

    @changer.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == expected_source

def test_apply_coordinate_preserves_added_leading_blank_line_without_duplicating_comment():
    """Adding a leading blank line through Module.header is not overwritten by prefix restoration."""
    source = '# header\nx = 1 + 2\n'
    changer = Changer(source)

    @changer.converter
    def convert(node: Module) -> Module:
        return node.with_changes(header=[EmptyLine(), *node.header])

    coordinate = next(changer.iterate_coordinates())
    assert changer.apply_coordinate(coordinate) == '\n# header\nx = 1 + 2\n'


def test_apply_coordinate_preserves_changed_leading_comment_indentation():
    """Changing a leading comment's indentation is not undone or duplicated by prefix restoration."""
    source = '# a\nx = 1 + 2\n'
    changer = Changer(source)

    @changer.converter
    def convert(node: EmptyLine) -> EmptyLine:
        return node.with_changes(whitespace=node.whitespace.with_changes(value='  '))

    coordinate = next(changer.iterate_coordinates())
    assert changer.apply_coordinate(coordinate) == '  # a\nx = 1 + 2\n'

