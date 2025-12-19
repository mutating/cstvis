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


def test_add_some_filter():
    collector = Collector()

    @collector.filter
    def some_filter(node, context):  # noqa: ARG001
        return True

    assert collector._filters == [some_filter]


def test_add_some_converter():
    collector = Collector()

    @collector.converter
    def some_converter(node, context):  # noqa: ARG001
        return node

    assert collector._converters == [some_converter]
