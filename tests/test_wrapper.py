from libcst import Integer
from libcst.metadata import CodePosition, CodeRange

from cstvis import Context, Coordinate
from cstvis.dto import SourcePosition
from cstvis.wrapper import CallableWrapper


def test_repr():
    """
    Pin CallableWrapper repr as a constructor-like string using positional values.

    The repr omits default meta, renders the wrapped function by its bare name, and includes explicit meta as a second positional argument.
    """
    def function(a, b):
        ...

    assert repr(CallableWrapper(function)) == 'CallableWrapper(function)'
    assert repr(CallableWrapper(function, meta={'kek': 1234})) == "CallableWrapper(function, {'kek': 1234})"


def test_callable_wrapper_copies_meta_without_mutating_base_context():
    """
    A context-aware callback receives copied decorator meta without changing the base Context or caller-owned dictionary.
    """
    decorator_meta = {'mode': 'wrapped'}
    base_meta = {'mode': 'base'}
    coordinate = Coordinate(None, 'Integer', 1, 0, 1, 1)
    node_range = CodeRange(CodePosition(1, 0), CodePosition(1, 1))
    position = SourcePosition(coordinate, '1', node_range, lambda _node_range: (0, 1))
    base_context = Context(position, None, base_meta)
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
    assert callback_context.position is position
    assert base_context.meta is base_meta
    assert base_meta == {'mode': 'base'}
    assert wrapper.meta is decorator_meta
    assert decorator_meta == {'mode': 'wrapped'}


def test_callable_wrapper_creates_fresh_meta_for_each_invocation():
    """
    Each call receives fresh meta, isolating mutations from later calls and wrapper state.
    """
    decorator_meta = {'value': 'original'}
    coordinate = Coordinate(None, 'Integer', 1, 0, 1, 1)
    node_range = CodeRange(CodePosition(1, 0), CodePosition(1, 1))
    position = SourcePosition(coordinate, '1', node_range, lambda _node_range: (0, 1))
    base_context = Context(position, None, {'base': True})
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
    coordinate = Coordinate(None, 'Integer', 1, 0, 1, 1)
    node_range = CodeRange(CodePosition(1, 0), CodePosition(1, 1))
    position = SourcePosition(coordinate, '1', node_range, lambda _node_range: (0, 1))
    base_context = Context(position, None, {'base': True})
    received_meta = []

    def callback(node: Integer, context: Context) -> Integer:
        received_meta.append(context.meta)
        return node

    CallableWrapper(callback)(Integer('1'), base_context)

    assert received_meta == [None]
    assert base_context.meta == {'base': True}
