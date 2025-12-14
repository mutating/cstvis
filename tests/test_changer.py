import pytest
from libcst import Add, Subtract
from full_match import match
from metacode import ParsedComment

from cstvis import Changer, Context



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
            'a = 5 + 6+ 7',
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

    assert len(results) == 2
    assert results == [
        'a = 5 - 6+ 7',
        'a = 5 + 6- 7',
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
