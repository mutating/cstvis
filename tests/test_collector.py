import pytest
from full_match import match

from cstvis import Collector


def test_collections_in_different_collectors_are_not_same():
    """
    A new Collector starts with empty, independent registration lists.

    Separate Collector instances have distinct `_filters` and `_converters` lists, so registrations cannot leak through shared mutable defaults.
    """
    first_collector = Collector()
    second_collector = Collector()

    assert isinstance(first_collector._filters, list)
    assert isinstance(first_collector._converters, list)

    assert len(first_collector._filters) == 0
    assert len(first_collector._converters) == 0

    assert first_collector._filters is not second_collector._filters
    assert first_collector._converters is not second_collector._converters


def test_collect_some_filter():
    """
    Registering a collector filter stores the original function in the filter collection.

    The decorated name remains bound to the same callable, while the collector stores a wrapper whose function is that callable.
    """
    collector = Collector()

    @collector.filter
    def some_filter(node, context):  # noqa: ARG001
        return True

    assert [x.function for x in collector._filters] == [some_filter]


def test_collect_some_converter():
    """
    Collects a converter registered with the bare collector decorator without replacing it.

    The decorated function remains the original callable, and the collector records that callable as its converter for later use.
    """
    collector = Collector()

    @collector.converter
    def some_converter(node, context):  # noqa: ARG001
        return node

    assert [x.function for x in collector._converters] == [some_converter]


def test_add_two_collectors_with_converters():
    """
    Adding two collectors combines converter registrations in left-to-right order.

    Before addition, each original collector contains only its own converter. The combined collector lists the left converter before the right converter.
    """
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
    """
    Adding two collectors combines their registered filters in left-to-right order.

    Before addition, each original collector contains only its own filter. The combined collector lists the left callback before the right callback.
    """
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
    """
    Reject non-Collector operands when adding to a Collector.

    Integer and string operands should both raise TypeError with the Collector-only diagnostic.
    """
    with pytest.raises(TypeError, match=match('Collector objects can only be added to other collector objects.')):
        Collector() + 1

    with pytest.raises(TypeError, match=match('Collector objects can only be added to other collector objects.')):
        Collector() + 'kek'


def test_repr():
    """
    Pin Collector repr output for default and non-empty constructor metadata.

    A default collector renders as `Collector()`, while a collector with metadata includes it as the `meta` keyword using the dictionary repr.
    """
    assert repr(Collector()) == 'Collector()'
    assert repr(Collector(meta={'lol': 'kek'})) == "Collector(meta={'lol': 'kek'})"


def test_meta_for_collector_but_not_for_converter_or_filter():
    """
    Bare converter and filter registrations inherit collector-level metadata.

    Each collected wrapper receives metadata equal to the Collector constructor dictionary while holding its own top-level copy, so neither wrapper reuses the caller's original dictionary.
    """
    meta = {'lol': 'kek'}
    collector = Collector(meta=meta)

    @collector.converter
    def some_converter(node, context):  # noqa: ARG001
        return node

    @collector.filter
    def some_filter(node, context):  # noqa: ARG001
        return False

    assert collector._converters[0].meta == meta
    assert collector._converters[0].meta is not meta

    assert collector._filters[0].meta == meta
    assert collector._filters[0].meta is not meta


def test_meta_for_converter_or_filter_but_not_for_collector():
    """
    Stores decorator-level metadata on collected converter and filter wrappers.

    A collector created without constructor metadata should attach equal but top-level copied meta dictionaries to wrappers registered with converter- and filter-level meta.
    """
    meta = {'lol': 'kek'}
    collector = Collector()

    @collector.converter(meta=meta)
    def some_converter(node, context):  # noqa: ARG001
        return node

    @collector.filter(meta=meta)
    def some_filter(node, context):  # noqa: ARG001
        return False

    assert collector._converters[0].meta == meta
    assert collector._converters[0].meta is not meta

    assert collector._filters[0].meta == meta
    assert collector._filters[0].meta is not meta


def test_meta_for_for_converter_or_filter_and_for_collector():
    """
    Registers merged collector and decorator metadata for converters and filters.

    Decorator metadata overrides collector metadata for duplicate keys, and each wrapper receives a copied top-level metadata dictionary rather than either original input dictionary.
    """
    meta_1 = {'lol_1': 'kek_1', 'lol_2': 'kek_2'}
    meta_2 = {'lol_2': 'kek_2-2', 'lol_3': 'kek_3'}

    collector = Collector(meta=meta_1)

    @collector.converter(meta=meta_2)
    def some_converter(node, context):  # noqa: ARG001
        return node

    @collector.filter(meta=meta_2)
    def some_filter(node, context):  # noqa: ARG001
        return False

    assert collector._converters[0].meta == {'lol_1': 'kek_1', 'lol_2': 'kek_2-2', 'lol_3': 'kek_3'}
    assert collector._converters[0].meta is not meta_1
    assert collector._converters[0].meta is not meta_2

    assert collector._filters[0].meta == {'lol_1': 'kek_1', 'lol_2': 'kek_2-2', 'lol_3': 'kek_3'}
    assert collector._filters[0].meta is not meta_1
    assert collector._filters[0].meta is not meta_2
