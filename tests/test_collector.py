import pytest
from full_match import match
from libcst import Add, Subtract

from cstvis import Changer, Collector, Context, Converter
from cstvis.wrapper import CallableWrapper


def test_collectors_have_independent_registration_lists():
    """Registering on one Collector leaves the other's filter and converter lists empty."""
    first_collector = Collector()
    second_collector = Collector()

    @first_collector.filter
    def first_filter(node):  # noqa: ARG001
        return True

    @first_collector.converter
    def first_converter(node):
        return node

    assert [wrapper.function for wrapper in first_collector._filters] == [first_filter]
    assert first_collector._converters == [first_converter]
    assert second_collector._filters == []
    assert second_collector._converters == []

    @second_collector.filter
    def second_filter(node):  # noqa: ARG001
        return True

    @second_collector.converter
    def second_converter(node):
        return node

    assert [wrapper.function for wrapper in first_collector._filters] == [first_filter]
    assert first_collector._converters == [first_converter]
    assert [wrapper.function for wrapper in second_collector._filters] == [second_filter]
    assert second_collector._converters == [second_converter]


@pytest.mark.parametrize('registration', ['bare', 'called', 'meta', 'meta_direct'])
def test_collector_filter_returns_original_function(registration):
    """All four registration forms — bare, called, decorator-style meta, and direct meta — return the original callable and store a `CallableWrapper` wrapping it."""
    collector = Collector()
    filter_meta = {'key': 'value'}

    def filter_function(node, context):  # noqa: ARG001
        return True

    if registration == 'bare':
        registered = collector.filter(filter_function)
        expected_meta = None
    elif registration == 'called':
        registered = collector.filter()(filter_function)
        expected_meta = None
    elif registration == 'meta':
        registered = collector.filter(meta=filter_meta)(filter_function)
        expected_meta = filter_meta
    else:
        registered = collector.filter(filter_function, meta=filter_meta)
        expected_meta = filter_meta

    assert registered is filter_function
    assert len(collector._filters) == 1
    stored_wrapper = collector._filters[0]
    assert type(stored_wrapper) is CallableWrapper
    assert stored_wrapper is not filter_function
    assert stored_wrapper.function is filter_function
    assert stored_wrapper.meta == expected_meta
    if registration in ('meta', 'meta_direct'):
        assert stored_wrapper.meta is not filter_meta


@pytest.mark.parametrize('registration_kind', ['converter', 'filter'])
@pytest.mark.parametrize('callback_kind', ['callable_object', 'bound_method'])
def test_collector_accepts_supported_callable_forms(registration_kind, callback_kind):
    """
    Collector accepts callable objects and bound methods for both callback roles,
    and the registered callback actually runs.
    """
    calls = []

    class RecordingCallback:
        def registered_callback(self, node: Add):
            calls.append(node)
            if registration_kind == 'filter':
                return False
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

        __call__ = registered_callback

    registered_callback = RecordingCallback() if callback_kind == 'callable_object' else RecordingCallback().registered_callback
    collector = Collector()
    register = getattr(collector, registration_kind)
    register(registered_callback)

    if registration_kind == 'filter':
        @collector.converter
        def identity(node: Add):
            return node

    changer = Changer('1 + 2', collector=collector)
    coordinates = list(changer.iterate_coordinates())

    if registration_kind == 'filter':
        assert coordinates == []
    else:
        assert len(coordinates) == 1
        assert changer.apply_coordinate(coordinates[0]) == '1 - 2'

    assert len(calls) == 1
    assert isinstance(calls[0], Add)


@pytest.mark.parametrize('registration_kind', ['converter', 'filter'])
def test_collector_injects_keyword_only_context(registration_kind):
    """Collector-registered converters and filters with `*, context=None` receive a real `Context`, not their default."""
    collector = Collector()
    received_contexts = []

    if registration_kind == 'converter':
        @collector.converter
        def callback(node: Add, *, context=None):
            received_contexts.append(context)
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)
    else:
        @collector.filter
        def callback(node: Add, *, context=None) -> bool:  # noqa: ARG001
            received_contexts.append(context)
            return True

        @collector.converter
        def identity(node: Add):
            return node

    changer = Changer('1 + 2', collector=collector)
    for coordinate in changer.iterate_coordinates():
        changer.apply_coordinate(coordinate)

    assert len(received_contexts) == 1
    assert isinstance(received_contexts[0], Context)
    assert received_contexts[0].position.source == '1 + 2'
    assert received_contexts[0].position.coordinate.class_name == 'Add'
    assert received_contexts[0].meta is None


def test_collector_converter_stores_converter_object(unfold):
    """Both bare and called decorator forms return a `Converter`; the collector stores that same object, and it still wraps the original function."""
    collector = Collector()

    def converter_function(node, context):  # noqa: ARG001
        return node

    registered_converter = unfold(collector.converter)(converter_function)

    assert isinstance(registered_converter, Converter)
    assert registered_converter.function is converter_function
    assert len(collector._converters) == 1
    assert collector._converters[0] is registered_converter


@pytest.mark.parametrize(
    'operand',
    [pytest.param(1, id='int'), pytest.param('kek', id='str')],
)
def test_collector_addition_rejects_non_collector_operands(operand):
    """
    Integer and string operands both raise TypeError with the Collector-only diagnostic.
    """
    with pytest.raises(
        TypeError,
        match=match('Collector objects can only be added to other collector objects.'),
    ):
        Collector() + operand


def test_collector_repr():
    """A default or empty-metadata collector renders as `Collector()`; non-empty metadata appears under `meta` using its dictionary repr."""
    assert repr(Collector()) == 'Collector()'
    assert repr(Collector(meta={})) == 'Collector()'
    assert repr(Collector(meta={'lol': 'kek'})) == "Collector(meta={'lol': 'kek'})"


@pytest.mark.parametrize(
    ('collector_meta', 'decorator_meta', 'expected_meta'),
    [
        pytest.param({'lol': 'kek'}, None, {'lol': 'kek'}, id='collector-only'),
        pytest.param(None, {'lol': 'kek'}, {'lol': 'kek'}, id='decorator-only'),
        pytest.param(
            {'lol_1': 'kek_1', 'lol_2': 'kek_2'},
            {'lol_2': 'kek_2-2', 'lol_3': 'kek_3'},
            {'lol_1': 'kek_1', 'lol_2': 'kek_2-2', 'lol_3': 'kek_3'},
            id='merged',
        ),
    ],
)
def test_collected_wrappers_copy_and_merge_meta(collector_meta, decorator_meta, expected_meta):
    """Bare registrations inherit constructor meta; decorator meta is copied over it and overrides duplicate keys. Each wrapper gets its own top-level copy."""
    original_collector_meta = dict(collector_meta) if collector_meta is not None else None
    original_decorator_meta = dict(decorator_meta) if decorator_meta is not None else None
    collector = Collector(meta=collector_meta)
    register_converter = collector.converter if decorator_meta is None else collector.converter(meta=decorator_meta)
    register_filter = collector.filter if decorator_meta is None else collector.filter(meta=decorator_meta)

    @register_converter
    def identity_converter(node, context):  # noqa: ARG001
        return node

    @register_filter
    def reject_filter(node, context):  # noqa: ARG001
        return False

    assert collector._converters[0].meta == expected_meta
    assert collector._filters[0].meta == expected_meta
    assert collector._converters[0].meta is not collector._filters[0].meta

    if collector_meta is not None:
        assert collector._converters[0].meta is not collector_meta
        assert collector._filters[0].meta is not collector_meta
    if decorator_meta is not None:
        assert collector._converters[0].meta is not decorator_meta
        assert collector._filters[0].meta is not decorator_meta

    assert collector_meta == original_collector_meta
    assert decorator_meta == original_decorator_meta


def test_collector_preserves_registration_order_within_and_across_collectors():
    """
    Each Collector preserves insertion order, and a combined Collector
    concatenates the left operand's registrations before the right operand's.
    """
    collector_1 = Collector()
    collector_2 = Collector()

    @collector_1.filter
    def filter_1a(node):  # noqa: ARG001
        return True

    @collector_1.filter
    def filter_1b(node):  # noqa: ARG001
        return True

    @collector_2.filter
    def filter_2(node):  # noqa: ARG001
        return True

    @collector_1.converter
    def converter_1a(node):
        return node

    @collector_1.converter
    def converter_1b(node):
        return node

    @collector_2.converter
    def converter_2(node):
        return node

    combined = collector_1 + collector_2

    assert [wrapper.function for wrapper in collector_1._filters] == [filter_1a, filter_1b]
    assert [wrapper.function for wrapper in collector_2._filters] == [filter_2]
    assert collector_1._converters == [converter_1a, converter_1b]
    assert collector_2._converters == [converter_2]
    assert [wrapper.function for wrapper in combined._filters] == [filter_1a, filter_1b, filter_2]
    assert combined._converters == [converter_1a, converter_1b, converter_2]


@pytest.mark.parametrize('registration_kind', ['converter', 'filter'])
def test_collector_direct_meta_registration(registration_kind):
    """
    Collector.converter and Collector.filter accept a callback and meta in one
    direct call, merging collector and decorator meta.
    """
    collector = Collector(meta={'collector': 1})
    decorator_meta = {'decorator': 2}

    def callback(node, context):  # noqa: ARG001
        return node

    if registration_kind == 'converter':
        registered = collector.converter(callback, meta=decorator_meta)
        assert registered.function is callback
        assert registered.meta == {'collector': 1, 'decorator': 2}
        assert registered.meta is not decorator_meta
        assert collector._converters == [registered]
    else:
        registered = collector.filter(callback, meta=decorator_meta)
        assert registered is callback
        assert collector._filters[0].function is callback
        assert collector._filters[0].meta == {'collector': 1, 'decorator': 2}
        assert collector._filters[0].meta is not decorator_meta

    assert decorator_meta == {'decorator': 2}


@pytest.mark.parametrize('mutated_side', ['left', 'right', 'combined'])
def test_collector_addition_creates_independent_registration_lists(mutated_side):
    """`Collector.__add__` creates registration lists independent of its operands: additions affect only the receiving collector, while wrapper and `Converter` objects remain shared."""
    collector_1 = Collector()
    collector_2 = Collector()

    @collector_1.filter
    def filter_1(node):  # noqa: ARG001
        return True

    @collector_2.filter
    def filter_2(node):  # noqa: ARG001
        return True

    @collector_1.converter
    def converter_1(node):
        return node

    @collector_2.converter
    def converter_2(node):
        return node

    combined = collector_1 + collector_2

    assert combined._filters is not collector_1._filters
    assert combined._filters is not collector_2._filters
    assert combined._converters is not collector_1._converters
    assert combined._converters is not collector_2._converters

    filter_wrapper_1 = collector_1._filters[0]
    filter_wrapper_2 = collector_2._filters[0]
    assert combined._filters[0] is filter_wrapper_1
    assert combined._filters[1] is filter_wrapper_2
    assert combined._converters[0] is collector_1._converters[0]
    assert combined._converters[1] is collector_2._converters[0]

    initial_combined_filters = list(combined._filters)
    initial_combined_converters = list(combined._converters)

    collector_to_mutate = {'left': collector_1, 'right': collector_2, 'combined': combined}[mutated_side]

    @collector_to_mutate.filter
    def late_filter(node):  # noqa: ARG001
        return True

    @collector_to_mutate.converter
    def late_converter(node):
        return node

    if mutated_side == 'left':
        assert [wrapper.function for wrapper in collector_1._filters] == [filter_1, late_filter]
        assert collector_1._converters == [converter_1, late_converter]
        assert collector_2._filters == [filter_wrapper_2]
        assert collector_2._converters == [converter_2]
        assert combined._filters == initial_combined_filters
        assert combined._converters == initial_combined_converters
    elif mutated_side == 'right':
        assert collector_1._filters == [filter_wrapper_1]
        assert collector_1._converters == [converter_1]
        assert [wrapper.function for wrapper in collector_2._filters] == [filter_2, late_filter]
        assert collector_2._converters == [converter_2, late_converter]
        assert combined._filters == initial_combined_filters
        assert combined._converters == initial_combined_converters
    else:
        assert collector_1._filters == [filter_wrapper_1]
        assert collector_2._filters == [filter_wrapper_2]
        assert collector_1._converters == [converter_1]
        assert collector_2._converters == [converter_2]
        assert [wrapper.function for wrapper in combined._filters] == [filter_1, filter_2, late_filter]
        assert combined._converters == [converter_1, converter_2, late_converter]


def test_combined_collector_keeps_operand_meta_only_on_existing_wrappers():
    """
    Combining collectors does not merge their constructor metadata.

    Existing wrappers keep the metadata they received from their original
    collector, while new registrations on the combined Collector start without
    metadata.
    """
    collector_1 = Collector(meta={'a': 1})
    collector_2 = Collector(meta={'b': 2})

    @collector_1.filter(meta={'filter': 1})
    def filter_1(node):  # noqa: ARG001
        return True

    @collector_1.converter
    def converter_1(node):
        return node

    @collector_2.filter(meta={'filter': 2})
    def filter_2(node):  # noqa: ARG001
        return True

    @collector_2.converter
    def converter_2(node):
        return node

    combined = collector_1 + collector_2

    assert combined._meta == {}
    assert converter_1.meta == {'a': 1}
    assert converter_2.meta == {'b': 2}
    assert combined._filters[0].meta == {'a': 1, 'filter': 1}
    assert combined._filters[1].meta == {'b': 2, 'filter': 2}
    assert combined._converters[0].meta == {'a': 1}
    assert combined._converters[1].meta == {'b': 2}

    @combined.converter
    def combined_converter(node):
        return node

    @combined.filter
    def combined_filter(node):  # noqa: ARG001
        return True

    assert combined_converter.meta is None
    assert combined._filters[2].meta is None
