from typing import Optional

import pytest
from libcst import Add

from cstvis import Changer, Coordinate


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
    def name_changer(node: Add, coordinate: Coordinate, comment: Optional[str]):
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
