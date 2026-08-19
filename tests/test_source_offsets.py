from unittest.mock import patch

import pytest
from libcst import (
    Add,
    Assign,
    BinaryOperation,
    FunctionDef,
    Integer,
    Module,
    Name,
    Parameters,
    SimpleStatementLine,
    SimpleString,
    parse_module,
)
from libcst.metadata import (
    CodePosition,
    CodeRange,
    MetadataWrapper,
    WhitespaceInclusivePositionProvider,
)

import cstvis.source_offsets as source_offsets_module
from cstvis import Changer, Context
from cstvis.dto import SourcePosition
from cstvis.source_offsets import SourceOffsetResolver


@pytest.mark.parametrize(
    ('source', 'position', 'expected_offset'),
    [
        pytest.param('', CodePosition(1, 0), 0, id='empty-source'),
        pytest.param('x=1', CodePosition(2, 0), 3, id='virtual-eof'),
        pytest.param('x=1\n', CodePosition(2, 0), 4, id='physical-eof'),
        pytest.param('x=1\n\f', CodePosition(3, 0), 5, id='form-feed-after-code'),
        pytest.param('\ufeff', CodePosition(1, 0), 1, id='bom-only'),
        pytest.param('\ufeffx=1\n', CodePosition(2, 0), 5, id='bom-and-code'),
    ],
)
def test_source_offset_resolver_returns_exact_eof_offsets(source, position, expected_offset):
    """
    EOF positions resolve exactly to len(source), including virtual newlines and an omitted initial BOM.
    """
    node_range = CodeRange(position, position)
    module = parse_module(source)
    resolver = SourceOffsetResolver(module, source, [node_range])

    assert expected_offset == len(source)
    assert resolver(node_range) == (expected_offset, expected_offset)


def test_source_offset_resolver_batches_unique_ranges_and_caches_codegen():
    """
    One lazy codegen pass resolves every unique registered endpoint and serves later ranges from cache.
    """
    source = 'a = 1 + 2\nb = 3 * 4\n'
    module = parse_module(source)
    add_range = CodeRange(CodePosition(1, 5), CodePosition(1, 8))
    multiply_range = CodeRange(CodePosition(2, 5), CodePosition(2, 8))
    registered_ranges = (node_range for node_range in [add_range, add_range, multiply_range])

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
    Every provider range stays bounded, ordered, monotone, shared-position consistent, and batch/single equivalent.
    """
    wrapper = MetadataWrapper(parse_module(source))
    node_ranges = list(wrapper.resolve(WhitespaceInclusivePositionProvider).values())
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


def test_code_fragments_cover_single_node_and_file_boundaries():
    """
    Nodes spanning or touching file boundaries leave the corresponding surrounding fragments empty.
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
    A zero-width Parameters node partitions non-empty source without shifting either fragment.
    """
    source = 'def f():\n    pass\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Parameters) -> Parameters:
        return node

    @changer.filter
    def capture(node: Parameters, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 6), CodePosition(1, 6))
    assert context.position.code_before == 'def f('
    assert context.position.code_after == '):\n    pass\n'
    assert context.position.code_before + '' + context.position.code_after == context.position.source


def test_code_fragments_handle_later_statement_without_final_newline():
    """
    At virtual EOF, a statement keeps the preceding CRLF and Context adds no final newline, unlike code_for_node().
    """
    source = 'head = 0\r\nx = 1'
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
    context = contexts[1]
    assert context.position.node_range == CodeRange(CodePosition(2, 0), CodePosition(3, 0))
    assert context.position.code_before == 'head = 0\r\n'
    assert context.position.code_after == ''
    assert context.position.code_before + 'x = 1' + context.position.code_after == context.position.source


def test_code_fragments_preserve_semicolon_owned_trivia():
    """
    The first Assign owns its trailing semicolon and space, excluding them from code_after.
    """
    source = 'x=1; y=2\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Assign) -> Assign:
        return node

    @changer.filter
    def capture(node: Assign, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 2
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(1, 5))
    assert context.position.code_before == ''
    assert context.position.code_after == 'y=2\n'
    assert context.position.code_before + 'x=1; ' + context.position.code_after == context.position.source


def test_code_fragments_preserve_decorators_and_surrounding_comments():
    """
    FunctionDef's span includes decorators, an indented body, and newlines but excludes surrounding comments.
    """
    source = '# h\n@dec\ndef f(x: int = 1):\n    return x\n# f\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: FunctionDef) -> FunctionDef:
        return node

    @changer.filter
    def capture(node: FunctionDef, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(2, 0), CodePosition(5, 0))
    assert context.position.code_before == '# h\n'
    assert context.position.code_after == '# f\n'
    assert context.position.code_before + '@dec\ndef f(x: int = 1):\n    return x\n' + context.position.code_after == context.position.source


def test_code_fragments_preserve_nested_indentation_and_comments():
    """
    A nested statement span retains ambient indentation that Module.code_for_node() would omit.

    The exact partition also preserves its leading and inline comments and multiline assignment.
    """
    source = '# header\nif True:\n    # lead\n    value = (\n        1 + 2  # inner\n    )\n# footer\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: SimpleStatementLine) -> SimpleStatementLine:
        return node

    @changer.filter
    def capture(node: SimpleStatementLine, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(3, 0), CodePosition(7, 0))
    assert context.position.code_before == '# header\nif True:\n'
    assert context.position.code_after == '# footer\n'
    assert context.position.code_before + '    # lead\n    value = (\n        1 + 2  # inner\n    )\n' + context.position.code_after == context.position.source


def test_codegen_indent_does_not_search_forward_in_source():
    """
    A generated suite indent cannot jump to matching spaces later in source after an omitted continuation.
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

    @changer.converter
    def convert(node: BinaryOperation) -> BinaryOperation:
        return node

    @changer.filter
    def capture(node: BinaryOperation, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
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
    def convert(node: Add) -> Add:
        return node

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 2
    first_context, second_context = contexts
    assert first_context.position.node_range == CodeRange(CodePosition(1, 9), CodePosition(1, 12))
    assert first_context.position.code_before == 'foo = foo'
    assert first_context.position.code_after == 'foo\nfoo = foo + foo\n'
    assert first_context.position.code_before + ' + ' + first_context.position.code_after == first_context.position.source
    assert second_context.position.node_range == CodeRange(CodePosition(2, 9), CodePosition(2, 12))
    assert second_context.position.code_before == 'foo = foo + foo\nfoo = foo'
    assert second_context.position.code_after == 'foo\n'
    assert second_context.position.code_before + ' + ' + second_context.position.code_after == second_context.position.source


def test_code_fragments_map_later_node_across_mixed_newlines():
    """
    A third-line Add maps across preceding CRLF and bare CR while preserving the following LF.
    """
    source = 'first=0\r\nsecond=1\rthird = 2  +\t3\nlast=4'
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
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(3, 9), CodePosition(3, 13))
    assert context.position.code_before == 'first=0\r\nsecond=1\rthird = 2'
    assert context.position.code_after == '3\nlast=4'
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


def test_code_fragments_preserve_unicode_before_later_node():
    """
    Non-BMP and combining characters before a later Add count as Python characters, not UTF-8 bytes.
    """
    source = 'header = "🙂e\u0301"\nvalue = π  +\t2\n'
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
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(2, 9), CodePosition(2, 13))
    assert context.position.code_before == 'header = "🙂e\u0301"\nvalue = π'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


def test_code_fragments_count_same_line_unicode_as_python_characters():
    """
    Non-BMP and combining characters on Add's line each occupy one LibCST column and one source index.
    """
    source = 'header = "🙂e\u0301"; value = π  +\t2\n'
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
    assert context.position.node_range == CodeRange(CodePosition(1, 25), CodePosition(1, 29))
    assert context.position.code_before == 'header = "🙂e\u0301"; value = π'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


def test_code_fragments_preserve_bom_before_later_node():
    """
    Absolute offsets count an initial BOM and Unicode header before a second-line Add.

    The BOM remains in code_before rather than shifting the Add's contextual span.
    """
    source = '\ufeffheader = "🙂e\u0301"\nvalue = 1  +\t2\ntail = 3\n'
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


@pytest.mark.parametrize('source', ['', 'x=1\n'], ids=['empty-source', 'ordinary-source'])
def test_module_fragments_cover_empty_and_nonempty_sources_completely(source):
    """
    Module spans empty and non-empty sources, including an empty range, without surrounding fragments.
    """
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Module, context: Context) -> Module:
        contexts.append(context)
        return node

    coordinate = next(changer.iterate_coordinates())
    assert changer.apply_coordinate(coordinate) == source
    assert len(contexts) == 1
    context = contexts[0]
    expected_end_position = CodePosition(1, 0) if not source else CodePosition(2, 0)
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

    @changer.converter
    def convert(node: Module, context: Context) -> Module:
        contexts.append(context)
        return node

    coordinate = next(changer.iterate_coordinates())
    changer.apply_coordinate(coordinate)
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(2, 0))
    assert context.position.code_before == '\ufeff'
    assert context.position.code_after == ''
    assert context.position.code_before + 'x=1\n' + context.position.code_after == context.position.source


@pytest.mark.parametrize(
    ('source', 'expected_before', 'expected_module_span'),
    [
        pytest.param('\f', '', '\f', id='form-feed-only'),
        pytest.param(' \f', '', ' \f', id='space-and-form-feed'),
        pytest.param('\ufeff\f', '\ufeff', '\f', id='bom-and-form-feed'),
    ],
)
def test_module_fragments_keep_eof_form_feed_in_module_span(source, expected_before, expected_module_span):
    """
    An EOF form feed remains in Module's span for whitespace-only files, with or without a BOM.
    """
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Module, context: Context) -> Module:
        contexts.append(context)
        return node

    coordinate = next(changer.iterate_coordinates())
    changer.apply_coordinate(coordinate)
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.code_before == expected_before
    assert context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(2, 0))
    assert context.position.code_after == ''
    assert context.position.code_before + expected_module_span + context.position.code_after == context.position.source


@pytest.mark.parametrize('prefix', [pytest.param('\f', id='form-feed'), pytest.param('\t\f', id='tab-and-form-feed')])
def test_code_fragments_preserve_leading_form_feed_prefix(prefix):
    """
    A codegen-omitted form-feed prefix remains in code_before without shifting Add's span, with or without a tab.
    """
    source = f'{prefix}result = 1  + 2\n'
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
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 10), CodePosition(1, 14))
    assert context.position.code_before == f'{prefix}result = 1'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + '  + ' + context.position.code_after == context.position.source


@pytest.mark.parametrize(
    'prefix',
    [
        pytest.param('\\\n', id='lf-continuation'),
        pytest.param('\\\r', id='cr-continuation'),
        pytest.param('\\\r\n', id='crlf-continuation'),
        pytest.param('\f\\\n', id='form-feed-and-continuation'),
        pytest.param('\ufeff\\\n', id='bom-and-continuation'),
        pytest.param('\\\n\t\f', id='continued-tab-and-form-feed'),
    ],
)
def test_code_fragments_preserve_leading_line_continuation_prefix(prefix):
    """
    Codegen-omitted LF, CR, and CRLF continuations stay in code_before across BOM, form-feed, and indentation variants.
    """
    source = f'{prefix}result = 1  + 2\n'
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
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 10), CodePosition(1, 14))
    assert context.position.code_before == f'{prefix}result = 1'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + '  + ' + context.position.code_after == context.position.source


@pytest.mark.parametrize(
    'prefix',
    [
        pytest.param('\n\f', id='blank-line-before-form-feed'),
        pytest.param('# lead\n \f', id='comment-before-form-feed'),
        pytest.param('\n\\\n', id='blank-line-before-continuation'),
        pytest.param('# lead\r\n\\\r\n', id='crlf-comment-before-continuation'),
    ],
)
def test_code_fragments_preserve_codegen_omitted_prefix_after_blank_or_comment_line(prefix):
    """
    An omitted form feed or continuation stays in code_before after a blank or comment line without shifting the later Add.
    """
    source = f'{prefix}result = 1  + 2\n'
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
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(2, 10), CodePosition(2, 14))
    assert context.position.code_before == f'{prefix}result = 1'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + '  + ' + context.position.code_after == context.position.source


def test_code_fragments_preserve_nested_form_feed_indentation():
    """
    A form feed in suite indentation affects LibCST columns without misaligning nested fragments.
    """
    source = 'if True:\n\f    result = 1  + 2\n'
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
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(2, 15), CodePosition(2, 19))
    assert context.position.code_before == 'if True:\n\f    result = 1'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + '  + ' + context.position.code_after == context.position.source


@pytest.mark.parametrize(
    ('source', 'expected_range', 'expected_before', 'expected_after'),
    [
        pytest.param(
            'value = (\n\f1  +\t2\n)\n',
            CodeRange(CodePosition(2, 2), CodePosition(2, 6)),
            'value = (\n\f1',
            '2\n)\n',
            id='form-feed-in-parenthesized-expression',
        ),
        pytest.param(
            'value=(\n\\\n1  +\t2\n)\n',
            CodeRange(CodePosition(3, 1), CodePosition(3, 5)),
            'value=(\n\\\n1',
            '2\n)\n',
            id='continuation-in-parenthesized-expression',
        ),
        pytest.param(
            's = f"""\n\f{1  +\t2}\n"""\n',
            CodeRange(CodePosition(2, 3), CodePosition(2, 7)),
            's = f"""\n\f{1',
            '2}\n"""\n',
            id='form-feed-in-fstring',
        ),
        pytest.param(
            's = """\n\\\ntext\n"""\nresult=π  +\t2\n',
            CodeRange(CodePosition(5, 8), CodePosition(5, 12)),
            's = """\n\\\ntext\n"""\nresult=π',
            '2\n',
            id='continuation-in-preceding-triple-string',
        ),
        pytest.param(
            'if True:\n    x = 0\n\\\nresult = 1  +\t2\n',
            CodeRange(CodePosition(3, 14), CodePosition(3, 18)),
            'if True:\n    x = 0\n\\\nresult = 1',
            '2\n',
            id='continuation-after-indented-suite',
        ),
    ],
)
def test_code_fragments_preserve_alignment_across_parser_contexts(source, expected_range, expected_before, expected_after):
    """
    Exact fragments verify Add alignment across form feeds and continuations inside parentheses and f-strings, after a triple-quoted string, and after an indented suite.
    """
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
    context = contexts[0]
    assert context.position.node_range == expected_range
    assert context.position.code_before == expected_before
    assert context.position.code_after == expected_after
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


def test_code_fragments_align_nested_string_matching_enclosing_fstring_quotes():
    """
    A nested SimpleString sharing its f-string's quotes includes enclosing parentheses but excludes the closing brace.
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
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 13), CodePosition(2, 9))
    assert context.position.code_before == 'value = f"""{'
    assert context.position.code_after == '}\ntail"""\n'
    assert context.position.code_before + '("""inner\n\fbody""")' + context.position.code_after == context.position.source


def test_pipeline_and_direct_source_positions_partition_form_feed_identically():
    """
    Pipeline and directly constructed SourcePositions partition an omitted form feed identically.
    """
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
        parse_module(first_context.position.source),
        first_context.position.source,
        [first_context.position.node_range],
    )
    direct_position = SourcePosition(
        first_context.position.coordinate,
        first_context.position.source,
        first_context.position.node_range,
        direct_resolver,
    )
    assert direct_position == first_context.position
    assert direct_position.code_before == first_context.position.code_before
    assert direct_position.code_after == first_context.position.code_after
    assert second_context.position.node_range == CodeRange(CodePosition(2, 0), CodePosition(3, 0))
    assert second_context.position.code_before == 'x=1\n\f'
    assert second_context.position.code_after == ''
    assert second_context.position.code_before + 'result=2\n' + second_context.position.code_after == second_context.position.source
