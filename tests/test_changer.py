from typing import Any, List, Union
from unittest.mock import patch

import pytest
from full_match import match
from libcst import Add, CSTNode, Float, Multiply, SimpleString, Subtract, metadata
from libcst.metadata import CodePosition, CodeRange
from metacode import ParsedComment
from sigmatch import SignatureMismatchError

from cstvis import (
    Changer,
    Collector,
    Context,
    ConverterWrappingError,
    Coordinate,
)
from cstvis.source_offsets import SourceOffsetResolver
from tests.helpers import collect_nodes

"""Tests for Changer orchestration and callback dispatch.

When a test uses both the `with_context` and `unfold` fixtures, it runs the
scenario with node-only and Context-aware callbacks, using both bare and called
decorator forms.
"""


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5',
            'b = 12 * a #lol',
            'c = 12 + b # kek',
            'c *= 5',
            'c += 5',
            'a = c + 5',
        ],),
    ],
)
def test_iterate_coordinates_reports_matching_add_coordinates(file):
    """Returns the two `Add` coordinates in source order, with no file path and the expected class name and start/end positions."""
    changer = Changer(file)

    @changer.converter
    def identity_converter(node: Add):
        return node

    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 2

    assert [coordinate.file for coordinate in coordinates] == [None, None]
    assert coordinates[0].class_name == 'Add'
    assert coordinates[0].start_line == 3
    assert coordinates[0].start_column == 7
    assert coordinates[0].end_line == 3
    assert coordinates[0].end_column == 8

    assert coordinates[1].class_name == 'Add'
    assert coordinates[1].start_line == 6
    assert coordinates[1].start_column == 6
    assert coordinates[1].end_line == 6
    assert coordinates[1].end_column == 7


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 1 + 2',
            'b = 3 + 4',
        ],),
    ],
)
def test_iterate_coordinates_filters_matching_add_without_calling_converter(file):
    """
    Iterating coordinates applies filters without running converters.

    When a filter rejects one matching Add node, only the accepted coordinate is emitted and the converter callback remains untouched.
    """
    changer = Changer(file)
    converter_calls = []

    @changer.converter
    def identity_converter(node: Add):
        converter_calls.append(node)
        return node

    @changer.filter
    def filter_second_add(node: Add, context: Context) -> bool:  # noqa: ARG001
        return context.position.coordinate.start_line == 2

    coordinates = list(changer.iterate_coordinates())

    assert converter_calls == []
    assert len(coordinates) == 1
    assert coordinates[0].start_line == 2
    assert coordinates[0].start_column == 6


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5',
            'b = 12 * a #lol',
            'c = 12 + b # kek',
        ],),
    ],
)
def test_apply_one_change(file, with_context, unfold):
    """
    Applying the coordinate produced by a Changer-registered converter returns
    the full source with only the selected operation rewritten.

    Using the only Add coordinate, the plus becomes a minus and surrounding whitespace is preserved.
    """
    changer = Changer(file)

    if with_context:
        @unfold(changer.converter)
        def change_add_to_sub(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )
    else:
        @unfold(changer.converter)
        def change_add_to_sub(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

    results = [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]

    assert len(results) == 1
    assert results[0] == file.replace('+', '-')


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5 + 6+ 7 +  8',
        ],),
    ],
)
def test_apply_three_same_line_changes_independently(file, with_context, unfold):
    """Each same-line `Add` coordinate applies independently to the original source, changing only its operator and preserving the other additions and spacing."""
    changer = Changer(file)

    if with_context:
        @unfold(changer.converter)
        def change_add_to_sub(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )
    else:
        @unfold(changer.converter)
        def change_add_to_sub(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

    results = [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]

    assert len(results) == 3
    assert results == [
        'a = 5 - 6+ 7 +  8',
        'a = 5 + 6- 7 +  8',
        'a = 5 + 6+ 7 -  8',
    ]


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5 + 6- 7',
        ],),
    ],
)
def test_two_converters_for_different_operators_on_same_line(file, with_context, unfold):
    """Each coordinate changes only its own operator: `Add` rewrites the plus, `Subtract` rewrites the minus, and the other operator stays untouched."""
    changer = Changer(file)

    if with_context:
        @unfold(changer.converter)
        def change_add_to_sub(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.converter)
        def change_sub_to_add(node: Subtract, context: Context):  # noqa: ARG001
            return Add(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )
    else:
        @unfold(changer.converter)
        def change_add_to_sub(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.converter)
        def change_sub_to_add(node: Subtract):
            return Add(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

    results = [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]

    assert len(results) == 2
    assert results == [
        'a = 5 - 6- 7',
        'a = 5 + 6+ 7',
    ]


@pytest.mark.parametrize(
    ['strings', 'expected_comment'],
    [
        (['a = 5 + 6- 7'], None),
        (['# preceding comment', 'a = 5 + 6- 7'], None),
        (['a = 5 + 6- 7#'], ''),
        (['a = 5 + 6- 7# ololo!'], ' ololo!'),
        (['a = 5 + 6- 7# other_key: action'], ' other_key: action'),
        (['a = 5 + 6- 7#key: action'],  'key: action'),
        (['a = 5 + 6- 7# key: action'],  ' key: action'),
        (['a = 5 + 6- 7 # key: action'],  ' key: action'),
        (['a = 5 + 6- 7 # key: action# ololo!'],  ' key: action# ololo!'),
    ],
)
def test_read_comments(file, expected_comment, unfold):
    """
    Context exposes the same-line comment for the node being converted.

    No same-line comment yields `None`; a bare `#` yields an empty string.
    Otherwise, the value is the raw comment text after removing only the leading
    `#`, preserving whitespace after it and any later `#` characters.
    """
    changer = Changer(file)

    received_comments = []

    @unfold(changer.converter)
    def change_something(node: Add, context: Context):
        received_comments.append(context.comment)
        return node

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    changer.apply_coordinate(coordinates[0])

    assert len(received_comments) == 1
    assert received_comments[0] == expected_comment


@pytest.mark.parametrize(
    ['strings', 'expected_metacodes'],
    [
        (['a = 5 + 6- 7'], []),
        (['a = 5 + 6- 7#'], []),
        (['a = 5 + 6- 7# ololo!'], []),
        (['a = 5 + 6- 7# other_key: action'], []),
        (['a = 5 + 6- 7# key: action'], [ParsedComment(key='key', command='action', arguments=[])]),
        (['a = 5 + 6- 7 # key: action'], [ParsedComment(key='key', command='action', arguments=[])]),
        (['a = 5 + 6- 7 # key: action# ololo!'], [ParsedComment(key='key', command='action', arguments=[])]),
    ],
)
def test_read_metacodes_from_comment(file, expected_metacodes, unfold):
    """
    Context.get_metacodes('key') returns only matching same-line metacodes.

    Inputs without a `key: action` metacode return an empty list, while matching comments return one parsed entry even when adjacent to code or followed by extra comment text.
    """
    changer = Changer(file)

    received_metacodes = []

    @unfold(changer.converter)
    def change_something(node: Add, context: Context):
        received_metacodes.append(context.get_metacodes('key'))
        return node

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    changer.apply_coordinate(coordinates[0])

    assert len(received_metacodes) == 1
    assert received_metacodes[0] == expected_metacodes


def test_read_comments_and_metacodes_with_bare_cr():
    """
    `Context.comment` and `get_metacodes` work when the source uses a bare CR
    line ending.
    """
    changer = Changer('a = 1 + 2  # key: action\r')
    contexts = []

    @changer.converter
    def convert(node: Add):
        return node

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert contexts[0].comment == ' key: action'
    assert contexts[0].get_metacodes('key') == [ParsedComment(key='key', command='action', arguments=[])]


def test_read_metacodes_returns_matches_for_multiple_keys_in_comment_order():
    """Multiple keys return matching metacodes in comment order."""
    changer = Changer('a = 5 + 6- 7 # key: action# other: x')
    received_metacodes = []

    @changer.converter
    def convert(node: Add, context: Context):
        received_metacodes.append(context.get_metacodes(['other', 'missing', 'key']))
        return node

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    changer.apply_coordinate(coordinates[0])

    assert received_metacodes == [[
        ParsedComment(key='key', command='action', arguments=[]),
        ParsedComment(key='other', command='x', arguments=[]),
    ]]


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5 + 6- 7',
        ],),
    ],
)
@pytest.mark.parametrize(
    'annotation',
    [
        pytest.param(None, id='unannotated'),
        pytest.param(Any, id='any'),
        pytest.param(CSTNode, id='cstnode'),
        pytest.param(Add, id='add'),
    ],
)
@pytest.mark.parametrize('filter_result', [True, False], ids=['allow', 'reject'])
def test_supported_filter_annotations_gate_conversion(
    file, with_context, unfold, annotation, filter_result,
):
    """Unannotated, `Any`, `CSTNode`, and `Add` filters permit the plus-to-minus change on a truthy result and suppress it on a falsy one. Each runs once for the `Add` candidate."""
    changer = Changer(file)
    filter_calls = []

    if with_context:
        @unfold(changer.converter)
        def change_add_to_subtract(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )
    else:
        @unfold(changer.converter)
        def change_add_to_subtract(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

    if with_context:
        def gate_conversion(node, context):  # noqa: ARG001
            filter_calls.append(node)
            return filter_result
    else:
        def gate_conversion(node):  # type: ignore[misc]
            filter_calls.append(node)
            return filter_result

    if annotation is not None:
        gate_conversion.__annotations__['node'] = annotation
    unfold(changer.filter)(gate_conversion)

    results = [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]

    assert len(filter_calls) == 1
    assert isinstance(filter_calls[0], Add)
    expected_filter_type = Add if annotation is Add else CSTNode
    assert set(changer.filters_by_types) == {expected_filter_type}
    if filter_result:
        assert results == [file.replace('+', '-')]
    else:
        assert results == []


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5 + 6- 7',
        ],),
    ],
)
def test_filter_for_nonmatching_node_type_is_not_called(file, with_context, unfold):
    """With only an `Add` converter registered, a `Subtract`-annotated filter never runs, so the plus-to-minus change applies."""
    changer = Changer(file)
    filter_calls = []

    if with_context:
        @unfold(changer.converter)
        def change_add_to_subtract(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def reject_subtract(node: Subtract, context: Context) -> bool:  # noqa: ARG001
            filter_calls.append(node)
            return False

    else:
        @unfold(changer.converter)
        def change_add_to_subtract(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def reject_subtract(node: Subtract) -> bool:
            filter_calls.append(node)
            return False

    results = [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]

    assert [wrapper.function for wrapper in changer.filters_by_types[Subtract]] == [reject_subtract]
    assert not changer.filters_by_types.get(Add)
    assert filter_calls == []
    assert results == [file.replace('+', '-')]


@pytest.mark.parametrize('annotation', [None, Any, CSTNode], ids=['unannotated', 'any', 'cstnode'])
def test_no_annotation_any_or_cstnode_converters_are_catch_all(annotation, with_context, unfold):
    """
    An unannotated parameter, `Any`, and an explicit `CSTNode` annotation all
    register as catch-alls, so discovery emits one coordinate per visited node
    and identity application leaves `'1'` unchanged.
    """
    changer = Changer('1')
    converter_calls = []

    if with_context:
        def converter_func(node, context):  # noqa: ARG001
            converter_calls.append(node)
            return node
    else:
        def converter_func(node):  # type: ignore[misc]
            converter_calls.append(node)
            return node

    if annotation is not None:
        converter_func.__annotations__['node'] = annotation

    converter = unfold(changer.converter)(converter_func)

    assert set(changer.converters_by_types) == {CSTNode}
    assert changer.converters_by_types[CSTNode] == [converter]

    coordinates = list(changer.iterate_coordinates())
    visited_nodes = collect_nodes(changer.module)
    assert len(coordinates) == len(visited_nodes)
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1'] * len(coordinates)
    assert len(converter_calls) == len(coordinates)
    assert all(actual.deep_equals(expected) for actual, expected in zip(converter_calls, visited_nodes))


def test_str_annotation_dispatches_to_simple_string(with_context, unfold):
    """The `str` shortcut maps to `SimpleString`; the converter runs once for the single literal and its replacement applies across both callback signatures and decorator forms."""
    changer = Changer('a = "kek"')

    received_nodes = []

    if with_context:
        @unfold(changer.converter)
        def converter_func(node: str, context: Context):  # noqa: ARG001
            received_nodes.append(node)
            return node.with_changes(value='"changed"')  # type: ignore[attr-defined]
    else:
        @unfold(changer.converter)
        def converter_func(node: str):
            received_nodes.append(node)
            return node.with_changes(value='"changed"')  # type: ignore[attr-defined]

    results = [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]

    assert results == ['a = "changed"']
    assert len(received_nodes) == 1
    assert isinstance(received_nodes[0], SimpleString)
    assert received_nodes[0].value == '"kek"'


def test_float_annotation_dispatches_to_float_literal(with_context, unfold):
    """The `float` shortcut converts the only literal in `a = 5.0` to `6.0`; `apply_coordinate()` leaves `Changer.source` unchanged, and a new discovery pass yields the same result."""
    changer = Changer('a = 5.0')
    original_source = changer.source

    if with_context:
        @unfold(changer.converter)
        def converter_func(node: float, context: Context):  # noqa: ARG001
            return node.with_changes(value=repr(node.evaluated_value + 1))  # type: ignore[attr-defined]
    else:
        @unfold(changer.converter)
        def converter_func(node: float):
            return node.with_changes(value=repr(node.evaluated_value + 1))  # type: ignore[attr-defined]

    assert changer.apply_coordinate(next(changer.iterate_coordinates())) == 'a = 6.0'
    assert changer.source == original_source

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == ['a = 6.0']


def test_filter_with_invalid_annotation_is_rejected(unfold):
    """A `Changer.filter` callback annotated with a non-`CSTNode` class raises `TypeError` in both direct and called forms; its signature is otherwise valid, so this is not a signature mismatch."""
    changer = Changer('a = 5')

    class SomeClass:
        pass

    with pytest.raises(TypeError, match=match('The type annotation for the first argument of the function must be descended from the libcst.CSTNode class.')):
        @unfold(changer.filter)
        def filter_func(node: SomeClass, context: Context):  # noqa: ARG001
            return True

    assert not changer.filters_by_types


def test_two_converters_for_same_node(with_context, unfold):
    """For `5 + 5`, two `Add` converters yield independent results, `5 - 5` and `5 * 5`."""
    changer = Changer('5 + 5')

    if with_context:
        @unfold(changer.converter)
        def to_subtract(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.converter)
        def to_multiply(node: Add, context: Context):  # noqa: ARG001
            return Multiply(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

    else:
        @unfold(changer.converter)
        def to_subtract(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.converter)
        def to_multiply(node: Add):
            return Multiply(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 2
    results = {coordinate.converter_id: changer.apply_coordinate(coordinate) for coordinate in coordinates}
    assert results == {
        to_subtract.get_function_id(): '5 - 5',
        to_multiply.get_function_id(): '5 * 5',
    }


def test_collected_converter_is_discovered_and_applied(with_context, unfold):
    """A collected converter rewrites the source's only `Add` to `Subtract` for node-only and Context-aware callbacks and both bare and called `Collector.converter` forms."""
    collector = Collector()

    if with_context:
        @unfold(collector.converter)
        def change_add_to_subtract(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )
    else:
        @unfold(collector.converter)
        def change_add_to_subtract(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

    changer = Changer('a = 5 + 5', collector=collector)

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == ['a = 5 - 5']


def test_collected_filter_gates_collected_converter(with_context, unfold):
    """With a collected filter returning `False`, the Collector-backed Changer emits no changes; after the filter state flips to `True`, the same source yields `a = 5 - 5`."""
    collector = Collector()

    filter_allows = False

    if with_context:
        @unfold(collector.converter)
        def change_add_to_subtract(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(collector.filter)
        def gate_conversion(node: Add, context: Context):  # noqa: ARG001
            return filter_allows

    else:
        @unfold(collector.converter)
        def change_add_to_subtract(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(collector.filter)
        def gate_conversion(node: Add):  # noqa: ARG001
            return filter_allows

    changer = Changer('a = 5 + 5', collector=collector)

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == []

    filter_allows = True

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == ['a = 5 - 5']


def test_union_annotation_expands_member_types(with_context, unfold):
    """`Union[Add, Multiply, Subtract]` dispatches the converter for each matching operator in `5 * 5 - 5 + 5`."""
    changer = Changer('5 * 5 - 5 + 5')
    annotation = Union[Add, Multiply, Subtract]
    applied_types = []

    if with_context:
        def replace_operator(node, context):  # noqa: ARG001
            applied_types.append(type(node))
            replacement_type = Add if isinstance(node, Multiply) else Multiply
            return replacement_type(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )
    else:
        def replace_operator(node):  # type: ignore[misc]
            applied_types.append(type(node))
            replacement_type = Add if isinstance(node, Multiply) else Multiply
            return replacement_type(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

    replace_operator.__annotations__['node'] = annotation
    unfold(changer.converter)(replace_operator)

    assert set(changer.converters_by_types) == {Add, Multiply, Subtract}
    coordinates = list(changer.iterate_coordinates())
    assert [coordinate.class_name for coordinate in coordinates] == ['Multiply', 'Subtract', 'Add']
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == [
        '5 + 5 - 5 + 5',
        '5 * 5 * 5 + 5',
        '5 * 5 - 5 * 5',
    ]
    assert applied_types == [Multiply, Subtract, Add]


@pytest.mark.parametrize(
    ('source', 'expected_sources'),
    [
        pytest.param('5 - 5 + 5', ['6 - 5 + 5', '5 - 6 + 5', '5 - 5 + 6'], id='same-width'),
        pytest.param('9 - 9 + 9', ['10 - 9 + 9', '9 - 10 + 9', '9 - 9 + 10'], id='growing-width'),
    ],
)
def test_int_converter_increments_each_integer_literal(with_context, unfold, source, expected_sources):
    """An `int` annotation targets integer literals; each occurrence increments independently, and a longer replacement rewrites only the selected literal."""
    changer = Changer(source)

    if with_context:
        @unfold(changer.converter)
        def convert_ints(node: int, context):  # noqa: ARG001
            return node.with_changes(value=repr(node.evaluated_value + 1))  # type: ignore[attr-defined]
    else:
        @unfold(changer.converter)
        def convert_ints(node: int):
            return node.with_changes(value=repr(node.evaluated_value + 1))  # type: ignore[attr-defined]

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 3
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == expected_sources


@pytest.mark.parametrize('source', ['5 - 5 + 5', '5 - 6 + 7'])
def test_any_annotated_converter_dispatches_once_per_coordinate(with_context, unfold, source):
    """An `Any` converter runs once per coordinate in CST traversal order. Context-aware callbacks see a `position.coordinate` matching the applied coordinate's class name and line/column bounds, with `converter_id=None`; identity conversion preserves the source."""
    changer = Changer(source)

    captured_invocations = []

    if with_context:
        @unfold(changer.converter)
        def capture_node(node: Any, context):
            captured_invocations.append((node, context))
            return node
    else:
        @unfold(changer.converter)
        def capture_node(node: Any):
            captured_invocations.append((node, None))
            return node

    coordinates = list(changer.iterate_coordinates())
    visited_nodes = collect_nodes(changer.module)
    assert captured_invocations == []
    assert len(coordinates) > 10
    assert len(coordinates) == len(visited_nodes)
    assert [coordinate.class_name for coordinate in coordinates] == [type(node).__name__ for node in visited_nodes]

    for coordinate, visited_node in zip(coordinates, visited_nodes):
        call_count_before = len(captured_invocations)
        assert changer.apply_coordinate(coordinate) == source

        assert len(captured_invocations) == call_count_before + 1
        captured_node, captured_context = captured_invocations[-1]
        assert captured_node.__class__.__name__ == coordinate.class_name
        assert captured_node.deep_equals(visited_node)
        if with_context:
            assert isinstance(captured_context, Context)
            assert captured_context.position.coordinate == Coordinate(
                None,
                coordinate.class_name,
                coordinate.start_line,
                coordinate.start_column,
                coordinate.end_line,
                coordinate.end_column,
            )

    assert len(captured_invocations) == len(coordinates)


def test_no_coordinates_when_converter_annotation_matches_no_node(with_context, unfold):
    """
    Discovery emits no coordinates for a `float`-annotated converter on
    `5 - 5 + 5`, whose numeric literals are all integers, so no changes are
    applied across callback and decorator variants.
    """
    changer = Changer('5 - 5 + 5')
    converter_calls = []

    if with_context:
        @unfold(changer.converter)
        def record_float_node(node: float, context):  # noqa: ARG001
            converter_calls.append(node)
            return node
    else:
        @unfold(changer.converter)
        def record_float_node(node: float):
            converter_calls.append(node)
            return node

    assert changer.converters_by_types[Float] == [record_float_node]
    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == []
    assert converter_calls == []


def test_registered_callbacks_report_function_based_ids(unfold):
    """Converter and filter wrappers report function-based IDs computed from the original undecorated callables, for both bare and called decorator forms."""
    changer = Changer('5 - 5 + 5')

    def converter_function(node: float, context):  # noqa: ARG001
        return node

    def filter_function(node: float, context):  # noqa: ARG001
        return False

    unfold(changer.converter)(converter_function)
    unfold(changer.filter)(filter_function)

    converter = changer.converters_by_types[Float][0]
    filter_wrapper = changer.filters_by_types[Float][0]

    expected_converter_id = f'{converter_function.__module__}:{converter_function.__name__}:{converter_function.__code__.co_firstlineno}'
    expected_filter_id = f'{filter_function.__module__}:{filter_function.__name__}:{filter_function.__code__.co_firstlineno}'

    assert converter.function is converter_function
    assert filter_wrapper.function is filter_function
    assert converter.get_function_id() == expected_converter_id
    assert filter_wrapper.get_function_id() == expected_filter_id


def test_converter_and_filter_with_invalid_arity_are_rejected(unfold):
    """Zero- and three-argument converter and filter callbacks raise `SignatureMismatchError` during registration, whether used directly or as called decorator factories."""
    changer = Changer('5 - 5 + 5')
    message = match('A function that takes a CST node and a context is expected.')

    with pytest.raises(SignatureMismatchError, match=message):
        @unfold(changer.converter)
        def converter_without_arguments():
            ...

    with pytest.raises(SignatureMismatchError, match=message):
        @unfold(changer.converter)
        def converter_with_three_arguments(node: Add, context: Context, extra: str):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

    with pytest.raises(SignatureMismatchError, match=message):
        @unfold(changer.filter)
        def filter_without_arguments():
            return False

    with pytest.raises(SignatureMismatchError, match=message):
        @unfold(changer.filter)
        def filter_with_three_arguments(node: Add, context: Context, extra: str) -> bool:  # noqa: ARG001
            return False

    assert not changer.converters_by_types
    assert not changer.filters_by_types


@pytest.mark.parametrize('registration_kind', ['changer', 'collector'])
def test_converter_receives_copied_meta_dict(registration_kind):
    """Applying the `Add` coordinate gives a two-argument converter an equal but distinct top-level copy of the decorator metadata in `Context.meta`, for both direct and Collector-backed registration."""
    received_meta = []
    meta = {'key': 123}

    if registration_kind == 'changer':
        changer = Changer('5 - 5 + 5')
        register = changer.converter
    else:
        collector = Collector()
        register = collector.converter

    @register(meta=meta)
    def convert_add_to_multiply(node: Add, context: Context):
        received_meta.append(context.meta)
        return Multiply(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    if registration_kind == 'collector':
        changer = Changer('5 - 5 + 5', collector=collector)

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    changer.apply_coordinate(coordinates[0])

    assert received_meta == [meta]
    assert received_meta[0] is not meta


@pytest.mark.parametrize('registration_kind', ['changer', 'collector'])
def test_filter_receives_copied_meta_dict(registration_kind):
    """Filter decorator metadata reaches `Context.meta` as an equal copy during discovery for direct and Collector-backed registration; rejecting the `Add` leaves no coordinate to apply."""
    received_meta = []
    meta = {'key': 123}

    if registration_kind == 'changer':
        changer = Changer('5 - 5 + 5')
        converter_register = changer.converter
        filter_register = changer.filter
    else:
        collector = Collector()
        converter_register = collector.converter
        filter_register = collector.filter

    @converter_register
    def convert_add_to_multiply(node: Add):
        return Multiply(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    @filter_register(meta=meta)
    def reject_add(node: Add, context: Context):  # noqa: ARG001
        received_meta.append(context.meta)
        return False

    if registration_kind == 'collector':
        changer = Changer('5 - 5 + 5', collector=collector)

    assert list(changer.iterate_coordinates()) == []

    assert received_meta == [meta]
    assert received_meta[0] is not meta


def test_optional_second_parameter_receives_context(unfold):
    """An optional second positional parameter receives a real `Context` even when it defaults to `None` and has no `Context` annotation."""
    changer = Changer('5 + 4')

    contexts = []

    @unfold(changer.converter)
    def capture_context(node: Add, context=None):
        contexts.append(context)
        return node

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    changer.apply_coordinate(coordinates[0])

    assert len(contexts) == 1
    assert isinstance(contexts[0], Context)
    assert contexts[0].position.source == '5 + 4'
    assert contexts[0].position.coordinate.class_name == 'Add'


@pytest.mark.parametrize('callback_kind', ['node_type_filter', 'bound_filter', 'converter'])
def test_context_exposes_original_position_fragments_comment_and_metacodes(callback_kind):
    """
    Filter and converter Contexts expose the original Add's position, fragments,
    comment, and metacodes; the converter result replaces only the Add.
    """
    source = 'left = 1  +\t2 # key: action\r\nright = 3\n'
    changer = Changer(source)
    contexts = []

    if callback_kind == 'converter':
        @changer.converter
        def convert(node: Add, context: Context) -> Subtract:
            contexts.append(context)
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)
    else:
        @changer.converter
        def convert(node: Add) -> Subtract:
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

        if callback_kind == 'node_type_filter':
            @changer.filter
            def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
                contexts.append(context)
                return True
        else:
            @convert.filter
            def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
                contexts.append(context)
                return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == 'left = 1  -\t2 # key: action\r\nright = 3\n'
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.coordinate == Coordinate(None, 'Add', 1, 10, 1, 11)
    assert context.position.node_range == CodeRange(CodePosition(1, 8), CodePosition(1, 12))
    assert context.position.start_offset == 8
    assert context.position.end_offset == 12
    assert context.position.code_before == 'left = 1'
    assert context.position.code_after == '2 # key: action\r\nright = 3\n'
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source
    assert context.comment == ' key: action'
    assert context.get_metacodes('key') == [ParsedComment(key='key', command='action', arguments=[])]


@pytest.mark.parametrize('accepts_context', [True, False], ids=['context-aware', 'node-only'])
@pytest.mark.parametrize(
    ('callback_kind', 'filter_result'),
    [
        ('node_type_filter', False),
        ('node_type_filter', True),
        ('bound_filter', False),
        ('bound_filter', True),
        ('converter', None),
    ],
)
def test_callbacks_without_fragment_reads_do_not_materialize_fragments(  # noqa: C901, PLR0912, PLR0915
    callback_kind, filter_result, accepts_context,
):
    """Callbacks that read no fragments never slice, iterate, split lines, align offsets, or stringify the source. Context-aware callbacks may read `position.coordinate`; node-only callbacks get no `Context`. Both filter outcomes stay fragment-free during discovery, as does converter application."""
    class TrackingString(str):
        __slots__ = ('alignment_operations', 'full_iterations', 'line_materializations', 'slices', 'string_conversions')
        alignment_operations: List[str]
        full_iterations: int
        line_materializations: List[str]
        slices: List[slice]
        string_conversions: int

        def __init__(self, _value: str) -> None:
            self.alignment_operations = []
            self.full_iterations = 0
            self.line_materializations = []
            self.slices = []
            self.string_conversions = 0

        def __getitem__(self, key):  # type: ignore[no-untyped-def]
            if isinstance(key, slice):
                self.slices.append(key)
            return super().__getitem__(key)

        def __iter__(self):  # type: ignore[no-untyped-def]
            self.full_iterations += 1
            return super().__iter__()

        def __str__(self) -> str:
            self.string_conversions += 1
            return super().__str__()

        def find(self, substring, *args):  # type: ignore[no-untyped-def]
            self.alignment_operations.append('find')
            return super().find(substring, *args)

        def split(self, separator=None, maxsplit=-1):  # type: ignore[no-untyped-def]
            self.line_materializations.append('split')
            return super().split(separator, maxsplit)

        def splitlines(self, keepends=False):  # type: ignore[no-untyped-def]
            self.line_materializations.append('splitlines')
            return super().splitlines(keepends)

        def startswith(self, prefix, *args):  # type: ignore[no-untyped-def]
            self.alignment_operations.append('startswith')
            return super().startswith(prefix, *args)

    source = TrackingString('x = 1 + 2\n')
    changer = Changer(source)
    source.alignment_operations.clear()
    source.full_iterations = 0
    source.line_materializations.clear()
    source.slices.clear()
    source.string_conversions = 0
    observed_coordinates = []
    converter_inputs = []
    filter_inputs = []

    if callback_kind == 'converter':
        if accepts_context:
            @changer.converter
            def convert(node: Add, context: Context) -> Subtract:
                observed_coordinates.append(context.position.coordinate)
                converter_inputs.append(node)
                return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)
        else:
            @changer.converter
            def convert(node: Add) -> Subtract:
                converter_inputs.append(node)
                return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)
    else:
        @changer.converter
        def convert(node: Add) -> Subtract:
            converter_inputs.append(node)
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    if callback_kind == 'node_type_filter':
        if accepts_context:
            @changer.filter
            def inspect(node: Add, context: Context) -> bool:
                observed_coordinates.append(context.position.coordinate)
                filter_inputs.append(node)
                return filter_result
        else:
            @changer.filter
            def inspect(node: Add) -> bool:
                filter_inputs.append(node)
                return filter_result
    elif callback_kind == 'bound_filter':
        if accepts_context:
            @convert.filter
            def inspect(node: Add, context: Context) -> bool:
                observed_coordinates.append(context.position.coordinate)
                filter_inputs.append(node)
                return filter_result
        else:
            @convert.filter
            def inspect(node: Add) -> bool:
                filter_inputs.append(node)
                return filter_result

    requested_ranges = []
    resolve_offsets = SourceOffsetResolver.__call__

    def track_alignment(resolver, node_range):  # type: ignore[no-untyped-def]
        requested_ranges.append(node_range)
        return resolve_offsets(resolver, node_range)

    with patch.object(SourceOffsetResolver, '__call__', track_alignment):
        coordinates = list(changer.iterate_coordinates())
        if callback_kind == 'converter' or filter_result:
            assert len(coordinates) == 1
            assert changer.apply_coordinate(coordinates[0]) == 'x = 1 - 2\n'
        else:
            assert coordinates == []

    assert requested_ranges == []
    if accepts_context:
        assert observed_coordinates == [Coordinate(None, 'Add', 1, 6, 1, 7)]
    if callback_kind in ('node_type_filter', 'bound_filter'):
        assert len(filter_inputs) == 1
        assert isinstance(filter_inputs[0], Add)
        if filter_result:
            assert len(converter_inputs) == 1
            assert isinstance(converter_inputs[0], Add)
        else:
            assert converter_inputs == []
    else:
        assert len(converter_inputs) == 1
        assert isinstance(converter_inputs[0], Add)
    assert source.alignment_operations == []
    assert source.slices == []
    assert source.full_iterations == 0
    assert source.line_materializations == []
    assert source.string_conversions == 0


@pytest.mark.parametrize('callback_kind', ['node_type_filter', 'bound_filter', 'converter'])
@pytest.mark.parametrize('fragment_name', ['code_before', 'code_after'])
def test_context_pipeline_materializes_only_requested_fragment(callback_kind, fragment_name):  # noqa: C901
    """
    The node-type-filter, bound-filter, and converter paths resolve and slice
    only the requested fragment once despite repeated reads.
    """
    class TrackingString(str):
        __slots__ = ('full_iterations', 'line_materializations', 'slices', 'string_conversions')
        full_iterations: int
        line_materializations: List[str]
        slices: List[slice]
        string_conversions: int

        def __init__(self, _value: str) -> None:
            self.full_iterations = 0
            self.line_materializations = []
            self.slices = []
            self.string_conversions = 0

        def __getitem__(self, key):  # type: ignore[no-untyped-def]
            if isinstance(key, slice):
                self.slices.append(key)
            return super().__getitem__(key)

        def __iter__(self):  # type: ignore[no-untyped-def]
            self.full_iterations += 1
            return super().__iter__()

        def __str__(self) -> str:
            self.string_conversions += 1
            return super().__str__()

        def split(self, separator=None, maxsplit=-1):  # type: ignore[no-untyped-def]
            self.line_materializations.append('split')
            return super().split(separator, maxsplit)

        def splitlines(self, keepends=False):  # type: ignore[no-untyped-def]
            self.line_materializations.append('splitlines')
            return super().splitlines(keepends)

    source = TrackingString('x = 1 + 2\n')
    changer = Changer(source)
    source.full_iterations = 0
    source.line_materializations.clear()
    source.slices.clear()
    source.string_conversions = 0
    fragment_values = []
    contexts = []

    if callback_kind == 'converter':
        @changer.converter
        def convert(node: Add, context: Context) -> Add:
            contexts.append(context)
            fragment_values.extend([getattr(context.position, fragment_name), getattr(context.position, fragment_name)])
            return node
    else:
        @changer.converter
        def convert(node: Add) -> Add:
            return node

    if callback_kind == 'node_type_filter':
        @changer.filter
        def read_fragment(node: Add, context: Context) -> bool:  # noqa: ARG001
            contexts.append(context)
            fragment_values.extend([getattr(context.position, fragment_name), getattr(context.position, fragment_name)])
            return True
    elif callback_kind == 'bound_filter':
        @convert.filter
        def read_fragment(node: Add, context: Context) -> bool:  # noqa: ARG001
            contexts.append(context)
            fragment_values.extend([getattr(context.position, fragment_name), getattr(context.position, fragment_name)])
            return True

    requested_ranges = []
    resolve_offsets = SourceOffsetResolver.__call__

    def track_alignment(resolver, node_range):  # type: ignore[no-untyped-def]
        requested_ranges.append(node_range)
        return resolve_offsets(resolver, node_range)

    with patch.object(SourceOffsetResolver, '__call__', track_alignment):
        coordinates = list(changer.iterate_coordinates())
        assert len(coordinates) == 1
        if callback_kind == 'converter':
            changer.apply_coordinate(coordinates[0])

    expected_fragment = 'x = 1' if fragment_name == 'code_before' else '2\n'
    expected_slice = slice(None, 5) if fragment_name == 'code_before' else slice(8, None)
    assert len(contexts) == 1
    assert fragment_values == [expected_fragment, expected_fragment]
    assert requested_ranges == [CodeRange(CodePosition(1, 5), CodePosition(1, 8))]
    assert source.slices == [expected_slice]
    unrequested_fragment = 'code_after' if fragment_name == 'code_before' else 'code_before'
    unrequested_offset = 'end_offset' if fragment_name == 'code_before' else 'start_offset'
    assert fragment_name in contexts[0].position.__dict__
    assert unrequested_fragment not in contexts[0].position.__dict__
    assert unrequested_offset not in contexts[0].position.__dict__
    assert source.full_iterations == 0
    assert source.line_materializations == []
    assert source.string_conversions == 0


@pytest.mark.parametrize('callback_kind', ['node_type_filter', 'bound_filter', 'converter'])
def test_context_fragments_can_be_read_after_traversal(callback_kind):  # noqa: C901
    """A captured `Context.position` remains usable and lazy after traversal: discovery slices nothing; reading `code_before`/`code_after` resolves the shared offsets, caches only those two slices, and the fragments plus node text reconstruct the source without full iteration, line splitting, or str conversion."""
    class TrackingString(str):
        __slots__ = ('full_iterations', 'line_materializations', 'slices', 'string_conversions')
        full_iterations: int
        line_materializations: List[str]
        slices: List[slice]
        string_conversions: int

        def __init__(self, _value: str) -> None:
            self.full_iterations = 0
            self.line_materializations = []
            self.slices = []
            self.string_conversions = 0

        def __getitem__(self, key):  # type: ignore[no-untyped-def]
            if isinstance(key, slice):
                self.slices.append(key)
            return super().__getitem__(key)

        def __iter__(self):  # type: ignore[no-untyped-def]
            self.full_iterations += 1
            return super().__iter__()

        def __str__(self) -> str:
            self.string_conversions += 1
            return super().__str__()

        def split(self, separator=None, maxsplit=-1):  # type: ignore[no-untyped-def]
            self.line_materializations.append('split')
            return super().split(separator, maxsplit)

        def splitlines(self, keepends=False):  # type: ignore[no-untyped-def]
            self.line_materializations.append('splitlines')
            return super().splitlines(keepends)

    source = TrackingString('x = 1 + 2\n')
    changer = Changer(source)
    source.full_iterations = 0
    source.line_materializations.clear()
    source.slices.clear()
    source.string_conversions = 0
    contexts = []

    if callback_kind == 'converter':
        @changer.converter
        def convert(node: Add, context: Context) -> Add:
            contexts.append(context)
            return node
    else:
        @changer.converter
        def convert(node: Add) -> Add:
            return node

    if callback_kind == 'node_type_filter':
        @changer.filter
        def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
            contexts.append(context)
            return True
    elif callback_kind == 'bound_filter':
        @convert.filter
        def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
            contexts.append(context)
            return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    if callback_kind == 'converter':
        changer.apply_coordinate(coordinates[0])

    assert source.slices == []
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 5), CodePosition(1, 8))
    assert context.position.code_before == 'x = 1'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + ' + ' + context.position.code_after == context.position.source
    assert source.slices == [slice(None, 5), slice(8, None)]
    assert source.full_iterations == 0
    assert source.line_materializations == []
    assert source.string_conversions == 0


def test_filters_share_source_position_and_offset_cache():
    """Filters for one `Add` share a `SourcePosition`, and both nodes share one resolver: the first fragment read builds the offset cache, and a read for the other node reuses it without new alignment."""
    class TrackingString(str):
        __slots__ = ('alignment_operations', 'slices')
        alignment_operations: List[str]
        slices: List[slice]

        def __init__(self, _value: str) -> None:
            self.alignment_operations = []
            self.slices = []

        def __getitem__(self, key):  # type: ignore[no-untyped-def]
            if isinstance(key, slice):
                self.slices.append(key)
            return super().__getitem__(key)

        def find(self, substring, *args):  # type: ignore[no-untyped-def]
            self.alignment_operations.append('find')
            return super().find(substring, *args)

        def startswith(self, prefix, *args):  # type: ignore[no-untyped-def]
            self.alignment_operations.append('startswith')
            return super().startswith(prefix, *args)

    source = TrackingString('1 + 2 + 3\n')
    changer = Changer(source)
    source.alignment_operations.clear()
    source.slices.clear()
    labeled_contexts = []

    @changer.converter
    def convert(node: Add) -> Add:
        return node

    @changer.filter
    def filter_first(node: Add, context: Context) -> bool:  # noqa: ARG001
        labeled_contexts.append(('first', context))
        return True

    @changer.filter
    def filter_second(node: Add, context: Context) -> bool:  # noqa: ARG001
        labeled_contexts.append(('second', context))
        return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 2
    assert [label for label, _ in labeled_contexts] == ['first', 'second', 'first', 'second']

    inner_add_position = labeled_contexts[0][1].position
    outer_add_position = labeled_contexts[2][1].position

    assert inner_add_position is labeled_contexts[1][1].position
    assert outer_add_position is labeled_contexts[3][1].position
    assert inner_add_position != outer_add_position
    assert inner_add_position.offset_resolver is outer_add_position.offset_resolver

    assert inner_add_position.node_range == CodeRange(CodePosition(1, 1), CodePosition(1, 4))
    assert inner_add_position.code_before == '1'
    assert inner_add_position.code_after == '2 + 3\n'
    assert inner_add_position.code_before + ' + ' + inner_add_position.code_after == inner_add_position.source
    alignment_after_first = list(source.alignment_operations)
    assert alignment_after_first

    assert outer_add_position.node_range == CodeRange(CodePosition(1, 5), CodePosition(1, 8))
    assert outer_add_position.code_before == '1 + 2'
    assert outer_add_position.code_after == '3\n'
    assert outer_add_position.code_before + ' + ' + outer_add_position.code_after == outer_add_position.source

    assert source.alignment_operations == alignment_after_first
    assert source.slices == [slice(None, 1), slice(4, None), slice(None, 5), slice(8, None)]


def test_multiple_converters_receive_equal_original_fragments_and_isolated_meta():
    """All converters replacing the same `Add` receive equal original fragments, but each gets a fresh copy of its own meta, so mutations do not leak between contexts or into the source dictionaries."""
    source = 'x = 1 + 2\n'
    changer = Changer(source)
    contexts = []
    subtract_meta = {'name': 'subtract'}
    multiply_meta = {'name': 'multiply'}

    @changer.converter(meta=subtract_meta)
    def subtract(node: Add, context: Context) -> Subtract:
        contexts.append(context)
        assert context.meta is not None
        context.meta['changed'] = True
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.converter(meta=multiply_meta)
    def multiply(node: Add, context: Context) -> Multiply:
        contexts.append(context)
        assert context.meta is not None
        context.meta['changed'] = True
        return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    transformed_sources = [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]

    assert transformed_sources == ['x = 1 - 2\n', 'x = 1 * 2\n']
    assert len(contexts) == 2
    assert [context.meta for context in contexts] == [{'name': 'subtract', 'changed': True}, {'name': 'multiply', 'changed': True}]
    assert contexts[0].meta is not contexts[1].meta
    assert contexts[0].meta is not subtract_meta
    assert contexts[1].meta is not multiply_meta
    assert subtract_meta == {'name': 'subtract'}
    assert multiply_meta == {'name': 'multiply'}
    for context in contexts:
        assert context.position.source == source
        assert context.position.node_range == CodeRange(CodePosition(1, 5), CodePosition(1, 8))
        assert context.position.code_before == 'x = 1'
        assert context.position.code_after == '2\n'
        assert context.position.code_before + ' + ' + context.position.code_after == context.position.source


@pytest.mark.parametrize('registration_kind', ['changer', 'collector'])
def test_bound_filter_added_after_changer_creation_affects_discovery(registration_kind):
    """Bound filters live on the Converter, so adding one after Changer construction affects an already-created Changer, whether the converter was registered directly or through a Collector. A newly created Changer from that Collector also sees it."""
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    if registration_kind == 'changer':
        changer = Changer('1 + 2')
        converter = changer.converter(convert)
    else:
        collector = Collector()
        converter = collector.converter(convert)
        changer = Changer('1 + 2', collector=collector)

    assert len(list(changer.iterate_coordinates())) == 1
    assert changer.converters_by_types[Add][0] is converter

    @converter.filter
    def reject(node: Add) -> bool:  # noqa: ARG001
        return False

    assert [wrapper.function for wrapper in converter.filters] == [reject]
    assert not changer.filters_by_types

    assert list(changer.iterate_coordinates()) == []
    if registration_kind == 'collector':
        latest_changer = Changer('1 + 2', collector=collector)
        assert latest_changer.converters_by_types[Add][0] is converter
        assert [wrapper.function for wrapper in converter.filters] == [reject]
        assert not latest_changer.filters_by_types
        assert list(latest_changer.iterate_coordinates()) == []


def test_changer_snapshots_collector_registrations():
    """Late node-type filters and converters are invisible to an existing Changer because its registration lists are snapshotted at construction; a new Changer sees them. Registered objects themselves are shared."""
    collector = Collector()

    @collector.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    changer = Changer('1 + 2', collector=collector)
    assert changer.converters_by_types[Add][0] is convert
    assert len(list(changer.iterate_coordinates())) == 1

    @collector.filter
    def allow(node: Add) -> bool:  # noqa: ARG001
        return True

    changer_with_filter = Changer('1 + 2', collector=collector)
    assert changer_with_filter.filters_by_types[Add][0] is collector._filters[0]
    assert not changer.filters_by_types

    @collector.filter
    def reject(node: Add) -> bool:  # noqa: ARG001
        return False

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(list(changer_with_filter.iterate_coordinates())) == 1
    latest_changer = Changer('1 + 2', collector=collector)
    assert latest_changer.converters_by_types[Add][0] is convert
    assert [wrapper.function for wrapper in latest_changer.filters_by_types[Add]] == [allow, reject]
    assert list(latest_changer.iterate_coordinates()) == []

    late_collector = Collector()
    changer_before_late_converter = Changer('1 + 2', collector=late_collector)

    @late_collector.converter
    def late_convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    assert list(changer_before_late_converter.iterate_coordinates()) == []

    late_changer = Changer('1 + 2', collector=late_collector)

    assert [late_changer.apply_coordinate(coordinate) for coordinate in late_changer.iterate_coordinates()] == ['1 - 2']


def test_late_converter_on_combined_collector_is_snapshotted_per_changer():
    """
    A Changer built from a combined Collector does not see registrations added
    later, while a newly created Changer does.
    """
    combined = Collector() + Collector()
    old_changer = Changer('1 + 2', collector=combined)

    assert list(old_changer.iterate_coordinates()) == []

    @combined.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    assert list(old_changer.iterate_coordinates()) == []

    new_changer = Changer('1 + 2', collector=combined)
    assert [new_changer.apply_coordinate(coordinate) for coordinate in new_changer.iterate_coordinates()] == ['1 - 2']


def test_late_node_type_and_bound_filters_have_different_visibility():
    """Converter-bound filters live on the shared Converter: a late one affects every Changer referencing it. Node-type filters are snapshotted, so a late one does not enter existing Changers."""
    collector = Collector()

    @collector.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    combined_collector = collector + Collector()
    changer_from_collector = Changer('1 + 2', collector=collector)
    changer_from_combined_collector = Changer('1 + 2', collector=combined_collector)

    assert changer_from_collector.converters_by_types[Add][0] is convert
    assert changer_from_combined_collector.converters_by_types[Add][0] is convert

    def apply_all_coordinates(changer):
        return [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]

    assert apply_all_coordinates(changer_from_collector) == ['1 - 2']
    assert apply_all_coordinates(changer_from_combined_collector) == ['1 - 2']

    @collector.filter
    def reject_node_type(node: Add) -> bool:  # noqa: ARG001
        return False

    assert apply_all_coordinates(changer_from_collector) == ['1 - 2']
    assert apply_all_coordinates(changer_from_combined_collector) == ['1 - 2']
    latest_changer = Changer('1 + 2', collector=collector)
    assert latest_changer.converters_by_types[Add][0] is convert
    assert [wrapper.function for wrapper in latest_changer.filters_by_types[Add]] == [reject_node_type]
    assert list(latest_changer.iterate_coordinates()) == []

    @convert.filter
    def reject_bound(node: Add) -> bool:  # noqa: ARG001
        return False

    assert list(changer_from_collector.iterate_coordinates()) == []
    assert list(changer_from_combined_collector.iterate_coordinates()) == []


@pytest.mark.parametrize('registry_kind', ['changer', 'collector'])
@pytest.mark.parametrize('registration_style', ['bare', 'factory', 'factory_meta', 'direct_meta'])
def test_failed_converter_wrapping_leaves_registries_intact(registry_kind, registration_style):  # noqa: C901
    """
    Every `Changer` and `Collector` converter registration form rejects wrapping
    an existing `Converter`.

    Registries and existing bound filters remain intact, and a valid converter
    can still be registered afterwards.
    """
    changer = Changer('1 + 2')
    collector = Collector()
    @changer.converter
    def changer_converter(node: Add):
        return node

    @changer.filter
    def changer_filter(node: Add) -> bool:  # noqa: ARG001
        return True

    @collector.converter
    def collector_converter(node: Add):
        return node

    @collector.filter
    def collector_filter(node: Add) -> bool:  # noqa: ARG001
        return True

    @changer_converter.filter
    def existing_bound_filter(node: Add) -> bool:  # noqa: ARG001
        return True

    changer_converters_snapshot = {
        node_type: list(converters) for node_type, converters in changer.converters_by_types.items()
    }
    changer_filters_snapshot = {
        node_type: list(filters) for node_type, filters in changer.filters_by_types.items()
    }
    collector_converters_snapshot = list(collector._converters)
    collector_filters_snapshot = list(collector._filters)
    existing_bound_filters = list(changer_converter.filters)

    converter_to_wrap = changer_converter if registry_kind == 'changer' else collector_converter
    register = changer.converter if registry_kind == 'changer' else collector.converter

    if registration_style == 'bare':
        def attempt_registration():
            register(converter_to_wrap)
    elif registration_style == 'factory':
        def attempt_registration():
            register()(converter_to_wrap)
    elif registration_style == 'factory_meta':
        def attempt_registration():
            register(meta={'meta': 1})(converter_to_wrap)
    else:
        def attempt_registration():
            register(converter_to_wrap, meta={'meta': 1})

    with pytest.raises(
        ConverterWrappingError,
        match=match('A converter cannot be wrapped in another converter.'),
    ):
        attempt_registration()

    assert changer.converters_by_types == changer_converters_snapshot
    assert changer.filters_by_types == changer_filters_snapshot
    assert collector._converters == collector_converters_snapshot
    assert collector._filters == collector_filters_snapshot
    assert changer_converter.filters == existing_bound_filters

    def valid_converter_function(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    valid_converter = register(valid_converter_function)
    if registry_kind == 'changer':
        assert valid_converter in changer.converters_by_types[Add]
    else:
        assert valid_converter is collector._converters[-1]
        latest_changer = Changer('1 + 2', collector=collector)
        assert valid_converter in latest_changer.converters_by_types[Add]


def test_late_registrations_on_changer_itself_are_visible():
    """
    Changer registrations added after construction are visible to later traversals.

    Unlike Collector snapshots, a Changer mutates its own registries directly:
    a late converter creates coordinates, and a late rejecting filter suppresses them.
    """
    changer = Changer('1 + 2')

    assert list(changer.iterate_coordinates()) == []

    @changer.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    coordinates = list(changer.iterate_coordinates())
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1 - 2']

    @changer.filter
    def reject(node: Add) -> bool:  # noqa: ARG001
        return False

    assert list(changer.iterate_coordinates()) == []

def test_changer_reuses_traversal_context():
    """A Changer builds one MetadataWrapper and resolver, reusing them for discovery and application."""
    with patch('cstvis.changer.metadata.MetadataWrapper', wraps=metadata.MetadataWrapper) as wrapper_class:
        changer = Changer('1 + 2')

        @changer.converter
        def convert(node: Add):
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

        coordinates = list(changer.iterate_coordinates())
        list(changer.iterate_coordinates())
        changer.apply_coordinate(coordinates[0])
        changer.apply_coordinate(coordinates[0])

    assert wrapper_class.call_count == 1
