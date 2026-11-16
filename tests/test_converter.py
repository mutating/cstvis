import inspect
from functools import partial
from inspect import signature, unwrap
from typing import Any, List, Union

import pytest
from full_match import match
from libcst import Add, CSTNode, Float, Integer, Multiply, SimpleString, Subtract
from sigmatch import SignatureMismatchError

from cstvis import (
    Changer,
    Collector,
    Context,
    Converter,
    ConverterWrappingError,
)
from cstvis.converter import build_converter_ids
from cstvis.wrapper import CallableWrapper
from tests.helpers import collect_nodes, make_add_context


class NestedPartial(partial):
    """A partial wrapper that deliberately keeps another partial in `func`."""

    def __new__(cls, inner):
        def call(*args, **kwargs):
            return inner(*args, **kwargs)

        instance = super().__new__(cls, call)
        instance._inner = inner
        return instance

    @property
    def func(self):
        return self._inner


def no_arguments_function():
    """Callback with no parameters."""
    return


def three_arguments_function(node, context, extra):  # noqa: ARG001
    """Callback with three parameters."""
    return node


class NoArgumentsCallable:
    """Callable object whose `__call__` takes no parameters."""

    def __call__(self):
        return None


class ThreeArgumentsCallable:
    """Callable object whose `__call__` takes three parameters."""

    def __call__(self, node: Add, context, extra):  # noqa: ARG002
        return node


def kwargs_only_callback(**kwargs):
    """Callback without a positional node parameter."""
    return kwargs


def keyword_only_node_callback(*, node):
    """Callback whose node parameter is keyword-only."""
    return node


def test_single_converter_keeps_unsuffixed_function_based_id():
    """
    A single converter without id collisions keeps the documented function-based coordinate id.

    Disambiguation suffixes are reserved for distinct Converter objects that share the same function id.
    """
    changer = Changer('1 + 2')

    def converter_function(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    converter = changer.converter(converter_function)
    coordinates = list(changer.iterate_coordinates())
    expected_id = f'{converter_function.__module__}:{converter_function.__name__}:{converter_function.__code__.co_firstlineno}'

    assert converter.function is converter_function
    assert converter.get_function_id() == expected_id
    assert len(coordinates) == 1
    assert coordinates[0].converter_id == expected_id
    assert changer.apply_coordinate(coordinates[0]) == '1 - 2'


def test_function_id_format_is_module_function_name_line():
    """The public function-id format is `module:name:first-source-line`."""
    def converter_function(node: Add):
        return node

    source_line = inspect.getsourcelines(converter_function)[1]

    assert Converter(converter_function).get_function_id() == f'{__name__}:converter_function:{source_line}'


def test_converter_repr_includes_meta_except_when_none():
    """The repr uses the `Converter` class name and includes meta except when it is `None`; an explicit `{}` is included."""
    def function(node):
        return node

    assert repr(Converter(function)) == 'Converter(function)'
    assert repr(Converter(function, meta=None)) == 'Converter(function)'
    assert repr(Converter(function, meta={})) == 'Converter(function, {})'
    assert repr(Converter(function, meta={'kek': 1234})) == "Converter(function, {'kek': 1234})"


@pytest.mark.parametrize('callback_kind', ['callable_object', 'bound_method'])
@pytest.mark.parametrize('context_style', ['positional', 'keyword_only'])
def test_callable_objects_and_bound_methods_receive_context(callback_kind, context_style):
    """Callable objects and bound methods receive `Context` both positionally and via keyword-only `context=None`, along with the converter's meta."""
    contexts: List[Context] = []

    class PositionalCallableConverter:
        """Converter callable object that accepts a positional Context."""

        def __init__(self, received_contexts: List[Context]) -> None:
            self.contexts = received_contexts

        def __call__(self, node: Add, context: Context):
            self.contexts.append(context)
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    class KeywordCallableConverter:
        """Converter callable object that accepts a keyword-only Context."""

        def __init__(self, received_contexts: List[Context]) -> None:
            self.contexts = received_contexts

        def __call__(self, node: Add, *, context=None):
            self.contexts.append(context)
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    class BoundConverterOwner:
        """Provide positional and keyword-only bound-method converters."""

        def __init__(self, received_contexts: List[Context]) -> None:
            self.contexts = received_contexts

        def positional(self, node: Add, context: Context):
            self.contexts.append(context)
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

        def keyword(self, node: Add, *, context=None):
            self.contexts.append(context)
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    if callback_kind == 'callable_object':
        callback = PositionalCallableConverter(contexts) if context_style == 'positional' else KeywordCallableConverter(contexts)
        expected_function = type(callback).__call__
    else:
        owner = BoundConverterOwner(contexts)
        callback = owner.positional if context_style == 'positional' else owner.keyword
        expected_function = callback

    changer = Changer('1 + 2')
    converter = changer.converter(callback, meta={'kind': 'callable'})
    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == '1 - 2'
    assert converter.get_function_id() == f'{expected_function.__module__}:{expected_function.__name__}:{expected_function.__code__.co_firstlineno}'
    if callback_kind == 'callable_object':
        assert converter.function is callback
    else:
        assert converter.function.__self__ is owner
    assert len(contexts) == 1
    assert isinstance(contexts[0], Context)
    assert contexts[0].meta == {'kind': 'callable'}
    assert contexts[0].position.source == '1 + 2'
    assert contexts[0].position.coordinate.class_name == 'Add'


def test_direct_call_uses_caller_context_while_call_with_context_uses_converter_meta():
    """A direct call uses the caller's `Context`; `call_with_context` substitutes a fresh copy of the converter meta, preserves the shared `SourcePosition`, and leaves the caller's `Context` untouched."""
    received_contexts = []

    def convert(node: Add, context: Context):
        received_contexts.append(context)
        return node

    converter = Converter(convert, meta={'registered': 1})
    node = Add()
    base_context = make_add_context({'caller': 2})

    assert converter(node, base_context) is node
    assert received_contexts[0] is base_context

    assert converter.call_with_context(node, base_context) is node
    assert received_contexts[1].meta == {'registered': 1}
    assert received_contexts[1].meta is not converter.meta
    assert received_contexts[1].position is base_context.position
    assert base_context.meta == {'caller': 2}

    assert converter.call_with_context(node, base_context) is node
    assert received_contexts[2].meta == {'registered': 1}
    assert received_contexts[2].meta is not received_contexts[1].meta
    assert base_context.meta == {'caller': 2}
    assert converter.meta == {'registered': 1}


def test_converter_forwards_keyword_arguments_to_wrapped_function():
    """
    A direct Converter call forwards keyword arguments to the wrapped function.
    """
    received_arguments = []

    def convert(node, context=None, *, marker='unset'):
        received_arguments.append((node, context, marker))
        return node

    converter = Converter(convert)
    node = Add()
    base_context = make_add_context()

    assert converter(node=node, context=base_context, marker='sentinel') is node
    assert len(received_arguments) == 1
    assert received_arguments[0][0] is node
    assert received_arguments[0][1] is base_context
    assert received_arguments[0][2] == 'sentinel'


def test_direct_calls_and_call_with_context_do_not_apply_bound_filters():
    """Bound filters run only during discovery: neither a direct call nor `call_with_context` consults them."""
    filter_calls = []
    changer = Changer('1 + 2')

    @changer.converter
    def convert(node: Add):
        return node

    @convert.filter
    def reject(node: Add) -> bool:
        filter_calls.append(node)
        return False

    assert [wrapper.function for wrapper in convert.filters] == [reject]
    assert list(changer.iterate_coordinates()) == []
    assert len(filter_calls) == 1
    assert isinstance(filter_calls[0], Add)

    filter_calls.clear()
    node = Add()
    base_context = make_add_context()

    assert convert(node) is node
    assert convert.call_with_context(node, base_context) is node
    assert filter_calls == []


def test_converter_filter_returns_original_function_and_stores_wrapper():
    """
    Converter.filter returns the callback unchanged and stores a CallableWrapper.

    The supplied meta is stored on the wrapper when provided and None otherwise;
    the converter's own meta is not modified.
    """
    converter = Converter(lambda node: node, meta={'converter': 1})

    def first_filter(node):  # noqa: ARG001
        return True

    def second_filter(node):  # noqa: ARG001
        return True

    def third_filter(node):  # noqa: ARG001
        return True

    assert converter.filter(first_filter) is first_filter
    assert converter.filter()(second_filter) is second_filter
    assert converter.filter(meta={'filter': 3})(third_filter) is third_filter

    assert len(converter.filters) == 3
    assert all(type(wrapper) is CallableWrapper for wrapper in converter.filters)
    assert [wrapper.function for wrapper in converter.filters] == [first_filter, second_filter, third_filter]
    assert [wrapper.meta for wrapper in converter.filters] == [None, None, {'filter': 3}]
    assert converter.meta == {'converter': 1}

    def fourth_filter(node):  # noqa: ARG001
        return True

    assert converter.filter(fourth_filter, meta={'filter': 4}) is fourth_filter
    assert converter.filters[-1].function is fourth_filter
    assert converter.filters[-1].meta == {'filter': 4}


def test_converter_accepts_callable_object_without_function_metadata():
    """Registration and traversal succeed for a callable object without `__name__` or `__code__`; its id comes from `__call__`, and both direct calls and coordinate application work."""
    class AddToSubtract:
        def __call__(self, node: Add):
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    changer = Changer('1 + 2')
    callback_object = AddToSubtract()

    assert not hasattr(callback_object, '__name__')
    assert not hasattr(callback_object, '__code__')

    converter = changer.converter(callback_object)

    assert isinstance(converter, Converter)
    assert converter.function is callback_object
    expected_id = f'{AddToSubtract.__call__.__module__}:{AddToSubtract.__call__.__name__}:{AddToSubtract.__call__.__code__.co_firstlineno}'
    assert converter.get_function_id() == expected_id
    assert isinstance(converter(Add()), Subtract)

    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == '1 - 2'


def test_partial_converter_uses_underlying_function_id_and_applies_replacement():
    """A `functools.partial` is supported when its remaining signature is valid."""
    def convert(node: Add, replacement):
        return replacement(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    changer = Changer('1 + 2')
    converter = changer.converter(partial(convert, replacement=Subtract))

    assert converter.get_function_id() == f'{convert.__module__}:{convert.__name__}:{convert.__code__.co_firstlineno}'

    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 1
    assert coordinates[0].converter_id == converter.get_function_id()
    assert changer.apply_coordinate(coordinates[0]) == '1 - 2'


@pytest.mark.parametrize('callback_kind', ['callable_object', 'bound_method'])
def test_partial_of_callable_object_or_bound_method_is_supported(callback_kind):
    """
    A functools.partial wrapping a callable object or bound method is supported.

    The function id falls back to the underlying `__call__` or method, and the
    coordinate applies normally.
    """
    class ConverterCallable:
        def convert(self, node: Add):
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

        __call__ = convert

    if callback_kind == 'callable_object':
        callback = ConverterCallable()
        expected_function = ConverterCallable.__call__
    else:
        callback = ConverterCallable().convert
        expected_function = callback

    changer = Changer('1 + 2')
    converter = changer.converter(partial(callback))
    coordinates = list(changer.iterate_coordinates())

    assert converter.get_function_id() == f'{expected_function.__module__}:{expected_function.__name__}:{expected_function.__code__.co_firstlineno}'
    assert len(coordinates) == 1
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1 - 2']


def test_partial_wrapping_a_converter_is_rejected():
    """
    A partial that wraps an existing Converter is rejected as a double wrapper.

    Direct construction, Changer registration and Collector registration all raise
    ConverterWrappingError.
    """
    def function(node: Add):
        return node

    converter = Converter(function)
    changer = Changer('1 + 2')
    collector = Collector()
    message = match('A converter cannot be wrapped in another converter.')

    with pytest.raises(ConverterWrappingError, match=message):
        Converter(partial(converter))

    with pytest.raises(ConverterWrappingError, match=message):
        changer.converter(partial(converter))
    assert not changer.converters_by_types

    with pytest.raises(ConverterWrappingError, match=message):
        collector.converter(partial(converter))
    assert collector._converters == []


def test_nested_partial_subclass_reports_underlying_function_id():
    """
    A partial subclass that keeps a nested partial in `func` is unwrapped recursively.

    The resulting `Converter` reports the id of the underlying function.
    """
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    partial_wrapper = NestedPartial(partial(convert))
    changer = Changer('1 + 2')
    converter = changer.converter(partial_wrapper)

    assert converter.get_function_id() == f'{convert.__module__}:{convert.__name__}:{convert.__code__.co_firstlineno}'
    coordinates = list(changer.iterate_coordinates())
    assert [coordinate.converter_id for coordinate in coordinates] == [converter.get_function_id()]
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1 - 2']


def test_nested_partial_subclass_hiding_converter_is_rejected():
    """
    A Converter hidden under nested partial-subclass layers is rejected.
    """
    def convert(node: Add):
        return node

    converter = Converter(convert)
    message = match('A converter cannot be wrapped in another converter.')

    with pytest.raises(ConverterWrappingError, match=message):
        Converter(NestedPartial(converter))

    with pytest.raises(ConverterWrappingError, match=message):
        Converter(NestedPartial(NestedPartial(converter)))


@pytest.mark.parametrize('callback_kind', ['converter', 'node_type_filter', 'bound_filter'])
def test_keyword_only_optional_context_receives_context_with_registered_meta(callback_kind):
    """`def callback(node, *, context=None)` receives a real `Context` and its registered metadata as a converter, node-type filter, or bound filter."""
    changer = Changer('1 + 2')
    received_contexts = []
    registered_meta = {'kind': callback_kind}

    if callback_kind == 'converter':
        @changer.converter(meta=registered_meta)
        def convert_callback(node: Add, *, context=None):
            received_contexts.append(context)
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

        coordinates = list(changer.iterate_coordinates())
        assert len(coordinates) == 1
        assert changer.apply_coordinate(coordinates[0]) == '1 - 2'
    elif callback_kind == 'node_type_filter':
        @changer.converter
        def convert_identity(node: Add):
            return node

        @changer.filter(meta=registered_meta)
        def filter_callback(node: Add, *, context=None):  # noqa: ARG001
            received_contexts.append(context)
            return True

        coordinates = list(changer.iterate_coordinates())
        assert len(coordinates) == 1
        assert changer.filters_by_types[Add][0].function is filter_callback
        assert convert_identity.filters == []
        assert changer.apply_coordinate(coordinates[0]) == '1 + 2'
    else:
        @changer.converter
        def convert_bound(node: Add):
            return node

        @convert_bound.filter(meta=registered_meta)
        def bound_callback(node: Add, *, context=None):  # noqa: ARG001
            received_contexts.append(context)
            return True

        coordinates = list(changer.iterate_coordinates())
        assert len(coordinates) == 1
        assert convert_bound.filters[0].function is bound_callback
        assert not changer.filters_by_types
        assert changer.apply_coordinate(coordinates[0]) == '1 + 2'

    assert len(received_contexts) == 1
    assert isinstance(received_contexts[0], Context)
    assert received_contexts[0].meta == registered_meta
    assert received_contexts[0].meta is not registered_meta


def test_converter_preserves_standard_function_metadata():
    """`Converter` stays transparent to standard introspection: it exposes `__wrapped__`, and its name, qualified name, module, docstring, and `inspect.signature` match the original function."""
    def convert(node: Add):
        """Convert one node."""
        return node

    converter = Changer('1 + 2').converter(convert)

    assert converter.__wrapped__ is convert  # type: ignore[attr-defined]
    assert unwrap(converter) is convert
    assert converter.__name__ == convert.__name__  # type: ignore[attr-defined]
    assert converter.__qualname__ == convert.__qualname__  # type: ignore[attr-defined]
    assert converter.__module__ == convert.__module__  # type: ignore[attr-defined]
    assert converter.__doc__ == convert.__doc__  # type: ignore[attr-defined]
    assert signature(converter) == signature(convert)

    node = Add()
    assert converter(node) is node


def test_converter_does_not_copy_function_attributes_onto_instance():
    """Custom attributes stay on the original callable and remain available through `function`/`__wrapped__`; same-named attributes do not shadow the Converter's `function`, `meta`, or `filters`."""
    def convert(node: Add):
        return node

    marker = object()
    convert.__dict__.update(marker=marker, function='shadow', meta='shadow', filters='shadow')

    converter = Converter(convert)

    assert converter.function is convert
    assert converter.meta is None
    assert converter.filters == []
    assert converter.function.__dict__['marker'] is marker
    assert unwrap(converter).__dict__['marker'] is marker
    assert not hasattr(converter, 'marker')


def test_decorator_factories_do_not_register_until_applied():
    """
    Calling a decorator factory without a callback returns a callable decorator.

    Nothing is registered until that decorator is applied to a function.
    """
    changer = Changer('1 + 2')

    @changer.converter
    def convert(node: Add):
        return node

    assert changer.converters_by_types == {Add: [convert]}
    assert not changer.filters_by_types

    collector = Collector()

    assert callable(changer.converter())
    assert callable(changer.filter())
    assert callable(convert.filter())
    assert callable(collector.converter())
    assert callable(collector.filter())

    assert changer.converters_by_types == {Add: [convert]}
    assert not changer.filters_by_types
    assert convert.filters == []
    assert collector._converters == []
    assert collector._filters == []

    def late_converter_function(node: Add):
        return node

    registered_late_converter = changer.converter()(late_converter_function)

    assert isinstance(registered_late_converter, Converter)
    assert changer.converters_by_types == {Add: [convert, registered_late_converter]}

    def late_filter(node: Add) -> bool:  # noqa: ARG001
        return True

    registered_late_filter = changer.filter()(late_filter)

    assert registered_late_filter is late_filter
    assert len(changer.filters_by_types[Add]) == 1
    assert changer.filters_by_types[Add][0].function is late_filter


def test_non_callable_callbacks_are_rejected_atomically():
    """Direct construction and the Changer, Collector, and converter-bound filter registration paths reject non-callable objects without changing existing registrations."""
    changer = Changer('1 + 2')
    message = match('A function that takes a CST node and a context is expected.')
    non_callable: Any = 42

    @changer.converter
    def existing_converter(node: Add):
        return node

    @changer.filter
    def existing_filter(node: Add) -> bool:  # noqa: ARG001
        return True

    @existing_converter.filter
    def existing_bound_filter(node: Add) -> bool:  # noqa: ARG001
        return True

    existing_bound_filters = list(existing_converter.filters)

    collector = Collector()

    @collector.converter
    def collector_converter(node: Add):
        return node

    @collector.filter
    def collector_filter(node: Add) -> bool:  # noqa: ARG001
        return True

    converters_snapshot = {node_type: list(converters) for node_type, converters in changer.converters_by_types.items()}
    filters_snapshot = {node_type: list(filters) for node_type, filters in changer.filters_by_types.items()}
    collector_converters_snapshot = list(collector._converters)
    collector_filters_snapshot = list(collector._filters)

    with pytest.raises(SignatureMismatchError, match=message):
        Converter(non_callable)

    with pytest.raises(SignatureMismatchError, match=message):
        changer.converter(non_callable)

    with pytest.raises(SignatureMismatchError, match=message):
        changer.converter()(non_callable)

    with pytest.raises(SignatureMismatchError, match=message):
        changer.filter(non_callable)

    with pytest.raises(SignatureMismatchError, match=message):
        changer.filter()(non_callable)

    with pytest.raises(SignatureMismatchError, match=message):
        existing_converter.filter(non_callable)

    with pytest.raises(SignatureMismatchError, match=message):
        collector.converter(non_callable)

    with pytest.raises(SignatureMismatchError, match=message):
        collector.converter()(non_callable)

    with pytest.raises(SignatureMismatchError, match=message):
        collector.filter(non_callable)

    with pytest.raises(SignatureMismatchError, match=message):
        collector.filter()(non_callable)

    with pytest.raises(SignatureMismatchError, match=message):
        existing_converter.filter()(non_callable)

    assert changer.converters_by_types == converters_snapshot
    assert changer.filters_by_types == filters_snapshot
    assert existing_converter.filters == existing_bound_filters
    assert existing_bound_filters[0].function is existing_bound_filter
    assert collector._converters == collector_converters_snapshot
    assert collector._filters == collector_filters_snapshot


def test_bound_method_converter_supports_bound_filter():
    """
    A bound method is a supported converter callback.

    Its id is derived from the method definition, bound filters can be attached,
    and coordinate application calls the method on its instance.
    """
    class ConverterOwner:
        def convert(self, node: Add):
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    changer = Changer('1 + 2')
    owner = ConverterOwner()
    converter = changer.converter(owner.convert)
    filter_calls = []

    assert converter.function.__self__ is owner

    @converter.filter
    def allow(node: Add) -> bool:
        filter_calls.append(node)
        return True

    assert [wrapper.function for wrapper in converter.filters] == [allow]
    assert not changer.filters_by_types
    assert converter.get_function_id() == f'{owner.convert.__module__}:{owner.convert.__name__}:{owner.convert.__code__.co_firstlineno}'

    coordinates = list(changer.iterate_coordinates())

    assert len(filter_calls) == 1
    assert isinstance(filter_calls[0], Add)
    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == '1 - 2'


def test_context_dispatch_for_variadic_callbacks():
    """Variadic callbacks receive `Context` according to their signature: keyword-only `context` wins over `*args`, `**kwargs`-only callbacks receive only the node, and mixed varargs receive it positionally."""
    base_context = make_add_context({'caller': 1})
    node = Add()
    calls = {}

    def mixed_varargs(*args, **kwargs):
        calls['mixed_varargs'] = (args, kwargs)
        return args[0]

    def pure_varargs(*args):
        calls['pure_varargs'] = args
        return args[0]

    def varargs_after_node(node, *args, **kwargs):
        calls['varargs_after_node'] = ((node, *args), kwargs)
        return node

    def kwargs_after_node(node, **kwargs):
        calls['kwargs_after_node'] = ((node,), kwargs)
        return node

    def varargs_with_keyword_context(node, *args, context=None):
        calls['varargs_with_keyword_context'] = ((node, *args), {'context': context})
        return node

    for callback in (
        mixed_varargs,
        pure_varargs,
        varargs_after_node,
        kwargs_after_node,
        varargs_with_keyword_context,
    ):
        assert Converter(callback).call_with_context(node, base_context) is node

    mixed_varargs_args, mixed_varargs_kwargs = calls['mixed_varargs']
    assert len(mixed_varargs_args) == 2
    assert mixed_varargs_args[0] is node
    assert isinstance(mixed_varargs_args[1], Context)
    assert mixed_varargs_args[1].position is base_context.position
    assert mixed_varargs_args[1].meta is None
    assert mixed_varargs_kwargs == {}

    pure_varargs_args = calls['pure_varargs']
    assert len(pure_varargs_args) == 2
    assert pure_varargs_args[0] is node
    assert isinstance(pure_varargs_args[1], Context)
    assert pure_varargs_args[1].position is base_context.position
    assert pure_varargs_args[1].meta is None

    after_node_args, after_node_kwargs = calls['varargs_after_node']
    assert len(after_node_args) == 2
    assert after_node_args[0] is node
    assert isinstance(after_node_args[1], Context)
    assert after_node_args[1].position is base_context.position
    assert after_node_args[1].meta is None
    assert after_node_kwargs == {}

    node_only_args, node_only_kwargs = calls['kwargs_after_node']
    assert node_only_args == (node,)
    assert node_only_kwargs == {}

    keyword_context_args, keyword_context_kwargs = calls['varargs_with_keyword_context']
    assert keyword_context_args == (node,)
    assert set(keyword_context_kwargs) == {'context'}
    keyword_context = keyword_context_kwargs['context']
    assert isinstance(keyword_context, Context)
    assert keyword_context.position is base_context.position
    assert keyword_context.meta is None


@pytest.mark.parametrize('signature_kind', ['positional_or_keyword', 'positional_only'])
def test_required_positional_parameter_takes_context(signature_kind):
    """
    A required positional parameter takes precedence over keyword-only context injection.

    The two-positional call shape passes Context into the required parameter, and
    keyword-only `context` keeps its default for both positional-or-keyword and
    positional-only parameters.
    """
    changer = Changer('1 + 2')
    received_arguments = []

    if signature_kind == 'positional_or_keyword':
        @changer.converter
        def convert(node: Add, extra, *, context='unset'):
            received_arguments.append((extra, context))
            return node
    else:
        @changer.converter
        def convert(node: Add, extra, /, *, context='unset'):
            received_arguments.append((extra, context))
            return node

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == '1 + 2'

    assert len(received_arguments) == 1
    extra, context = received_arguments[0]
    assert isinstance(extra, Context)
    assert extra.meta is None
    assert extra.position.source == '1 + 2'
    assert extra.position.coordinate.class_name == 'Add'
    assert context == 'unset'


@pytest.mark.parametrize('signature_kind', ['positional_or_keyword', 'positional_only'])
@pytest.mark.parametrize('default', [None, 0, 'sentinel'], ids=['none', 'zero', 'string'])
def test_optional_positional_parameter_keeps_default_with_keyword_only_context(signature_kind, default):
    """
    An optional positional parameter does not disable keyword-only context injection.

    Context is delivered through the keyword-only parameter; the optional
    positional parameter keeps its default in both signature forms and for all
    tested default values.
    """
    changer = Changer('1 + 2')
    received_arguments = []

    if signature_kind == 'positional_or_keyword':
        @changer.converter
        def convert(node: Add, extra=default, *, context='unset'):
            received_arguments.append((extra, context))
            return node
    else:
        @changer.converter
        def convert(node: Add, extra=default, /, *, context='unset'):
            received_arguments.append((extra, context))
            return node

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == '1 + 2'
    assert len(received_arguments) == 1
    extra, context = received_arguments[0]
    assert extra == default
    assert isinstance(context, Context)
    assert context.meta is None
    assert context.position.source == '1 + 2'


@pytest.mark.parametrize('registration_kind', ['converter', 'filter'])
@pytest.mark.parametrize('callback_kind', ['callable_object', 'bound_method'])
def test_callable_objects_and_bound_methods_with_invalid_annotation_are_rejected(registration_kind, callback_kind):
    """
    Callable objects and bound methods with non-CST node annotations are rejected
    without leaving registrations behind.
    """
    class InvalidCallable:
        def __call__(self, node: object):
            return node

    class InvalidOwner:
        def callback(self, node: object):
            return node

    callback = InvalidCallable() if callback_kind == 'callable_object' else InvalidOwner().callback
    changer = Changer('1 + 2')
    register = changer.converter if registration_kind == 'converter' else changer.filter
    with pytest.raises(
        TypeError,
        match=match('The type annotation for the first argument of the function must be descended from the libcst.CSTNode class.'),
    ):
        register(callback)

    assert not changer.converters_by_types
    assert not changer.filters_by_types


@pytest.mark.parametrize('registration_kind', ['converter', 'filter'])
@pytest.mark.parametrize(
    'invalid_callback',
    [
        pytest.param(no_arguments_function, id='function-no-arguments'),
        pytest.param(three_arguments_function, id='function-three-arguments'),
        pytest.param(NoArgumentsCallable(), id='callable-object-no-arguments'),
        pytest.param(ThreeArgumentsCallable(), id='callable-object-three-arguments'),
        pytest.param(kwargs_only_callback, id='kwargs-only'),
        pytest.param(keyword_only_node_callback, id='keyword-only-node'),
    ],
)
def test_collector_rejects_invalid_callbacks(registration_kind, invalid_callback, unfold):
    """
    Collector registration rejects callbacks with unsupported arity or no
    positional node parameter, without leaving registrations behind.
    """
    collector = Collector()
    register = collector.converter if registration_kind == 'converter' else collector.filter
    with pytest.raises(
        SignatureMismatchError,
        match=match('A function that takes a CST node and a context is expected.'),
    ):
        unfold(register)(invalid_callback)

    assert collector._converters == []
    assert collector._filters == []


def test_converter_accepts_one_and_two_argument_callbacks_and_applies_both():
    """One- and two-argument converters registered for the same Add node produce independent coordinates; applied to `1 + 2`, they yield `1 - 2` and `1 * 2`."""
    calls = []

    def convert_with_one_argument(node: Add):
        calls.append('one')
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    def convert_with_two_arguments(node: Add, context):
        calls.append('two')
        assert isinstance(context, Context)
        return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    changer = Changer('1 + 2')
    changer.converter(convert_with_one_argument)
    changer.converter(convert_with_two_arguments)

    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 2
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1 - 2', '1 * 2']
    assert calls == ['one', 'two']


@pytest.mark.parametrize(
    'callback',
    [
        lambda node, *, context: node,  # noqa: ARG005
        lambda node, *, extra: node,  # noqa: ARG005
    ],
    ids=['context', 'extra'],
)
@pytest.mark.parametrize('registration_kind', ['converter', 'filter', 'bound_filter', 'converter_constructor', 'collector_converter', 'collector_filter'])
def test_required_keyword_only_parameter_is_rejected(callback, registration_kind):
    """
    A mandatory keyword-only parameter is rejected during construction or registration.

    Both callbacks accept one positional node argument but require an additional
    keyword-only parameter (`context` or `extra`). `CallableWrapper` validates
    the call shape before inspecting node annotations: since the callback cannot
    be called with the node alone, every registration path raises
    `SignatureMismatchError`. The name `context` is not special without a default.
    """
    changer = Changer('1 + 2')
    message = match('A function that takes a CST node and a context is expected.')

    if registration_kind == 'converter':
        with pytest.raises(SignatureMismatchError, match=message):
            changer.converter(callback)
        assert not changer.converters_by_types
    elif registration_kind == 'filter':
        with pytest.raises(SignatureMismatchError, match=message):
            changer.filter(callback)
        assert not changer.filters_by_types
    elif registration_kind == 'bound_filter':
        @changer.converter
        def convert(node: Add):
            return node

        with pytest.raises(SignatureMismatchError, match=message):
            convert.filter(callback)
        assert convert.filters == []
    elif registration_kind == 'converter_constructor':
        with pytest.raises(SignatureMismatchError, match=message):
            Converter(callback)
    elif registration_kind == 'collector_converter':
        collector = Collector()
        with pytest.raises(SignatureMismatchError, match=message):
            collector.converter(callback)
        assert collector._converters == []
    else:
        collector = Collector()
        with pytest.raises(SignatureMismatchError, match=message):
            collector.filter(callback)
        assert collector._filters == []


@pytest.mark.parametrize('filter_scope', ['node_type', 'bound_filter'])
@pytest.mark.parametrize('callback_kind', ['callable_object', 'bound_method'])
@pytest.mark.parametrize('context_style', ['positional', 'keyword_only'])
@pytest.mark.parametrize('filter_result', [True, False], ids=['allow', 'reject'])
def test_callable_object_and_bound_method_can_be_filters(filter_scope, callback_kind, context_style, filter_result):
    """
    Callable objects and bound methods are accepted as filters.

    Both positional and keyword-only Context forms receive a real Context, and
    both allowing and rejecting results gate the converter through either
    registration path.
    """
    filter_calls = []
    converter_calls = []

    class ResultFilter:
        def __call__(self, node: Add, context: Context) -> bool:
            filter_calls.append((node, context))
            return filter_result

    class KeywordResultFilter:
        def __call__(self, node: Add, *, context=None) -> bool:
            filter_calls.append((node, context))
            return filter_result

    class FilterOwner:
        def filter_node(self, node: Add, context: Context) -> bool:
            filter_calls.append((node, context))
            return filter_result

        def keyword_filter_node(self, node: Add, *, context=None) -> bool:
            filter_calls.append((node, context))
            return filter_result

    changer = Changer('1 + 2')

    @changer.converter
    def convert(node: Add):
        converter_calls.append(node)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    if callback_kind == 'callable_object':
        filter_callback = ResultFilter() if context_style == 'positional' else KeywordResultFilter()
    else:
        owner = FilterOwner()
        filter_callback = owner.filter_node if context_style == 'positional' else owner.keyword_filter_node

    if filter_scope == 'node_type':
        assert changer.filter(filter_callback) is filter_callback
        assert changer.filters_by_types[Add][0].function is filter_callback
        assert convert.filters == []
    else:
        assert convert.filter(filter_callback) is filter_callback
        assert convert.filters[0].function is filter_callback
        assert not changer.filters_by_types

    coordinates = list(changer.iterate_coordinates())

    assert len(filter_calls) == 1
    seen_node, context = filter_calls[0]
    assert isinstance(seen_node, Add)
    assert isinstance(context, Context)
    assert context.meta is None
    assert context.position.source == '1 + 2'

    if filter_result:
        assert len(coordinates) == 1
        assert changer.apply_coordinate(coordinates[0]) == '1 - 2'
        assert len(converter_calls) == 1
    else:
        assert coordinates == []
        assert converter_calls == []


@pytest.mark.parametrize('filter_scope', ['node_type', 'bound_filter'])
@pytest.mark.parametrize('allowed', [True, False], ids=['allow', 'reject'])
def test_partial_filter_is_supported(allowed, filter_scope):
    """
    A functools.partial with a valid remaining signature is accepted as a filter.

    The partial is called once and gates the converter through node-type or
    converter-bound registration.
    """
    changer = Changer('1 + 2')
    seen_nodes = []

    @changer.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    def predicate(node, allowed_value):
        seen_nodes.append(node)
        return allowed_value

    filter_function = partial(predicate, allowed_value=allowed)
    if filter_scope == 'node_type':
        changer.filter(filter_function)
        assert changer.filters_by_types[CSTNode][0].function is filter_function
    else:
        convert.filter(filter_function)
        assert convert.filters[0].function is filter_function

    coordinates = list(changer.iterate_coordinates())
    expected_sources = ['1 - 2'] if allowed else []

    assert len(seen_nodes) == 1
    assert isinstance(seen_nodes[0], Add)
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == expected_sources


def test_callable_object_without_annotation_is_catch_all_filter():
    """Without a `__call__` annotation, the filter still registers as `CSTNode` and sees every visited node."""
    received_nodes = []

    class AllowAll:
        def __call__(self, node):
            received_nodes.append(node)
            return True

    changer = Changer('1 + 2')

    @changer.converter
    def convert(node: CSTNode):
        return node

    filter_object = AllowAll()
    changer.filter(filter_object)

    assert set(changer.filters_by_types) == {CSTNode}
    assert [wrapper.function for wrapper in changer.filters_by_types[CSTNode]] == [filter_object]
    visited_nodes = collect_nodes(changer.module)
    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == len(visited_nodes)
    assert [coordinate.class_name for coordinate in coordinates] == [type(node).__name__ for node in visited_nodes]
    assert {coordinate.converter_id for coordinate in coordinates} == {convert.get_function_id()}
    assert len(received_nodes) == len(visited_nodes)
    assert all(actual.deep_equals(expected) for actual, expected in zip(received_nodes, visited_nodes))


def test_changer_filter_direct_meta_registration():
    """The callback receives the supplied meta during discovery."""
    changer = Changer('1 + 2')
    received_meta = []
    filter_meta = {'key': 'value'}

    @changer.converter
    def convert(node: Add):
        return node

    def predicate(node: Add, context: Context) -> bool:  # noqa: ARG001
        received_meta.append(context.meta)
        return True

    assert changer.filter(predicate, meta=filter_meta) is predicate
    list(changer.iterate_coordinates())

    assert received_meta == [filter_meta]
    assert received_meta[0] is not filter_meta


@pytest.mark.parametrize(
    ('parameter_name', 'expects_context'),
    [('context', True), ('ctx', False)],
    ids=['context', 'other-name'],
)
def test_only_keyword_only_parameter_named_context_receives_context(parameter_name, expects_context):
    """A keyword-only parameter receives `Context` only when named `context`; a differently named one keeps its default."""
    changer = Changer('1 + 2')
    received_values = []

    if parameter_name == 'context':
        @changer.converter
        def convert(node: Add, *, context=None):
            received_values.append(context)
            return node
    else:
        @changer.converter
        def convert(node: Add, *, ctx='unset'):
            received_values.append(ctx)
            return node

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == '1 + 2'

    assert len(received_values) == 1
    if expects_context:
        assert isinstance(received_values[0], Context)
        assert received_values[0].position.source == '1 + 2'
    else:
        assert received_values[0] == 'unset'


def test_keyword_only_context_can_follow_another_keyword_only_parameter():
    """A keyword-only `context` receives a real `Context` even when another keyword-only parameter precedes it; that parameter keeps its default."""
    changer = Changer('1 + 2')
    received_arguments = []

    @changer.converter
    def convert(node: Add, *, marker='default', context=None):
        received_arguments.append((marker, context))
        return node

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == '1 + 2'

    assert len(received_arguments) == 1
    marker, context = received_arguments[0]
    assert marker == 'default'
    assert isinstance(context, Context)
    assert context.position.source == '1 + 2'


def test_partial_converter_receives_keyword_only_context():
    """
    A partial converter still receives keyword-only Context injection.

    The partial supplies a regular keyword argument while the wrapper supplies a
    real Context through the reserved keyword-only parameter.
    """
    received_callback_arguments = []

    def convert(node: Add, *, context=None, marker='default'):
        received_callback_arguments.append((context, marker))
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    changer = Changer('1 + 2')
    changer.converter(partial(convert, marker='bound'))
    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == '1 - 2'
    assert len(received_callback_arguments) == 1
    context, marker = received_callback_arguments[0]
    assert isinstance(context, Context)
    assert context.meta is None
    assert context.position.source == '1 + 2'
    assert marker == 'bound'


def test_partial_with_bound_context_receives_runtime_context():
    """
    When a partial binds the reserved `context` parameter, the runtime `Context`
    overrides that bound value.
    """
    received_contexts = []

    def convert(node: Add, context=None):
        received_contexts.append(context)
        return node

    changer = Changer('1 + 2')
    changer.converter(partial(convert, context='bound'))
    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == '1 + 2'

    assert len(received_contexts) == 1
    assert isinstance(received_contexts[0], Context)
    assert received_contexts[0].position.source == '1 + 2'


def test_positional_only_context_parameter_is_passed_positionally():
    """A positional-only `context` receives `Context` positionally, not through keyword-only injection."""
    changer = Changer('1 + 2')
    received_contexts = []

    @changer.converter
    def convert(node: Add, context: Context, /):
        received_contexts.append(context)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == '1 - 2'
    assert len(received_contexts) == 1
    assert isinstance(received_contexts[0], Context)
    assert received_contexts[0].meta is None
    assert received_contexts[0].position.source == '1 + 2'
    assert received_contexts[0].position.coordinate.class_name == 'Add'


def test_positional_only_node_receives_keyword_only_context():
    """
    A positional-only node parameter does not disable keyword-only Context
    injection.
    """
    changer = Changer('1 + 2')
    received_contexts = []

    @changer.converter
    def convert(node: Add, /, *, context=None):
        received_contexts.append(context)
        return node

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == '1 + 2'
    assert len(received_contexts) == 1
    assert isinstance(received_contexts[0], Context)
    assert received_contexts[0].position.source == '1 + 2'
    assert received_contexts[0].position.coordinate.class_name == 'Add'


def test_mixed_union_annotation_maps_cst_and_shortcut_members():
    """
    A union containing a CST type and a shortcut type registers both mappings.

    The `Add` union member maps to `Add`, and the `int` shortcut maps to
    `Integer`. For `1 + 2`, coordinates are emitted for both `Integer`
    occurrences and the `Add` node.
    """
    called_types = []

    def convert(node: Union[Add, int]):
        called_types.append(type(node))
        return node

    changer = Changer('1 + 2')
    converter = changer.converter(convert)

    assert changer.converters_by_types[Add] == [converter]
    assert changer.converters_by_types[Integer] == [converter]
    coordinates = list(changer.iterate_coordinates())

    assert [coordinate.class_name for coordinate in coordinates] == ['Integer', 'Add', 'Integer']
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1 + 2'] * 3
    assert called_types == [Integer, Add, Integer]


@pytest.mark.parametrize(
    ('annotation', 'expected_node_type'),
    [
        pytest.param(int, Integer, id='int-to-integer'),
        pytest.param(float, Float, id='float-to-float'),
        pytest.param(str, SimpleString, id='str-to-simple-string'),
    ],
)
def test_builtin_shortcut_maps_only_to_its_node_type(annotation, expected_node_type):
    """
    Built-in shortcut annotations map to exactly one LibCST node type.

    The mapping is checked directly, so accidentally widening int/float/str to
    additional node types fails immediately.
    """
    def callback(node):
        return node

    callback.__annotations__['node'] = annotation

    assert CallableWrapper(callback).first_node_annotations == [expected_node_type]

    changer = Changer('x = 1')
    converter = changer.converter(callback)

    assert set(changer.converters_by_types) == {expected_node_type}
    assert changer.converters_by_types[expected_node_type] == [converter]


@pytest.mark.parametrize('registration_path', ['changer', 'collector'])
def test_callable_object_without_annotation_is_catch_all_converter(registration_path):
    """An unannotated `__call__` makes a catch-all converter through either registration path; it applies to every CST node."""
    received_nodes = []

    class CatchAll:
        def __call__(self, node):
            received_nodes.append(node)
            return node

    if registration_path == 'changer':
        changer = Changer('1 + 2')
        converter = changer.converter(CatchAll())
    else:
        collector = Collector()
        converter = collector.converter(CatchAll())
        changer = Changer('1 + 2', collector=collector)

    visited_nodes = collect_nodes(changer.module)
    coordinates = list(changer.iterate_coordinates())

    assert changer.converters_by_types[CSTNode] == [converter]
    assert set(changer.converters_by_types) == {CSTNode}
    assert {coordinate.converter_id for coordinate in coordinates} == {converter.get_function_id()}
    assert len(coordinates) == len(visited_nodes)
    assert [coordinate.class_name for coordinate in coordinates] == [type(node).__name__ for node in visited_nodes]
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1 + 2'] * len(coordinates)
    assert len(received_nodes) == len(visited_nodes)
    assert all(received_node.deep_equals(visited) for received_node, visited in zip(received_nodes, visited_nodes))


def test_keyword_only_context_injection_does_not_depend_on_none_default():
    """
    Keyword-only context injection works with a non-None default value.

    The wrapper detects the parameter by name and kind, not by its default.
    """
    changer = Changer('1 + 2')
    received_contexts = []

    @changer.converter
    def convert(node: Add, *, context='sentinel'):
        received_contexts.append(context)
        return node

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == '1 + 2'

    assert len(received_contexts) == 1
    assert isinstance(received_contexts[0], Context)
    assert received_contexts[0].position.source == '1 + 2'
    assert received_contexts[0].position.coordinate.class_name == 'Add'


@pytest.mark.parametrize('binding_kind', ['positional', 'keyword', 'nested_subclass'])
@pytest.mark.parametrize(
    'registration_kind',
    ['constructor', 'changer_converter', 'collector_converter', 'changer_filter', 'collector_filter', 'bound_filter'],
)
def test_partial_with_bound_node_is_rejected(binding_kind, registration_kind):
    """A partial binding the node positionally or by keyword, and a partial subclass exposing its inner partial through `func`, are rejected at construction or registration. The test checks only the public error contract, not which internal validation rejects each shape."""
    def convert(node: Add, context=None):  # noqa: ARG001
        return node

    if binding_kind == 'positional':
        callback = partial(convert, Add())
    elif binding_kind == 'keyword':
        callback = partial(convert, node=Add())
    else:
        callback = NestedPartial(partial(convert, Add()))
    message = match('A function that takes a CST node and a context is expected.')

    if registration_kind == 'constructor':
        with pytest.raises(SignatureMismatchError, match=message):
            Converter(callback)
    elif registration_kind == 'changer_converter':
        changer = Changer('1 + 2')
        with pytest.raises(SignatureMismatchError, match=message):
            changer.converter(callback)
        assert not changer.converters_by_types
    elif registration_kind == 'collector_converter':
        collector = Collector()
        with pytest.raises(SignatureMismatchError, match=message):
            collector.converter(callback)
        assert collector._converters == []
    elif registration_kind == 'changer_filter':
        changer = Changer('1 + 2')
        with pytest.raises(SignatureMismatchError, match=message):
            changer.filter(callback)
        assert not changer.filters_by_types
    elif registration_kind == 'collector_filter':
        collector = Collector()
        with pytest.raises(SignatureMismatchError, match=message):
            collector.filter(callback)
        assert collector._filters == []
    else:
        changer = Changer('1 + 2')

        @changer.converter
        def existing(node: Add):
            return node

        with pytest.raises(SignatureMismatchError, match=message):
            existing.filter(callback)
        assert existing.filters == []


@pytest.mark.parametrize('callback_kind', ['function', 'callable_object', 'bound_method'])
def test_duplicate_function_id_converters_apply_their_own_meta(callback_kind):
    """Two `Converter` objects with the same function id stay independent: the second gets `#1` while both report the same base id, and each coordinate invokes its converter with its own meta and result."""
    changer = Changer('1 + 2')

    def convert_with_operation(node: Add, context: Context):
        assert context.meta is not None
        if context.meta['operation'] == 'subtract':
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)
        return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    class CallableConverter:
        def __call__(self, node: Add, context: Context):
            return convert_with_operation(node, context)

    class BoundMethodOwner:
        def convert(self, node: Add, context: Context):
            return convert_with_operation(node, context)

    if callback_kind == 'function':
        first_callback = second_callback = convert_with_operation
    elif callback_kind == 'callable_object':
        first_callback = CallableConverter()
        second_callback = CallableConverter()
    else:
        first_owner = BoundMethodOwner()
        second_owner = BoundMethodOwner()
        first_callback = first_owner.convert
        second_callback = second_owner.convert

    subtract_converter = changer.converter(first_callback, meta={'operation': 'subtract'})
    multiply_converter = changer.converter(second_callback, meta={'operation': 'multiply'})
    function_id = subtract_converter.get_function_id()

    assert multiply_converter.get_function_id() == function_id

    if callback_kind == 'function':
        assert subtract_converter.function is convert_with_operation
    elif callback_kind == 'callable_object':
        assert subtract_converter.function is first_callback
        assert multiply_converter.function is second_callback
    else:
        assert subtract_converter.function.__self__ is first_owner
        assert multiply_converter.function.__self__ is second_owner

    coordinates = list(changer.iterate_coordinates())

    assert [coordinate.converter_id for coordinate in coordinates] == [function_id, f'{function_id}#1']
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1 - 2', '1 * 2']


def test_build_converter_ids_assigns_sequential_suffixes_and_ignores_repeated_converters():
    """`build_converter_ids` assigns per-function sequential suffixes, ignores duplicates without advancing the counter, and lets registration order choose the base-id owner; empty input maps to `{}`."""
    def function(node):
        return node

    def other_function(node):
        return node

    first_converter = Converter(function)
    second_converter = Converter(function)
    third_converter = Converter(function)
    other_converter = Converter(other_function)
    other_twin = Converter(other_function)
    function_id = first_converter.get_function_id()

    assert build_converter_ids([first_converter]) == {first_converter: function_id}
    assert build_converter_ids([]) == {}

    ids = build_converter_ids([first_converter, second_converter, first_converter, third_converter, other_converter, other_twin])

    assert list(ids.items()) == [
        (first_converter, function_id),
        (second_converter, f'{function_id}#1'),
        (third_converter, f'{function_id}#2'),
        (other_converter, other_converter.get_function_id()),
        (other_twin, f'{other_converter.get_function_id()}#1'),
    ]
    reordered = build_converter_ids([third_converter, first_converter, second_converter])
    assert list(reordered.items()) == [
        (third_converter, function_id),
        (first_converter, f'{function_id}#1'),
        (second_converter, f'{function_id}#2'),
    ]


def test_same_line_lambdas_share_function_id_and_are_disambiguated():
    """Both lambdas are deliberately defined on one physical line, so they share `co_firstlineno`; `build_converter_ids` must still assign the base and `#1` ids."""
    first_lambda, second_lambda = (lambda node: node), (lambda node: node)
    first_converter = Converter(first_lambda)
    second_converter = Converter(second_lambda)
    function_id = first_converter.get_function_id()

    assert first_lambda.__code__.co_firstlineno == second_lambda.__code__.co_firstlineno
    assert function_id == second_converter.get_function_id()

    ids = build_converter_ids([first_converter, second_converter])

    assert list(ids.items()) == [
        (first_converter, function_id),
        (second_converter, f'{function_id}#1'),
    ]


def test_duplicate_function_id_keeps_suffix_when_bound_filter_rejects_middle_converter():
    """
    Collision suffixes are based on all registered converters, not only accepted ones.

    With three converters sharing one function id and the middle one rejected by
    a bound filter, the surviving third converter's coordinate keeps `#2` and
    applies with its own meta.
    """
    changer = Changer('1 + 2')
    operations = []

    def convert(node: Add, context: Context):
        assert context.meta is not None
        operations.append(context.meta['operation'])
        if context.meta['operation'] == 'first':
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)
        if context.meta['operation'] == 'middle':
            return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)
        return node

    first_converter = changer.converter(meta={'operation': 'first'})(convert)
    middle_converter = changer.converter(meta={'operation': 'middle'})(convert)
    third_converter = changer.converter(meta={'operation': 'third'})(convert)
    function_id = first_converter.get_function_id()

    assert changer.converters_by_types[Add] == [first_converter, middle_converter, third_converter]

    @middle_converter.filter
    def reject(node: Add) -> bool:  # noqa: ARG001
        return False

    coordinates = list(changer.iterate_coordinates())

    assert [coordinate.converter_id for coordinate in coordinates] == [function_id, f'{function_id}#2']
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1 - 2', '1 + 2']
    assert operations == ['first', 'third']


def test_direct_function_and_partial_share_id_and_are_disambiguated():
    """
    A direct converter and a partial of the same function share a function id.

    The partial is unwrapped to the original function, and end-to-end discovery
    gives the direct converter's coordinate the bare id and the partial
    converter's coordinate `#1`.
    """
    def function(node: Add, context: Context):
        assert context.meta is not None
        if context.meta['operation'] == 'direct':
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)
        return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    changer = Changer('1 + 2')
    direct_converter = changer.converter(meta={'operation': 'direct'})(function)
    partial_converter = changer.converter(meta={'operation': 'partial'})(partial(function))
    function_id = direct_converter.get_function_id()

    assert partial_converter.get_function_id() == function_id
    assert list(build_converter_ids([direct_converter, partial_converter]).items()) == [
        (direct_converter, function_id),
        (partial_converter, f'{function_id}#1'),
    ]

    coordinates = list(changer.iterate_coordinates())

    assert [coordinate.converter_id for coordinate in coordinates] == [function_id, f'{function_id}#1']
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1 - 2', '1 * 2']


def test_shared_function_id_is_scoped_per_node_type():
    """The same callable is registered for `Add` and `Subtract` with different annotations, so both converters share one function id; each coordinate applies the converter matching its node type."""
    received_operations = []

    def convert(node, context: Context):
        assert context.meta is not None
        received_operations.append(context.meta['operation'])
        if isinstance(node, Add):
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)
        return Add(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    convert.__annotations__['node'] = Add
    changer = Changer('1 + 2 - 3')
    add_converter = changer.converter(convert, meta={'operation': 'add'})
    convert.__annotations__['node'] = Subtract
    subtract_converter = changer.converter(convert, meta={'operation': 'subtract'})

    assert add_converter.function is subtract_converter.function is convert
    assert add_converter.get_function_id() == subtract_converter.get_function_id()
    assert changer.converters_by_types[Add] == [add_converter]
    assert changer.converters_by_types[Subtract] == [subtract_converter]

    coordinates = list(changer.iterate_coordinates())

    assert [coordinate.class_name for coordinate in coordinates] == ['Add', 'Subtract']
    assert [coordinate.converter_id for coordinate in coordinates] == [add_converter.get_function_id()] * 2
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1 - 2 - 3', '1 + 2 + 3']
    assert received_operations == ['add', 'subtract']


@pytest.mark.parametrize('second_source', ['collector', 'changer'])
def test_duplicate_function_id_is_disambiguated_across_registration_sources(second_source):
    """The second converter's coordinate gets `#1` whether the converter comes from another Collector or directly from the Changer, and both coordinates apply their own meta."""
    def convert(node: Add, context: Context):
        assert context.meta is not None
        if context.meta['operation'] == 'subtract':
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)
        return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    first_collector = Collector()
    first_converter = first_collector.converter(meta={'operation': 'subtract'})(convert)

    if second_source == 'collector':
        second_collector = Collector()
        second_converter = second_collector.converter(meta={'operation': 'multiply'})(convert)
        changer = Changer('1 + 2', collector=first_collector + second_collector)
    else:
        changer = Changer('1 + 2', collector=first_collector)
        second_converter = changer.converter(meta={'operation': 'multiply'})(convert)

    function_id = first_converter.get_function_id()
    assert second_converter.get_function_id() == function_id

    coordinates = list(changer.iterate_coordinates())

    assert [coordinate.converter_id for coordinate in coordinates] == [function_id, f'{function_id}#1']
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1 - 2', '1 * 2']


@pytest.mark.parametrize('catch_all_first', [False, True], ids=['specific-first', 'catch-all-first'])
def test_specific_and_catch_all_converters_are_disambiguated_per_node_type(catch_all_first):
    """Specific and catch-all converters sharing one function id are disambiguated per node type regardless of registration order; for other node types the catch-all keeps the base id."""
    applied_calls = []

    def convert(node: Add, replacement):
        applied_calls.append((type(node), replacement))
        if not isinstance(node, Add):
            return node
        return replacement(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    changer = Changer('1 + 2')

    if catch_all_first:
        convert.__annotations__['node'] = CSTNode
        catch_all = changer.converter(partial(convert, replacement=Multiply))
        convert.__annotations__['node'] = Add
        specific = changer.converter(partial(convert, replacement=Subtract))
    else:
        convert.__annotations__['node'] = Add
        specific = changer.converter(partial(convert, replacement=Subtract))
        convert.__annotations__['node'] = CSTNode
        catch_all = changer.converter(partial(convert, replacement=Multiply))

    assert specific.get_function_id() == catch_all.get_function_id()
    function_id = specific.get_function_id()

    coordinates = list(changer.iterate_coordinates())
    add_coordinates = [coordinate for coordinate in coordinates if coordinate.class_name == 'Add']

    assert [coordinate.converter_id for coordinate in add_coordinates] == [function_id, f'{function_id}#1']
    non_add_class_names = [coordinate.class_name for coordinate in coordinates if coordinate.class_name != 'Add']
    expected_non_add_class_names = [
        type(node).__name__ for node in collect_nodes(changer.module) if not isinstance(node, Add)
    ]
    assert non_add_class_names == expected_non_add_class_names
    assert {coordinate.converter_id for coordinate in coordinates if coordinate.class_name != 'Add'} == {function_id}
    applied_sources = [changer.apply_coordinate(coordinate) for coordinate in coordinates]
    expected_sources = [
        ('1 - 2' if coordinate.converter_id == function_id else '1 * 2')
        if coordinate.class_name == 'Add'
        else '1 + 2'
        for coordinate in coordinates
    ]

    assert applied_sources == expected_sources
    assert [node_type.__name__ for node_type, _ in applied_calls] == [coordinate.class_name for coordinate in coordinates]
    assert all(replacement is Multiply for node_type, replacement in applied_calls if node_type is not Add)
