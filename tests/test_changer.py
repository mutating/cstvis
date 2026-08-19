from typing import Any, List, Union
from unittest.mock import patch

import pytest
from full_match import match
from libcst import Add, CSTNode, Multiply, SimpleString, Subtract
from libcst.metadata import CodePosition, CodeRange
from metacode import ParsedComment
from sigmatch import SignatureMismatchError

import cstvis.source_offsets as source_offsets_module
from cstvis import Changer, Collector, Context, Coordinate
from cstvis.source_offsets import SourceOffsetResolver


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
def test_just_iterate_add_coordinates(file, with_context, unfold):
    """
    Iterating coordinates for raw source reports only matching Add operators.

    It returns the two Add coordinates in source order, with no file path and the expected class name and start positions.
    """
    changer = Changer(file)

    if with_context:
        @unfold(changer.converter)
        def name_changer(node: Add, context: Context):  # noqa: ARG001
            return True
    else:
        @unfold(changer.converter)
        def name_changer(node: Add):  # noqa: ARG001
            return True

    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 2

    assert coordinates[0].file is None
    assert coordinates[0].class_name == 'Add'
    assert coordinates[0].start_line == 3
    assert coordinates[0].start_column == 7
    assert coordinates[0].end_line == 3
    assert coordinates[0].end_column == 8

    assert coordinates[1].file is None
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
    def name_changer(node: Add):
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
    Applying one Changer-registered converter rewrites the single matching operation in the returned full source.

    Using the only Add coordinate, the plus becomes a minus and surrounding whitespace is preserved across callback signatures and decorator forms.
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

    results = []

    for coordinate in changer.iterate_coordinates():
        results.append(changer.apply_coordinate(coordinate))

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
def test_apply_two_changes_at_same_line(file, with_context, unfold):
    """
    Applying a selected change to one of several same-line additions changes only that operator.

    Coordinates distinguish additions on the same line, so each candidate is applied independently from the original source while preserving the other additions and spacing.
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

    results = []

    for coordinate in changer.iterate_coordinates():
        results.append(changer.apply_coordinate(coordinate))

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
def test_to_different_changers_to_same_line(file, with_context, unfold):
    """
    Converters targeting different operator types on the same source line remain independently addressable.

    Applying the Add coordinate changes only the plus, and applying the Subtract coordinate changes only the minus; the neighboring operator is left unchanged in each result.
    """
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

    results = []

    for coordinate in changer.iterate_coordinates():
        results.append(changer.apply_coordinate(coordinate))

    assert len(results) == 2
    assert results == [
        'a = 5 - 6- 7',
        'a = 5 + 6+ 7',
    ]


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5 + 6- 7',
        ],),
    ],
)
def test_changing_function_with_wrong_number_of_parameters(file, unfold):
    """
    Reject converter callbacks that cannot be called with a node or with a node and context.

    Zero-argument and three-argument converters are rejected during registration, with the error type and message treated as part of the contract.
    """
    changer = Changer(file)

    with pytest.raises(SignatureMismatchError, match=match('A function that takes a CST node and a context is expected.')):
        @unfold(changer.converter)
        def changing_function_1(node: Add, context: Context, something_else: str):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

    with pytest.raises(SignatureMismatchError, match=match('A function that takes a CST node and a context is expected.')):
        @unfold(changer.converter)
        def changing_function_2():
            ...


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

    A missing comment is None. Otherwise, the value is the raw comment text after removing only the leading #, preserving whitespace after it and later # characters.
    """
    changer = Changer(file)

    comments_containers = []

    @unfold(changer.converter)
    def change_something(node: Add, context: Context):
        comments_containers.append(context.comment)
        return node

    for coordinate in changer.iterate_coordinates():
        changer.apply_coordinate(coordinate)

    assert comments_containers[0] == expected_comment


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

    metacodes_containers = []

    @unfold(changer.converter)
    def change_something(node: Add, context: Context):
        metacodes_containers.append(context.get_metacodes('key'))
        return node

    for coordinate in changer.iterate_coordinates():
        changer.apply_coordinate(coordinate)

    assert metacodes_containers[0] == expected_metacodes


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5 + 6- 7',
        ],),
    ],
)
def test_filter_any_on(file, with_context, unfold):
    """
    An Any-annotated filter that returns True permits matching Changer conversions.

    The test checks that the catch-all filter allows the single Add-to-Subtract change to be discovered and applied for both node-only and context-aware callables, through both decorator styles.
    """
    changer = Changer(file)

    if with_context:
        @unfold(changer.converter)
        def change_something(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def filter_something(node: Any, context: Context) -> bool:  # noqa: ARG001
            return True

    else:
        @unfold(changer.converter)
        def change_something(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def filter_something(node: Any) -> bool:  # noqa: ARG001
            return True

    results = []

    for coordinate in changer.iterate_coordinates():
        results.append(changer.apply_coordinate(coordinate))

    assert len(results) == 1
    assert results[0] == file.replace('+', '-')


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5 + 6- 7',
        ],),
    ],
)
def test_filter_any_off(file, with_context, unfold):
    """
    A filter annotated with Any rejects an otherwise eligible change when it returns False.

    This checks that the broad filter blocks an Add converter that would replace a plus operator, leaving no results across the supported callback signatures and decorator forms.
    """
    changer = Changer(file)

    if with_context:
        @unfold(changer.converter)
        def change_something(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def filter_something(node: Any, context: Context) -> bool:  # noqa: ARG001
            return False

    else:
        @unfold(changer.converter)
        def change_something(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def filter_something(node: Any) -> bool:  # noqa: ARG001
            return False

    results = []

    for coordinate in changer.iterate_coordinates():
        results.append(changer.apply_coordinate(coordinate))

    assert len(results) == 0


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5 + 6- 7',
        ],),
    ],
)
def test_filter_cstnode_on(file, with_context, unfold):
    """
    A truthy broad CSTNode filter allows a concrete Add conversion to remain available.

    The test uses one plus expression and an Add converter that changes it to subtraction, then checks that one coordinate is emitted and applying it changes only that plus operator. The behavior is covered for callbacks with or without context and for both decorator forms.
    """
    changer = Changer(file)

    if with_context:
        @unfold(changer.converter)
        def change_something(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def filter_something(node: CSTNode, context: Context) -> bool:  # noqa: ARG001
            return True

    else:
        @unfold(changer.converter)
        def change_something(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def filter_something(node: CSTNode) -> bool:  # noqa: ARG001
            return True

    results = []

    for coordinate in changer.iterate_coordinates():
        results.append(changer.apply_coordinate(coordinate))

    assert len(results) == 1
    assert results[0] == file.replace('+', '-')


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5 + 6- 7',
        ],),
    ],
)
def test_filter_cstnode_off(file, with_context, unfold):
    """
    A broad CSTNode filter returning False suppresses otherwise matching converter changes.

    Even when a converter targets a specific Add node, the rejecting CSTNode filter applies to that candidate, so no changes are emitted. The same behavior is expected for callbacks with or without Context and for both supported decorator registration styles.
    """
    changer = Changer(file)

    if with_context:
        @unfold(changer.converter)
        def change_something(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def filter_something(node: CSTNode, context: Context) -> bool:  # noqa: ARG001
            return False

    else:
        @unfold(changer.converter)
        def change_something(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def filter_something(node: CSTNode) -> bool:  # noqa: ARG001
            return False

    results = []

    for coordinate in changer.iterate_coordinates():
        results.append(changer.apply_coordinate(coordinate))

    assert len(results) == 0


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5 + 6- 7',
        ],),
    ],
)
def test_filter_node_on(file, with_context, unfold):
    """
    An Add-annotated filter returning True permits the Add conversion.

    The single Add-to-Subtract change is emitted and applied across node-only/context-aware callbacks and both decorator forms, leaving the existing Subtract operator unchanged.
    """
    changer = Changer(file)

    if with_context:
        @unfold(changer.converter)
        def change_something(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def filter_something(node: Add, context: Context) -> bool:  # noqa: ARG001
            return True

    else:
        @unfold(changer.converter)
        def change_something(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def filter_something(node: Add) -> bool:  # noqa: ARG001
            return True

    results = []

    for coordinate in changer.iterate_coordinates():
        results.append(changer.apply_coordinate(coordinate))

    assert len(results) == 1
    assert results[0] == file.replace('+', '-')


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5 + 6- 7',
        ],),
    ],
)
def test_filter_node_off(file, with_context, unfold):
    """
    Rejects an Add conversion when a matching Add filter returns false.

    The otherwise valid plus-to-minus change produces no results because the concrete node filter vetoes the candidate before any coordinate is applied. The expectation holds for both node-only and context-aware callbacks, and for both decorator invocation styles.
    """
    changer = Changer(file)

    if with_context:
        @unfold(changer.converter)
        def change_something(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def filter_something(node: Add, context: Context) -> bool:  # noqa: ARG001
            return False

    else:
        @unfold(changer.converter)
        def change_something(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def filter_something(node: Add) -> bool:  # noqa: ARG001
            return False

    results = []

    for coordinate in changer.iterate_coordinates():
        results.append(changer.apply_coordinate(coordinate))

    assert len(results) == 0


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5 + 6- 7',
        ],),
    ],
)
def test_filter_other_node_on(file, with_context, unfold):
    """
    A true filter for a different concrete node type coexists with an Add conversion.

    The source contains one Add and one existing Subtract, but only the Add converter yields a change. Applying that change replaces the plus with a minus while leaving the existing minus intact, across context-aware and context-free callbacks and both decorator styles.
    """
    changer = Changer(file)

    if with_context:
        @unfold(changer.converter)
        def change_something(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def filter_something(node: Subtract, context: Context) -> bool:  # noqa: ARG001
            return True

    else:
        @unfold(changer.converter)
        def change_something(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def filter_something(node: Subtract) -> bool:  # noqa: ARG001
            return True

    results = []

    for coordinate in changer.iterate_coordinates():
        results.append(changer.apply_coordinate(coordinate))

    assert len(results) == 1
    assert results[0] == file.replace('+', '-')


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5 + 6- 7',
        ],),
    ],
)
def test_filter_other_node_off(file, with_context, unfold):
    """
    A false filter for a different concrete node type does not block an eligible conversion.

    An Add converter still yields one change even when a Subtract filter returns False, because that filter is unrelated to the Add candidate. Applying the change rewrites only the plus operator to a minus, and the behavior is the same with or without Context and for both decorator invocation styles.
    """
    changer = Changer(file)

    if with_context:
        @unfold(changer.converter)
        def change_something(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def filter_something(node: Subtract, context: Context) -> bool:  # noqa: ARG001
            return False

    else:
        @unfold(changer.converter)
        def change_something(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.filter)
        def filter_something(node: Subtract) -> bool:  # noqa: ARG001
            return False

    results = []

    for coordinate in changer.iterate_coordinates():
        results.append(changer.apply_coordinate(coordinate))

    assert len(results) == 1
    assert results[0] == file.replace('+', '-')


def test_converter_with_no_annotation(with_context, unfold):
    """
    Accept an unannotated converter parameter as a catch-all for CST nodes.

    The identity converter should produce applicable coordinates for the minimal source and work both with and without context, regardless of decorator invocation form.
    """
    changer = Changer('1')

    if with_context:
        @unfold(changer.converter)
        def converter_func(node, context):  # noqa: ARG001
            return node
    else:
        @unfold(changer.converter)
        def converter_func(node):
            return node

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]


def test_converter_with_any_annotation(with_context, unfold):
    """
    Accepts typing.Any as a universal converter annotation.

    An Any-annotated identity converter for source '1' should discover at least one coordinate and apply successfully across supported converter signatures and decorator forms.
    """
    changer = Changer('1')

    if with_context:
        @unfold(changer.converter)
        def converter_func(node: Any, context):  # noqa: ARG001
            return node
    else:
        @unfold(changer.converter)
        def converter_func(node: Any):
            return node

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]


def test_converter_with_cstnode_annotation_restriction(with_context, unfold):
    """
    Accepts libcst.CSTNode as a broad converter annotation.

    The converter should apply to at least one coordinate for a minimal source, whether it accepts only the node or also accepts context, and whether the decorator is used bare or called.
    """
    changer = Changer('1')

    if with_context:
        @unfold(changer.converter)
        def converter_func(node: CSTNode, context):  # noqa: ARG001
            return node
    else:
        @unfold(changer.converter)
        def converter_func(node: CSTNode):
            return node

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]


def test_convert_str(with_context, unfold):
    """
    Dispatches the builtin str annotation shortcut to string literal CST nodes.

    Verifies that a converter registered for source containing one string literal is called exactly once and receives a libcst.SimpleString node, across the supported converter signature and decorator forms.
    """
    changer = Changer('a = "kek"')

    nodes = []

    if with_context:
        @unfold(changer.converter)
        def converter_func(node: str, context: Context):  # noqa: ARG001
            nodes.append(node)
            return node
    else:
        @unfold(changer.converter)
        def converter_func(node: str):
            nodes.append(node)
            return node

    for coordinate in changer.iterate_coordinates():
        changer.apply_coordinate(coordinate)

    assert len(nodes) == 1
    assert isinstance(nodes[0], SimpleString)


def test_convert_float(with_context, unfold):
    """
    Converts a float literal selected by the built-in `float` shortcut.

    A `float` converter finds the single `5.0` in `a = 5.0` and returns `a = 6.0`; a prior discarded application must not affect the later result. This holds with or without context and for both decorator forms.
    """
    changer = Changer('a = 5.0')

    if with_context:
        @unfold(changer.converter)
        def converter_func(node: float, context: Context):  # noqa: ARG001
            return node.with_changes(value=repr(node.evaluated_value + 1))  # type: ignore[attr-defined]
    else:
        @unfold(changer.converter)
        def converter_func(node: float):
            return node.with_changes(value=repr(node.evaluated_value + 1))  # type: ignore[attr-defined]

    for coordinate in changer.iterate_coordinates():
        changer.apply_coordinate(coordinate)

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == ['a = 6.0']


def test_filter_with_wrong_number_of_parameters(unfold):
    """
    Reject filters with unsupported callback arity.

    Covers both direct and called decorator forms, asserting that zero-argument and three-argument filter callbacks fail registration with SignatureMismatchError.
    """
    changer = Changer('a = 5')

    with pytest.raises(SignatureMismatchError, match=match('A function that takes a CST node and a context is expected.')):
        @unfold(changer.filter)
        def filter_func(node: Add, context: Context, extra_param: str):  # noqa: ARG001
            return True

    with pytest.raises(SignatureMismatchError, match=match('A function that takes a CST node and a context is expected.')):
        @unfold(changer.filter)
        def filter_func():
            return True


def test_filter_with_invalid_annotation(unfold):
    """
    Rejects filters whose node parameter is annotated with a non-CSTNode class.

    The callback otherwise has a valid node-and-context signature, so either filter decorator form should raise TypeError for the invalid annotation instead of treating it as a signature mismatch.
    """
    changer = Changer('a = 5')

    class SomeClass:
        pass

    with pytest.raises(TypeError, match=match('The type annotation for the first argument of the function must be descended from the libcst.CSTNode class.')):
        @unfold(changer.filter)
        def filter_func(node: SomeClass, context: Context):  # noqa: ARG001
            return True


def test_two_converters_for_same_node(with_context, unfold):
    """
    Multiple converters for the same Add node produce separate choices.

    For `5 + 5`, the two Add converters yield independent results, `5 - 5` and `5 * 5`, across node-only/context-aware callbacks and both decorator forms.
    """
    changer = Changer('5 + 5')

    if with_context:
        @unfold(changer.converter)
        def converter1(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.converter)
        def converter2(node: Add, context: Context):  # noqa: ARG001
            return Multiply(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

    else:
        @unfold(changer.converter)
        def converter1(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(changer.converter)
        def converter2(node: Add):
            return Multiply(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

    assert set(changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()) == {'5 - 5', '5 * 5'}


def test_use_collector_for_converter(with_context, unfold):
    """
    Collected converters participate in Changer coordinate discovery and application.

    A converter registered on a Collector and supplied to Changer should rewrite the single Add operator in the source to Subtract, for both supported converter signatures and both Collector.converter decorator forms.
    """
    collector = Collector()

    if with_context:
        @unfold(collector.converter)
        def some_converter(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )
    else:
        @unfold(collector.converter)
        def some_converter(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

    changer = Changer('a = 5 + 5', collector=collector)

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == ['a = 5 - 5']


def test_use_collector_for_converter_and_filter(with_context, unfold):
    """
    Collected filters gate collected converters.

    With the filter returning False, the Collector-backed Changer emits no changes; after the filter state flips to True, the same source yields `a = 5 - 5` across callback signatures and decorator forms.
    """
    collector = Collector()

    filters_value = False

    if with_context:
        @unfold(collector.converter)
        def some_converter(node: Add, context: Context):  # noqa: ARG001
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(collector.filter)
        def some_filter(node: Add, context: Context):  # noqa: ARG001
            return filters_value

    else:
        @unfold(collector.converter)
        def some_converter(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

        @unfold(collector.filter)
        def some_filter(node: Add):  # noqa: ARG001
            return filters_value

    changer = Changer('a = 5 + 5', collector=collector)

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == []

    filters_value = True

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == ['a = 5 - 5']


def test_union_with_csts(with_context, unfold):
    """
    Union[Add, Subtract] converters produce one rewrite per matching operator.

    For `5 - 5 + 5`, coordinates are emitted in source order, and each application replaces only the selected Add or Subtract operator with Multiply across callback signatures.
    """
    changer = Changer('5 - 5 + 5')

    if with_context:
        @unfold(changer.converter)
        def some_converter(node: Union[Add, Subtract], context: Context):  # noqa: ARG001
            return Multiply(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )
    else:
        @unfold(changer.converter)
        def some_converter(node: Union[Add, Subtract]):
            return Multiply(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == ['5 * 5 + 5', '5 - 5 * 5']


def test_union_with_union_with_csts(with_context, unfold):
    """
    Nested Union annotations expand to the matching operator types present in the source.

    For `Union[Add, Union[Multiply, Subtract]]` on `5 - 5 + 5`, only Add and Subtract coordinates are emitted, yielding the two single-operator rewrites.
    """
    changer = Changer('5 - 5 + 5')

    if with_context:
        @unfold(changer.converter)
        def some_converter(node: Union[Add, Union[Multiply, Subtract]], context: Context):  # noqa: ARG001
            return Multiply(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )
    else:
        @unfold(changer.converter)
        def some_converter(node: Union[Add, Union[Multiply, Subtract]]):
            return Multiply(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

    assert set(changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()) == {'5 * 5 + 5', '5 - 5 * 5'}


def test_convert_plus_one(with_context, unfold):
    """
    Treat converters annotated with int as applying to integer literals.

    For `5 - 5 + 5`, each integer occurrence can be changed independently to its plus-one value, across node-only and context-aware converter signatures and both decorator call styles.
    """
    changer = Changer('5 - 5 + 5')

    if with_context:
        @unfold(changer.converter)
        def convert_ints(node: int, context):  # noqa: ARG001
            return node.with_changes(value=repr(node.evaluated_value + 1))  # type: ignore[attr-defined]
    else:
        @unfold(changer.converter)
        def convert_ints(node: int):
            return node.with_changes(value=repr(node.evaluated_value + 1))  # type: ignore[attr-defined]

    assert set(changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()) == {'6 - 5 + 5', '5 - 6 + 5', '5 - 5 + 6'}


def test_converter_for_any(with_context, unfold):
    """
    An Any-annotated converter is considered for many CST nodes.

    Applying every coordinate in `Changer('5 - 5 + 5')` invokes the identity converter more than ten times across node-only/context-aware callbacks and both decorator forms.
    """
    changer = Changer('5 - 5 + 5')

    nodes = []

    if with_context:
        @unfold(changer.converter)
        def do_something(node: Any, context):  # noqa: ARG001
            nodes.append(nodes)
            return node
    else:
        @unfold(changer.converter)
        def do_something(node: Any):
            nodes.append(nodes)
            return node

    [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]
    assert len(nodes) > 10


def test_if_node_is_not_exist_nothing_changed(with_context, unfold):
    """
    Converters targeting float literals produce no changes when the source has no float literals.

    A float-annotated converter should produce no applied changes for `5 - 5 + 5`, whose numeric literals are all integers, across supported context and decorator variants.
    """
    changer = Changer('5 - 5 + 5')

    if with_context:
        @unfold(changer.converter)
        def do_something(node: float, context):  # noqa: ARG001
            return node
    else:
        @unfold(changer.converter)
        def do_something(node: float):
            return node

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == []


def test_get_function_id_from_itself(unfold):
    """
    Registered converter and filter wrappers report deterministic function IDs.

    The IDs include the wrapped callable's module, function name, and first source line for both bare-decorator and called-decorator registration forms.
    """
    changer = Changer('5 - 5 + 5')

    @unfold(changer.converter)
    def do_something(node: float, context):  # noqa: ARG001
        return node

    @unfold(changer.filter)
    def filter_something(node: float, context):  # noqa: ARG001
        return False

    converter = list(changer.converters_by_types.values())[0][0]  # noqa: RUF015
    filter = list(changer.filters_by_types.values())[0][0]  # noqa: RUF015, A001

    assert converter.get_function_id() == 'tests.test_changer:do_something:1114'
    assert filter.get_function_id() == 'tests.test_changer:filter_something:1118'


def test_wrong_converter_and_wrong_filter(unfold):
    """
    Reject converter and filter callbacks with invalid arity.

    Both decorators should raise SignatureMismatchError when registering callbacks that take no parameters or three parameters, whether used directly or as called decorator factories.
    """
    changer = Changer('5 - 5 + 5')

    with pytest.raises(SignatureMismatchError, match=match('A function that takes a CST node and a context is expected.')):
        @unfold(changer.converter)
        def do_something_1():
            ...

    with pytest.raises(SignatureMismatchError, match=match('A function that takes a CST node and a context is expected.')):
        @unfold(changer.converter)
        def do_something_2(a, b, c):
            ...

    with pytest.raises(SignatureMismatchError, match=match('A function that takes a CST node and a context is expected.')):
        @unfold(changer.filter)
        def filter_something_1():
            return False

    with pytest.raises(SignatureMismatchError, match=match('A function that takes a CST node and a context is expected.')):
        @unfold(changer.filter)
        def filter_something_2(a, b, c):  # noqa: ARG001
            return False


def test_pass_meta_dict_to_converter():
    """
    Direct Changer converters receive copied decorator metadata in their Context.

    Applying the Add coordinate from `5 - 5 + 5` triggers a two-argument converter and verifies that `context.meta` equals the supplied meta dictionary while remaining a distinct top-level dict.
    """
    bread_crumbs = []
    changer = Changer('5 - 5 + 5')
    meta = {'key': 123}

    @changer.converter(meta=meta)
    def some_converter(node: Add, context: Context):
        bread_crumbs.append(context.meta)
        return Multiply(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]

    assert bread_crumbs == [meta]
    assert bread_crumbs[0] is not meta


def test_pass_meta_dict_to_filter(unfold):
    """
    Passing a metadata dict to a Changer filter exposes an equal but distinct copy through Context.meta.

    The filter is evaluated while discovering a matching Add candidate, so the test focuses on filter metadata delivery rather than source transformation.
    """
    bread_crumbs = []
    changer = Changer('5 - 5 + 5')
    meta = {'key': 123}

    @unfold(changer.converter)
    def some_converter(node: Add):
        return Multiply(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    @changer.filter(meta=meta)
    def filter_something(node: Add, context: Context):  # noqa: ARG001
        bread_crumbs.append(context.meta)
        return False

    [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]

    assert bread_crumbs == [meta]
    assert bread_crumbs[0] is not meta


def test_pass_meta_dict_to_converter_throw_collector():
    """
    Collector-registered converter meta reaches the converter context as an equal copy.

    When a Changer built from the Collector applies the Add converter, the converter records one Context.meta value equal to {'key': 123} and distinct from the original decorator dict.
    """
    bread_crumbs = []
    collector = Collector()
    meta = {'key': 123}

    @collector.converter(meta=meta)
    def some_converter(node: Add, context: Context):
        bread_crumbs.append(context.meta)
        return Multiply(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    changer = Changer('5 - 5 + 5', collector=collector)
    [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]

    assert bread_crumbs == [meta]
    assert bread_crumbs[0] is not meta


def test_pass_meta_dict_to_filter_throw_collector(unfold):
    """
    Collector-registered filter metadata is copied into Context during coordinate discovery.

    A Changer built from the Collector has a collected Add converter only to make the Add node eligible. The collected Add filter returns False, and the assertions focus on context.meta matching the filter decorator's dict without aliasing it.
    """
    bread_crumbs = []
    collector = Collector()
    meta = {'key': 123}

    @unfold(collector.converter)
    def some_converter(node: Add):
        return Multiply(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    @collector.filter(meta=meta)
    def filter_something(node: Add, context: Context):  # noqa: ARG001
        bread_crumbs.append(context.meta)
        return False

    changer = Changer('5 - 5 + 5', collector=collector)
    [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]

    assert bread_crumbs == [meta]
    assert bread_crumbs[0] is not meta


def test_it_passes_2_arguments_if_possible(unfold):
    """
    Passes Context as the second argument when a converter can accept it.

    This covers the ambiguous valid case where the converter's second positional parameter is optional, defaults to None, and is not annotated as Context. The converter should receive a real Context object instead of falling back to its default.
    """
    changer = Changer('5 + 4')

    contexts = []

    @unfold(changer.converter)
    def change_something(node: Add, context=None):
        contexts.append(context)
        return node

    for coordinate in changer.iterate_coordinates():
        changer.apply_coordinate(coordinate)

    assert len(contexts) == 1
    assert isinstance(contexts[0], Context)


def test_filter_context_exposes_whitespace_inclusive_fragments():
    """
    Context.position exposes an Add's whitespace-inclusive range, offsets, and fragments to filters.

    The ordinary coordinate remains limited to the '+' token.
    """
    source = 'left = 1  +\t2 # tail\r\nright = 3\n'
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
    assert context.position.coordinate == Coordinate(None, 'Add', 1, 10, 1, 11)
    assert context.position.node_range == CodeRange(CodePosition(1, 8), CodePosition(1, 12))
    assert context.position.start_offset == 8
    assert context.position.end_offset == 12
    assert context.position.code_before == 'left = 1'
    assert context.position.code_after == '2 # tail\r\nright = 3\n'
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


def test_converter_context_exposes_original_fragments():
    """
    A converter's Context.position retains the original Add's range, offsets, and fragments after replacement.
    """
    source = 'left = 1  +\t2 # tail\r\nright = 3\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add, context: Context) -> Subtract:
        contexts.append(context)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    coordinate = next(changer.iterate_coordinates())
    transformed_source = changer.apply_coordinate(coordinate)

    assert transformed_source == 'left = 1  -\t2 # tail\r\nright = 3\n'
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.coordinate == Coordinate(None, 'Add', 1, 10, 1, 11)
    assert context.position.node_range == CodeRange(CodePosition(1, 8), CodePosition(1, 12))
    assert context.position.start_offset == 8
    assert context.position.end_offset == 12
    assert context.position.code_before == 'left = 1'
    assert context.position.code_after == '2 # tail\r\nright = 3\n'
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


@pytest.mark.parametrize('callback_kind', ['filter', 'converter'])
def test_context_pipeline_does_not_materialize_unread_fragments(callback_kind):  # noqa: C901
    """
    Coordinate-only filter and converter callbacks neither resolve fragment offsets nor slice the source.
    """
    class TrackingString(str):
        __slots__ = ('alignment_operations', 'slices')
        alignment_operations: List[str]
        slices: List[slice]

        def __new__(cls, value: str):  # type: ignore[no-untyped-def]
            instance = super().__new__(cls, value)
            instance.alignment_operations = []
            instance.slices = []
            return instance

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

    source = TrackingString('x = 1 + 2\n')
    changer = Changer(source)
    source.alignment_operations.clear()
    source.slices.clear()
    observed_coordinates = []

    if callback_kind == 'filter':
        @changer.converter
        def convert(node: Add) -> Add:
            return node

        @changer.filter
        def inspect_coordinate(node: Add, context: Context) -> bool:  # noqa: ARG001
            observed_coordinates.append(context.position.coordinate)
            return False
    else:
        @changer.converter
        def convert(node: Add, context: Context) -> Subtract:
            observed_coordinates.append(context.position.coordinate)
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    alignment_ranges = []
    resolve_offsets = SourceOffsetResolver.__call__

    def track_alignment(resolver, node_range):  # type: ignore[no-untyped-def]
        alignment_ranges.append(node_range)
        return resolve_offsets(resolver, node_range)

    with patch.object(SourceOffsetResolver, '__call__', track_alignment):
        coordinates = list(changer.iterate_coordinates())
        if callback_kind == 'filter':
            assert coordinates == []
        else:
            assert len(coordinates) == 1
            assert changer.apply_coordinate(coordinates[0]) == 'x = 1 - 2\n'

    assert observed_coordinates == [Coordinate(None, 'Add', 1, 6, 1, 7)]
    assert alignment_ranges == []
    assert source.alignment_operations == []
    assert source.slices == []


@pytest.mark.parametrize('callback_kind', ['filter', 'converter'])
def test_node_only_callbacks_do_not_materialize_context_fragments(callback_kind):
    """
    Node-only filter and converter callbacks neither resolve fragment offsets nor slice the source.
    """
    class TrackingString(str):
        __slots__ = ('slices',)
        slices: List[slice]

        def __new__(cls, value: str):  # type: ignore[no-untyped-def]
            instance = super().__new__(cls, value)
            instance.slices = []
            return instance

        def __getitem__(self, key):  # type: ignore[no-untyped-def]
            if isinstance(key, slice):
                self.slices.append(key)
            return super().__getitem__(key)

    source = TrackingString('x = 1 + 2\n')
    changer = Changer(source)
    source.slices.clear()
    converter_inputs = []
    filter_inputs = []
    alignment_ranges = []

    @changer.converter
    def convert(node: Add) -> Subtract:
        converter_inputs.append(node)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    if callback_kind == 'filter':
        @changer.filter
        def reject(node: Add) -> bool:
            filter_inputs.append(node)
            return False

    resolve_offsets = SourceOffsetResolver.__call__

    def track_alignment(resolver, node_range):  # type: ignore[no-untyped-def]
        alignment_ranges.append(node_range)
        return resolve_offsets(resolver, node_range)

    with patch.object(SourceOffsetResolver, '__call__', track_alignment):
        coordinates = list(changer.iterate_coordinates())
        if callback_kind == 'converter':
            assert changer.apply_coordinate(coordinates[0]) == 'x = 1 - 2\n'

    if callback_kind == 'filter':
        assert coordinates == []
        assert len(filter_inputs) == 1
        assert isinstance(filter_inputs[0], Add)
        assert converter_inputs == []
    else:
        assert len(coordinates) == 1
        assert len(converter_inputs) == 1
        assert isinstance(converter_inputs[0], Add)
    assert alignment_ranges == []
    assert source.slices == []


@pytest.mark.parametrize('callback_kind', ['filter', 'converter'])
@pytest.mark.parametrize('fragment_name', ['code_before', 'code_after'])
def test_context_pipeline_materializes_only_requested_fragment(callback_kind, fragment_name):
    """
    Filter and converter paths resolve and slice only the requested fragment once despite repeated reads.
    """
    class TrackingString(str):
        __slots__ = ('slices',)
        slices: List[slice]

        def __new__(cls, value: str):  # type: ignore[no-untyped-def]
            instance = super().__new__(cls, value)
            instance.slices = []
            return instance

        def __getitem__(self, key):  # type: ignore[no-untyped-def]
            if isinstance(key, slice):
                self.slices.append(key)
            return super().__getitem__(key)

    source = TrackingString('x = 1 + 2\n')
    changer = Changer(source)
    fragment_values = []
    contexts = []
    source.slices.clear()

    if callback_kind == 'filter':
        @changer.converter
        def convert(node: Add) -> Add:
            return node

        @changer.filter
        def read_fragment(node: Add, context: Context) -> bool:  # noqa: ARG001
            contexts.append(context)
            fragment_values.extend([getattr(context.position, fragment_name), getattr(context.position, fragment_name)])
            return True
    else:
        @changer.converter
        def convert(node: Add, context: Context) -> Add:
            contexts.append(context)
            fragment_values.extend([getattr(context.position, fragment_name), getattr(context.position, fragment_name)])
            return node

    alignment_ranges = []
    resolve_offsets = SourceOffsetResolver.__call__

    def track_alignment(resolver, node_range):  # type: ignore[no-untyped-def]
        alignment_ranges.append(node_range)
        return resolve_offsets(resolver, node_range)

    with patch.object(SourceOffsetResolver, '__call__', track_alignment):
        coordinates = list(changer.iterate_coordinates())
        if callback_kind == 'converter':
            changer.apply_coordinate(coordinates[0])

    expected_fragment = 'x = 1' if fragment_name == 'code_before' else '2\n'
    expected_slice = slice(None, 5) if fragment_name == 'code_before' else slice(8, None)
    other_fragment_name = 'code_after' if fragment_name == 'code_before' else 'code_before'
    assert len(contexts) == 1
    assert fragment_name in contexts[0].position.__dict__
    assert other_fragment_name not in contexts[0].position.__dict__
    assert fragment_values == [expected_fragment, expected_fragment]
    assert alignment_ranges == [CodeRange(CodePosition(1, 5), CodePosition(1, 8))]
    assert source.slices == [expected_slice]


@pytest.mark.parametrize('callback_kind', ['filter', 'converter'])
def test_context_fragments_can_be_read_after_traversal(callback_kind):
    """
    A captured Context.position can resolve unread fragments after traversal and reconstruct the source.
    """
    class TrackingString(str):
        __slots__ = ('slices',)
        slices: List[slice]

        def __new__(cls, value: str):  # type: ignore[no-untyped-def]
            instance = super().__new__(cls, value)
            instance.slices = []
            return instance

        def __getitem__(self, key):  # type: ignore[no-untyped-def]
            if isinstance(key, slice):
                self.slices.append(key)
            return super().__getitem__(key)

    source = TrackingString('x = 1 + 2\n')
    changer = Changer(source)
    contexts = []
    source.slices.clear()

    if callback_kind == 'filter':
        @changer.converter
        def convert(node: Add) -> Add:
            return node

        @changer.filter
        def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
            contexts.append(context)
            return True
    else:
        @changer.converter
        def convert(node: Add, context: Context) -> Add:
            contexts.append(context)
            return node

    coordinates = list(changer.iterate_coordinates())
    if callback_kind == 'converter':
        changer.apply_coordinate(coordinates[0])

    assert source.slices == []
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 5), CodePosition(1, 8))
    assert context.position.code_before == 'x = 1'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + ' + ' + context.position.code_after == context.position.source


def test_multiple_filters_receive_contexts_with_isolated_meta():
    """
    Filter Context copies share one SourcePosition while their mutable meta copies remain isolated.
    """
    source = 'x = 1 + 2\n'
    changer = Changer(source)
    first_filter_meta = {'filter': 1}
    second_filter_meta = {'filter': 2}
    contexts = []

    @changer.converter
    def convert(node: Add) -> Add:
        return node

    @changer.filter(meta=first_filter_meta)
    def first_filter(node: Add, context: Context) -> bool:  # noqa: ARG001
        assert context.meta is not None
        context.meta['changed'] = True
        contexts.append(context)
        return True

    @changer.filter(meta=second_filter_meta)
    def second_filter(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 2
    assert contexts[0].position is contexts[1].position
    assert contexts[0].meta == {'filter': 1, 'changed': True}
    assert contexts[1].meta == {'filter': 2}
    assert first_filter_meta == {'filter': 1}
    assert second_filter_meta == {'filter': 2}
    with patch('cstvis.source_offsets._SourceOffsetCodegenState', wraps=source_offsets_module._SourceOffsetCodegenState) as create_state:
        for context in contexts:
            assert context.position.node_range == CodeRange(CodePosition(1, 5), CodePosition(1, 8))
            assert context.position.code_before == 'x = 1'
            assert context.position.code_after == '2\n'
            assert context.position.code_before + ' + ' + context.position.code_after == context.position.source
        assert create_state.call_count == 1


def test_multiple_converters_receive_equal_original_fragments():
    """
    Different Add replacements receive equal original fragments and produce distinct transformed sources.
    """
    source = 'x = 1 + 2\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def subtract(node: Add, context: Context) -> Subtract:
        contexts.append(context)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.converter
    def multiply(node: Add, context: Context) -> Multiply:
        contexts.append(context)
        return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    transformed_sources = {changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()}

    assert transformed_sources == {'x = 1 - 2\n', 'x = 1 * 2\n'}
    assert len(contexts) == 2
    for context in contexts:
        assert context.position.source == source
        assert context.position.node_range == CodeRange(CodePosition(1, 5), CodePosition(1, 8))
        assert context.position.code_before == 'x = 1'
        assert context.position.code_after == '2\n'
        assert context.position.code_before + ' + ' + context.position.code_after == context.position.source
