import pytest

from libcst import CSTNode, parse_module, metadata

from cstvis.visitors.comments_aggregator import CommentsAggregator


@pytest.mark.parametrize(
    ['strings'],
    [
        ([
            'a = 5',
            'b = 12 * a'
        ],),
    ],
)
def test_code_without_comments(file):
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
    wrapper = metadata.MetadataWrapper(parse_module(file))
    aggregator = CommentsAggregator()
    wrapper.visit(aggregator)

    assert aggregator.comments == {2: 'lol', 3: ' kek'}
