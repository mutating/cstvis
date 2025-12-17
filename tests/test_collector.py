from cstvis import Collector


def test_collections_in_different_collectors_are_not_same():
    first_collector = Collector()
    second_collector = Collector()

    assert isinstance(first_collector.filters, list)
    assert isinstance(first_collector.converters, list)

    assert len(first_collector.filters) == 0
    assert len(first_collector.converters) == 0

    assert first_collector.filters is not second_collector.filters
    assert first_collector.converters is not second_collector.converters


def test_add_some_filter():
    collector = Collector()

    @collector.filter
    def some_filter(node, context):
        return True

    assert collector.filters == [some_filter]


def test_add_some_converter():
    collector = Collector()

    @collector.converter
    def some_converter(node, context):
        return node

    assert collector.converters == [some_converter]
