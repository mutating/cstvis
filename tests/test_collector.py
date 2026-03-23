import pytest
from full_match import match

from cstvis import Collector


def test_collections_in_different_collectors_are_not_same():
    first_collector = Collector()
    second_collector = Collector()

    assert isinstance(first_collector._filters, list)
    assert isinstance(first_collector._converters, list)

    assert len(first_collector._filters) == 0
    assert len(first_collector._converters) == 0

    assert first_collector._filters is not second_collector._filters
    assert first_collector._converters is not second_collector._converters


def test_collect_some_filter():
    collector = Collector()

    @collector.filter
    def some_filter(node, context):  # noqa: ARG001
        return True

    assert [x.function for x in collector._filters] == [some_filter]


def test_collect_some_converter():
    collector = Collector()

    @collector.converter
    def some_converter(node, context):  # noqa: ARG001
        return node

    assert [x.function for x in collector._converters] == [some_converter]


def test_add_two_collectors_with_converters():
    collector_1 = Collector()
    collector_2 = Collector()

    @collector_1.converter
    def some_converter_1(node, context):  # noqa: ARG001
        return node

    @collector_2.converter
    def some_converter_2(node, context):  # noqa: ARG001
        return node

    assert [x.function for x in collector_1._converters] == [some_converter_1]
    assert [x.function for x in collector_2._converters] == [some_converter_2]

    collector_3 = collector_1 + collector_2

    assert [x.function for x in collector_3._converters] == [some_converter_1, some_converter_2]


def test_add_two_collectors_with_filters():
    collector_1 = Collector()
    collector_2 = Collector()

    @collector_1.filter
    def some_filter_1(node, context):  # noqa: ARG001
        return False

    @collector_2.filter
    def some_filter_2(node, context):  # noqa: ARG001
        return False

    assert [x.function for x in collector_1._filters] == [some_filter_1]
    assert [x.function for x in collector_2._filters] == [some_filter_2]

    collector_3 = collector_1 + collector_2

    assert [x.function for x in collector_3._filters] == [some_filter_1, some_filter_2]


def test_add_wrong_things_to_collector():
    with pytest.raises(TypeError, match=match('Collector objects can only be added to other collector objects.')):
        Collector() + 1

    with pytest.raises(TypeError, match=match('Collector objects can only be added to other collector objects.')):
        Collector() + 'kek'
