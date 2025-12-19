# ruff: noqa: ARG001

from typing import Any, Union

import pytest
from full_match import match
from libcst import Add, CSTNode, Multiply, SimpleString, Subtract
from metacode import ParsedComment

from cstvis import Changer, Collector, Context


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
def test_just_iterate_add_coordinates(file):
    changer = Changer(file)

    @changer.converter
    def name_changer(node: Add, context: Context):
        return True

    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 2

    assert coordinates[0].file is None
    assert coordinates[0].class_name == 'Add'
    assert coordinates[0].start_line == 3
    assert coordinates[0].start_column == 7
    assert coordinates[0].start_line == 3
    assert coordinates[0].start_column == 7

    assert coordinates[1].file is None
    assert coordinates[1].class_name == 'Add'
    assert coordinates[1].start_line == 6
    assert coordinates[1].start_column == 6
    assert coordinates[1].start_line == 6
    assert coordinates[1].start_column == 6


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
def test_apply_one_change(file):
    changer = Changer(file)

    @changer.converter
    def change_add_to_sub(node: Add, context: Context):
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
def test_apply_two_changes_at_same_line(file):
    changer = Changer(file)

    @changer.converter
    def change_add_to_sub(node: Add, context: Context):
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
def test_to_different_changers_to_same_line(file):
    changer = Changer(file)

    @changer.converter
    def change_add_to_sub(node: Add, context: Context):
        return Subtract(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    @changer.converter
    def change_sub_to_add(node: Subtract, context: Context):
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
def test_changing_function_with_wrong_number_of_parameters(file):
    changer = Changer(file)

    with pytest.raises(ValueError, match=match('The converter is expected to accept 2 parameters: node and context; you have passed 3 parameters.')):
        @changer.converter
        def changing_function(node: Add, context: Context, something_else: str):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )

    with pytest.raises(ValueError, match=match('The converter is expected to accept 2 parameters: node and context; you have passed 1 parameters.')):
        @changer.converter
        def changing_function(node: Add):
            return Subtract(
                whitespace_before=node.whitespace_before,
                whitespace_after=node.whitespace_after,
            )


@pytest.mark.parametrize(
    ['strings', 'expected_comment'],
    [
        (['a = 5 + 6- 7'], None),
        (['a = 5 + 6- 7#'], ''),
        (['a = 5 + 6- 7# ololo!'], ' ololo!'),
        (['a = 5 + 6- 7# other_key: action'], ' other_key: action'),
        (['a = 5 + 6- 7#key: action'],  'key: action'),
        (['a = 5 + 6- 7# key: action'],  ' key: action'),
        (['a = 5 + 6- 7 # key: action'],  ' key: action'),
        (['a = 5 + 6- 7 # key: action# ololo!'],  ' key: action# ololo!'),
    ],
)
def test_read_comments(file, expected_comment):
    changer = Changer(file)

    comments_containers = []

    @changer.converter
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
def test_read_metacodes_from_comment(file, expected_metacodes):
    changer = Changer(file)

    metacodes_containers = []

    @changer.converter
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
def test_filter_any_on(file):
    changer = Changer(file)

    @changer.converter
    def change_something(node: Add, context: Context):
        return Subtract(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    @changer.filter
    def filter_something(node: Any, context: Context) -> bool:
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
def test_filter_any_off(file):
    changer = Changer(file)

    @changer.converter
    def change_something(node: Add, context: Context):
        return Subtract(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    @changer.filter
    def filter_something(node: Any, context: Context) -> bool:
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
def test_filter_cstnode_on(file):
    changer = Changer(file)

    @changer.converter
    def change_something(node: Add, context: Context):
        return Subtract(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    @changer.filter
    def filter_something(node: CSTNode, context: Context) -> bool:
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
def test_filter_cstnode_off(file):
    changer = Changer(file)

    @changer.converter
    def change_something(node: Add, context: Context):
        return Subtract(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    @changer.filter
    def filter_something(node: CSTNode, context: Context) -> bool:
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
def test_filter_node_on(file):
    changer = Changer(file)

    @changer.converter
    def change_something(node: Add, context: Context):
        return Subtract(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    @changer.filter
    def filter_something(node: Add, context: Context) -> bool:
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
def test_filter_node_off(file):
    changer = Changer(file)

    @changer.converter
    def change_something(node: Add, context: Context):
        return Subtract(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    @changer.filter
    def filter_something(node: Add, context: Context) -> bool:
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
def test_filter_other_node_on(file):
    changer = Changer(file)

    @changer.converter
    def change_something(node: Add, context: Context):
        return Subtract(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    @changer.filter
    def filter_something(node: Subtract, context: Context) -> bool:
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
def test_filter_other_node_off(file):
    changer = Changer(file)

    @changer.converter
    def change_something(node: Add, context: Context):
        return Subtract(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    @changer.filter
    def filter_something(node: Subtract, context: Context) -> bool:
        return False

    results = []

    for coordinate in changer.iterate_coordinates():
        results.append(changer.apply_coordinate(coordinate))

    assert len(results) == 1
    assert results[0] == file.replace('+', '-')


def test_converter_with_no_annotation():
    changer = Changer('1')

    @changer.converter
    def converter_func(node, context):
        return node

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]


def test_converter_with_any_annotation():
    changer = Changer('1')

    @changer.converter
    def converter_func(node: Any, context):
        return node

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]


def test_converter_with_cstnode_annotation_restriction():
    changer = Changer('1')

    @changer.converter
    def converter_func(node: CSTNode, context):
        return node

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]


def test_convert_str():
    changer = Changer('a = "kek"')

    nodes = []

    @changer.converter
    def converter_func(node: str, context: Context):
        nodes.append(node)
        return node

    for coordinate in changer.iterate_coordinates():
        changer.apply_coordinate(coordinate)

    assert len(nodes) == 1
    assert isinstance(nodes[0], SimpleString)


def test_convert_float():
    changer = Changer('a = 5.0')

    @changer.converter
    def converter_func(node: float, context: Context):
        return node.with_changes(value=repr(node.evaluated_value + 1))  # type: ignore[attr-defined]

    for coordinate in changer.iterate_coordinates():
        changer.apply_coordinate(coordinate)

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == ['a = 6.0']


def test_filter_with_wrong_number_of_parameters():
    changer = Changer('a = 5')

    with pytest.raises(ValueError, match=match('The filter is expected to accept 2 parameters: node and context; you have passed 3 parameters.')):
        @changer.filter
        def filter_func(node: Add, context: Context, extra_param: str):
            return True

    with pytest.raises(ValueError, match=match('The filter is expected to accept 2 parameters: node and context; you have passed 1 parameters.')):
        @changer.filter
        def filter_func(node: Add):
            return True


def test_filter_with_invalid_annotation():
    changer = Changer('a = 5')

    class SomeClass:
        pass

    with pytest.raises(TypeError, match=match('The type annotation for the first argument of the function must be descended from the libcst.CSTNode class (or be a libcst.CSTNode class if you want to set a filter for all nodes).')):
        @changer.filter
        def filter_func(node: SomeClass, context: Context):
            return True


def test_two_converters_for_same_node():
    changer = Changer('5 + 5')

    @changer.converter
    def converter1(node: Add, context: Context):
        return Subtract(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    @changer.converter
    def converter2(node: Add, context: Context):
        return Multiply(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    assert set(changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()) == {'5 - 5', '5 * 5'}


def test_use_collector_for_converter():
    collector = Collector()

    @collector.converter
    def some_converter(node: Add, context: Context):
        return Subtract(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    changer = Changer('a = 5 + 5', collector=collector)

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == ['a = 5 - 5']


def test_use_collector_for_converter_and_filter():
    collector = Collector()

    filters_value = False

    @collector.converter
    def some_converter(node: Add, context: Context):
        return Subtract(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    @collector.filter
    def some_filter(node: Add, context: Context):
        return filters_value

    changer = Changer('a = 5 + 5', collector=collector)

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == []

    filters_value = True

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == ['a = 5 - 5']


def test_union_with_csts():
    changer = Changer('5 - 5 + 5')

    @changer.converter
    def some_converter(node: Union[Add, Subtract], context: Context):
        return Multiply(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == ['5 * 5 + 5', '5 - 5 * 5']


def test_union_with_union_with_csts():
    changer = Changer('5 - 5 + 5')

    @changer.converter
    def some_converter(node: Union[Add, Union[Multiply, Subtract]], context: Context):
        return Multiply(
            whitespace_before=node.whitespace_before,
            whitespace_after=node.whitespace_after,
        )

    assert set(changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()) == {'5 * 5 + 5', '5 - 5 * 5'}


def test_convert_plus_one():
    changer = Changer('5 - 5 + 5')

    @changer.converter
    def convert_ints(node: int, context):
        return node.with_changes(value=repr(node.evaluated_value + 1))  # type: ignore[attr-defined]

    assert set(changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()) == {'6 - 5 + 5', '5 - 6 + 5', '5 - 5 + 6'}


def test_converter_for_any():
    changer = Changer('5 - 5 + 5')

    nodes = []

    @changer.converter
    def do_something(node: Any, context):
        nodes.append(nodes)
        return node

    [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]
    assert len(nodes) > 10


def test_if_node_is_not_exist_nothing_changed():
    changer = Changer('5 - 5 + 5')

    @changer.converter
    def do_something(node: float, context):
        return node

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == []
