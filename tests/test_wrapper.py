import sys
import typing
from typing import Optional

import pytest
from full_match import match
from libcst import Add, CSTNode, Integer, Multiply, SimpleString, Subtract

from cstvis import Changer, Collector, Context
from cstvis.wrapper import CallableWrapper
from tests.helpers import make_integer_context


def test_callable_wrapper_repr():
    """The repr is constructor-like: default meta is omitted, the function appears by bare name, and explicit empty or non-empty meta is a second positional argument."""
    def function(a, b):
        ...

    assert repr(CallableWrapper(function)) == 'CallableWrapper(function)'
    assert repr(CallableWrapper(function, meta=None)) == 'CallableWrapper(function)'
    assert repr(CallableWrapper(function, meta={})) == 'CallableWrapper(function, {})'
    assert repr(CallableWrapper(function, meta={'kek': 1234})) == "CallableWrapper(function, {'kek': 1234})"


def test_callable_wrapper_copies_meta_without_mutating_base_context():
    """
    A context-aware callback receives copied decorator meta without changing the base Context or caller-owned dictionary.
    """
    decorator_meta = {'mode': 'wrapped'}
    base_meta = {'mode': 'base'}
    base_context = make_integer_context(base_meta)
    received_contexts = []

    def callback(node: Integer, context: Context) -> Integer:
        received_contexts.append(context)
        return node

    wrapper = CallableWrapper(callback, decorator_meta)
    node = Integer('1')

    assert wrapper(node, base_context) is node
    assert len(received_contexts) == 1
    callback_context = received_contexts[0]
    assert callback_context.meta == decorator_meta
    assert callback_context.meta is not decorator_meta
    assert callback_context.position is base_context.position
    assert base_context.meta is base_meta
    assert base_meta == {'mode': 'base'}
    assert wrapper.meta is decorator_meta
    assert decorator_meta == {'mode': 'wrapped'}


def test_callable_wrapper_creates_fresh_meta_for_each_invocation():
    """
    Each call receives fresh meta, isolating mutations from later calls and wrapper state.
    """
    decorator_meta = {'value': 'original'}
    base_context = make_integer_context({'base': True})
    received_meta = []

    def callback(node: Integer, context: Context) -> Integer:
        assert context.meta is not None
        received_meta.append(context.meta)
        if len(received_meta) == 1:
            context.meta['value'] = 'changed'
        return node

    wrapper = CallableWrapper(callback, decorator_meta)
    wrapper(Integer('1'), base_context)
    wrapper(Integer('1'), base_context)

    first_callback_meta, second_callback_meta = received_meta
    assert first_callback_meta is not second_callback_meta
    assert first_callback_meta is not decorator_meta
    assert second_callback_meta is not decorator_meta
    assert first_callback_meta == {'value': 'changed'}
    assert second_callback_meta == {'value': 'original'}
    assert decorator_meta == {'value': 'original'}
    assert wrapper.meta == {'value': 'original'}
    assert base_context.meta == {'base': True}


def test_callable_wrapper_with_no_meta_passes_none():
    """
    A wrapper without decorator meta passes meta=None without mutating the base Context.
    """
    base_context = make_integer_context({'base': True})
    received_meta = []

    def callback(node: Integer, context: Context) -> Integer:
        received_meta.append(context.meta)
        return node

    CallableWrapper(callback)(Integer('1'), base_context)

    assert received_meta == [None]
    assert base_context.meta == {'base': True}


def test_callable_wrapper_keyword_only_context_passes_copied_meta():
    """A keyword-only `context` receives a `Context` with a fresh copy of wrapper meta, while the base `SourcePosition` and comment are preserved."""
    decorator_meta = {'mode': 'keyword'}
    base_context = make_integer_context({'base': True}, comment=' key: action')
    received_contexts = []

    def callback(node: Integer, *, context=None):
        received_contexts.append(context)
        assert context is not None
        assert context.meta is not None
        if len(received_contexts) == 1:
            context.meta['mode'] = 'changed'
        return node

    wrapper = CallableWrapper(callback, decorator_meta)
    node = Integer('1')

    assert wrapper(node, base_context) is node
    assert wrapper(node, base_context) is node
    assert len(received_contexts) == 2
    assert all(isinstance(context, Context) for context in received_contexts)
    assert received_contexts[0].meta is not decorator_meta
    assert received_contexts[0].meta is not received_contexts[1].meta
    assert received_contexts[0].meta == {'mode': 'changed'}
    assert received_contexts[1].meta == {'mode': 'keyword'}
    assert received_contexts[1].meta is not decorator_meta
    assert all(context.position is base_context.position for context in received_contexts)
    assert all(context.comment == ' key: action' for context in received_contexts)
    assert base_context.comment == ' key: action'
    assert base_context.meta == {'base': True}
    assert wrapper.meta == {'mode': 'keyword'}
    assert wrapper.meta is decorator_meta


def test_callable_wrapper_node_only_callback_receives_no_context():
    """The callback receives only the node; base and wrapper meta stay unchanged."""
    base_context = make_integer_context({'base': True})
    received_nodes = []

    def callback(node: Integer):
        received_nodes.append(node)
        return node

    node = Integer('1')
    wrapper = CallableWrapper(callback, {'unused': 1})

    assert wrapper(node, base_context) is node
    assert received_nodes == [node]
    assert base_context.meta == {'base': True}
    assert wrapper.meta == {'unused': 1}


@pytest.mark.parametrize(
    'decorator_meta',
    [pytest.param(None, id='none'), pytest.param({}, id='empty')],
)
def test_callable_wrapper_keyword_only_context_meta_is_none_or_empty(decorator_meta):
    """
    With keyword-only context injection the callback always receives a real
    `Context`; its `meta` attribute is `None` for `meta=None` and an empty
    dictionary for an explicit `meta={}`.
    """
    base_context = make_integer_context({'base': True})
    received_contexts = []

    def callback(node: Integer, *, context=None):
        received_contexts.append(context)
        return node

    node = Integer('1')
    wrapper = CallableWrapper(callback, decorator_meta)

    assert wrapper(node, base_context) is node
    assert len(received_contexts) == 1
    assert isinstance(received_contexts[0], Context)
    assert received_contexts[0].meta == decorator_meta
    if decorator_meta is not None:
        assert received_contexts[0].meta is not decorator_meta
    assert base_context.meta == {'base': True}


def test_collector_defers_invalid_annotation_until_changer_construction():
    """The annotation error surfaces only when a Changer builds its type mappings, not at Collector registration."""
    message = match('The type annotation for the first argument of the function must be descended from the libcst.CSTNode class.')

    filter_collector = Collector()

    @filter_collector.filter
    def invalid_filter(node: object) -> bool:  # noqa: ARG001
        return True

    with pytest.raises(TypeError, match=message):
        Changer('1 + 2', collector=filter_collector)

    converter_collector = Collector()

    @converter_collector.converter
    def invalid_converter(node: object):
        return node

    with pytest.raises(TypeError, match=message):
        Changer('1 + 2', collector=converter_collector)


@pytest.mark.parametrize('registration_kind', ['converter', 'filter'])
def test_unsupported_annotation_forms_are_rejected_for_converters_and_filters(registration_kind):
    """For both converters and filters, `Optional[Add]` and string annotations fail with the standard annotation error; `Annotated[Add, 'marker']` is also rejected on Python 3.9+. No partial registrations remain."""
    message = match('The type annotation for the first argument of the function must be descended from the libcst.CSTNode class.')
    changer = Changer('1 + 2')
    register = changer.converter if registration_kind == 'converter' else changer.filter

    def optional_annotation(node: Optional[Add]):
        return node

    with pytest.raises(TypeError, match=message):
        register(optional_annotation)

    def string_annotation(node: 'Add'):
        return node

    with pytest.raises(TypeError, match=message):
        register(string_annotation)

    if sys.version_info >= (3, 9):
        def annotated_annotation(node: typing.Annotated[Add, 'marker']):
            return node

        with pytest.raises(TypeError, match=message):
            register(annotated_annotation)

    assert not changer.converters_by_types
    assert not changer.filters_by_types


if sys.version_info >= (3, 10):
    def test_pep604_union_converter_dispatches_for_each_member():
        """An `Add | Subtract` converter is dispatched for both operator types and produces independent replacements for each matching node."""
        changer = Changer('1 + 2 - 3')

        @changer.converter
        def convert(node: Add | Subtract):
            return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

        coordinates = list(changer.iterate_coordinates())

        assert len(coordinates) == 2
        applied = {coordinate.class_name: changer.apply_coordinate(coordinate) for coordinate in coordinates}
        assert applied == {'Add': '1 * 2 - 3', 'Subtract': '1 + 2 * 3'}


    def test_pep604_union_filter_is_called_for_each_member():
        """An `Add | Subtract` filter is called for both node types, but only `Add` passes, so one coordinate remains."""
        changer = Changer('1 + 2 - 3')
        seen_types = []

        @changer.converter
        def convert(node: Add | Subtract):
            return node

        @changer.filter
        def allow(node: Add | Subtract) -> bool:
            seen_types.append(type(node))
            return isinstance(node, Add)

        coordinates = list(changer.iterate_coordinates())

        assert len(coordinates) == 1
        assert coordinates[0].class_name == 'Add'
        assert changer.apply_coordinate(coordinates[0]) == '1 + 2 - 3'
        assert len(seen_types) == 2
        assert set(seen_types) == {Add, Subtract}


    @pytest.mark.parametrize('registration_kind', ['converter', 'filter'])
    def test_pep604_union_with_non_cst_member_is_rejected(registration_kind):
        """A PEP 604 union containing a non-CST member is rejected for converters and filters, leaving no registrations behind."""
        changer = Changer('1 + 2 - 3')

        def invalid_union_callback(node: Add | object):
            return node

        register = changer.converter if registration_kind == 'converter' else changer.filter
        with pytest.raises(TypeError, match=match('The type annotation for the first argument of the function must be descended from the libcst.CSTNode class.')):
            register(invalid_union_callback)
        assert not changer.converters_by_types
        assert not changer.filters_by_types


    @pytest.mark.parametrize(
        ('annotation', 'expected_types'),
        [
            pytest.param(Add | CSTNode, {Add, CSTNode}, id='catch-all'),
            pytest.param(Add | int, {Add, Integer}, id='mixed-shortcut'),
            pytest.param(int | str, {Integer, SimpleString}, id='shortcuts'),
        ],
    )
    @pytest.mark.parametrize('registration_kind', ['converter', 'filter'])
    def test_pep604_union_maps_members_to_node_types(annotation, expected_types, registration_kind):
        """
        A PEP 604 union registers the same callback for every included member.

        Catch-all and builtin-shortcut members map to their corresponding node
        types for converters and filters.
        """
        changer = Changer('1 + 2')

        if registration_kind == 'converter':
            def callback(node):
                return node
            register = changer.converter
            mappings = changer.converters_by_types
        else:
            def callback(node):  # noqa: ARG001
                return True
            register = changer.filter
            mappings = changer.filters_by_types

        callback.__annotations__['node'] = annotation
        register(callback)

        assert set(mappings) == expected_types
        for node_type in expected_types:
            assert [wrapper.function for wrapper in mappings[node_type]] == [callback]
