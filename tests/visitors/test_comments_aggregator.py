import pytest
from libcst import metadata, parse_module

from cstvis.visitors.comments_aggregator import CommentsAggregator


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5',
            'b = 12 * a',
        ],),
    ],
)
def test_code_without_comments(file):
    """
    A module with ordinary code but no comments leaves the comments map empty.

    Lines without comments are omitted rather than recorded with placeholder values.
    """
    wrapper = metadata.MetadataWrapper(parse_module(file))
    aggregator = CommentsAggregator()
    wrapper.visit(aggregator)

    assert aggregator.comments == {}


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5',
            'b = 12 * a #lol',
        ],),
    ],
)
def test_code_with_one_comment(file):
    """
    Record one trailing inline comment under its 1-based source line.

    The collected mapping is {2: 'lol'}, showing that the leading '#' is removed from the comment after code while the remaining comment text is kept unchanged.
    """
    wrapper = metadata.MetadataWrapper(parse_module(file))
    aggregator = CommentsAggregator()
    wrapper.visit(aggregator)

    assert aggregator.comments == {2: 'lol'}


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5',
            'b = 12 * a #lol',
            'c = 12 * b # kek',
        ],),
    ],
)
def test_code_with_two_comments(file):
    """
    Accumulates separate inline comments by their 1-based source line numbers.

    The expected mapping shows that multiple comments are retained together and that only the leading `#` is removed, preserving the remaining text, including a leading space.
    """
    wrapper = metadata.MetadataWrapper(parse_module(file))
    aggregator = CommentsAggregator()
    wrapper.visit(aggregator)

    assert aggregator.comments == {2: 'lol', 3: ' kek'}
