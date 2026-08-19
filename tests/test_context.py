from dataclasses import FrozenInstanceError
from typing import List
from unittest.mock import patch

import pytest
from full_match import match
from libcst import (
    Add,
    Assign,
    BinaryOperation,
    FunctionDef,
    Integer,
    Module,
    Multiply,
    Name,
    Parameters,
    SimpleStatementLine,
    SimpleString,
    Subtract,
    parse_module,
)
from libcst.metadata import (
    CodePosition,
    CodeRange,
    MetadataWrapper,
    WhitespaceInclusivePositionProvider,
)
from metacode import ParsedComment
from printo import describe_call as printo_describe_call

import cstvis.source_offsets as source_offsets_module
from cstvis import Changer, Context, Coordinate
from cstvis.dto import SourcePosition
from cstvis.source_offsets import SourceOffsetResolver
from cstvis.wrapper import CallableWrapper


def test_context_requires_source_position_with_resolver():
    """
    Context requires SourcePosition, which requires coordinate, source, node_range, and a resolver.
    """
    coordinate = Coordinate(None, 'Add', 1, 2, 1, 3)
    node_range = CodeRange(CodePosition(1, 1), CodePosition(1, 4))
    resolver = SourceOffsetResolver(parse_module('1 + 2'), '1 + 2', [node_range])
    position = SourcePosition(coordinate, '1 + 2', node_range, resolver)

    context = Context(position, None)

    assert context.position is position
    assert position.coordinate == coordinate
    assert position.source == '1 + 2'
    assert position.node_range == node_range
    assert position.offset_resolver is resolver
    assert context.meta is None
    with pytest.raises(TypeError, match=match("Context.__init__() missing 1 required positional argument: 'position'")):
        Context(comment=None)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match=match("SourcePosition.__init__() missing 1 required positional argument: 'offset_resolver'")):
        SourcePosition(coordinate, '1 + 2', node_range)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match=match("SourcePosition.__init__() missing 2 required positional arguments: 'node_range' and 'offset_resolver'")):
        SourcePosition(coordinate, '1 + 2')  # type: ignore[call-arg]


def test_context_is_frozen():
    """
    Context and SourcePosition are frozen to protect lazy caches, while meta remains mutable.
    """
    coordinate = Coordinate(None, 'Add', 1, 2, 1, 3)
    node_range = CodeRange(CodePosition(1, 1), CodePosition(1, 4))
    resolver = SourceOffsetResolver(parse_module('1 + 2'), '1 + 2', [node_range])
    position = SourcePosition(coordinate, '1 + 2', node_range, resolver)
    context = Context(position, None, {'key': 'value'})

    with pytest.raises(FrozenInstanceError, match=match("cannot assign to field 'source'")):
        position.source = '3 + 4'  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError, match=match("cannot assign to field 'node_range'")):
        position.node_range = CodeRange(CodePosition(1, 0), CodePosition(1, 1))  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError, match=match("cannot assign to field 'offset_resolver'")):
        position.offset_resolver = resolver  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError, match=match("cannot assign to field 'position'")):
        context.position = position  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError, match=match("cannot assign to field 'coordinate'")):
        position.coordinate = Coordinate(None, 'Add', 1, 0, 1, 1)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError, match=match("cannot assign to field 'comment'")):
        context.comment = 'replacement'  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError, match=match("cannot assign to field 'meta'")):
        context.meta = {'replacement': True}  # type: ignore[misc]

    assert position.source == '1 + 2'
    assert position.node_range == node_range
    assert position.offset_resolver is resolver
    assert position.coordinate == coordinate
    assert context.comment is None
    assert context.meta is not None
    context.meta['key'] = 'changed'
    assert context.meta == {'key': 'changed'}


def test_context_equality_includes_fields_but_ignores_derived_caches():
    """
    Equality includes Context and SourcePosition data but ignores resolvers and derived caches.
    """
    coordinate = Coordinate(None, 'Add', 1, 2, 1, 3)
    node_range = CodeRange(CodePosition(1, 1), CodePosition(1, 4))
    resolver = SourceOffsetResolver(parse_module('1 + 2'), '1 + 2', [node_range])
    other_resolver = SourceOffsetResolver(parse_module('1 + 2'), '1 + 2', [node_range])
    position = SourcePosition(coordinate, '1 + 2', node_range, resolver)
    equal_position = SourcePosition(coordinate, '1 + 2', node_range, other_resolver)
    context = Context(position, None)
    equal_context = Context(equal_position, None)

    assert context == equal_context
    assert context.position.code_before == '1'
    assert context == equal_context
    assert context.position.code_after == '2'
    assert context == equal_context
    assert context != Context(SourcePosition(coordinate, '3 + 4', node_range, resolver), None)
    different_range = CodeRange(CodePosition(1, 0), CodePosition(1, 1))
    assert context != Context(SourcePosition(coordinate, '1 + 2', different_range, resolver), None)
    different_coordinate = Coordinate(None, 'Add', 1, 0, 1, 1)
    assert context != Context(SourcePosition(different_coordinate, '1 + 2', node_range, resolver), None)
    assert context != Context(position, 'comment')
    assert context != Context(position, None, {'key': 'value'})
    assert position != object()


def test_context_repr_uses_printo_item_limit():
    """
    Nested reprs delegate ordered public data and lazy offsets to printo with item_limit=80.

    Repr truncates a long source and leaves both surrounding fragments lazy.
    """
    coordinate = Coordinate(None, 'Add', 1, 2, 1, 3)
    node_range = CodeRange(CodePosition(1, 1), CodePosition(1, 4))
    comment = 'keep this comment'
    meta = {'mode': 'test'}
    short_resolver = SourceOffsetResolver(parse_module('1 + 2'), '1 + 2', [node_range])
    short_position = SourcePosition(coordinate, '1 + 2', node_range, short_resolver)
    short_context = Context(short_position, comment, meta)
    long_source = 'x' * 200
    long_resolver = SourceOffsetResolver(parse_module(long_source), long_source, [node_range])
    long_position = SourcePosition(coordinate, long_source, node_range, long_resolver)
    long_context = Context(long_position, comment, meta)

    with patch('cstvis.dto.describe_call', wraps=printo_describe_call) as describe_call:
        short_position_repr = repr(short_position)
        long_position_repr = repr(long_position)
        short_repr = repr(short_context)
        long_repr = repr(long_context)

    assert "source='1 + 2'" in short_position_repr
    assert 'start_offset=1' in short_position_repr
    assert 'end_offset=4' in short_position_repr
    assert long_source not in long_position_repr
    assert 'source=' in long_position_repr
    assert 'position=SourcePosition(' in short_repr
    assert 'position=SourcePosition(' in long_repr
    assert short_position.__dict__['start_offset'] == 1
    assert short_position.__dict__['end_offset'] == 4
    assert long_position.__dict__['start_offset'] == 1
    assert long_position.__dict__['end_offset'] == 4
    assert 'code_before' not in short_position.__dict__
    assert 'code_after' not in short_position.__dict__
    assert 'code_before' not in long_position.__dict__
    assert 'code_after' not in long_position.__dict__
    context_calls = [call for call in describe_call.call_args_list if call.args[0] is Context]
    position_calls = [call for call in describe_call.call_args_list if call.args[0] is SourcePosition]
    assert len(context_calls) == 2
    assert len(position_calls) == 4
    short_context_call, long_context_call = context_calls
    short_position_call, long_position_call = position_calls[:2]
    assert short_context_call.args == (
        Context,
        [],
        {
            'position': short_position,
            'comment': comment,
            'meta': meta,
        },
    )
    assert long_context_call.args == (
        Context,
        [],
        {
            'position': long_position,
            'comment': comment,
            'meta': meta,
        },
    )
    assert short_position_call.args == (
        SourcePosition,
        [],
        {
            'coordinate': coordinate,
            'source': '1 + 2',
            'node_range': node_range,
            'start_offset': 1,
            'end_offset': 4,
        },
    )
    assert long_position_call.args == (
        SourcePosition,
        [],
        {
            'coordinate': coordinate,
            'source': long_source,
            'node_range': node_range,
            'start_offset': 1,
            'end_offset': 4,
        },
    )
    assert list(short_context_call.args[2]) == ['position', 'comment', 'meta']
    assert list(long_context_call.args[2]) == ['position', 'comment', 'meta']
    assert list(short_position_call.args[2]) == ['coordinate', 'source', 'node_range', 'start_offset', 'end_offset']
    assert list(long_position_call.args[2]) == ['coordinate', 'source', 'node_range', 'start_offset', 'end_offset']
    for call in describe_call.call_args_list:
        assert call.kwargs == {'item_limit': 80}


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


def test_source_position_offsets_and_fragments_are_lazy_and_cached():  # noqa: C901, PLR0915
    """
    Construction, equality, coordinate access, and metacode parsing resolve neither offsets nor fragments.

    Reading either offset performs one shared alignment without slicing, copying
    the complete source, or splitting it into lines. Fragment properties then
    cache only their own source slices.
    """
    class TrackingString(str):
        __slots__ = ('alignment_operations', 'full_iterations', 'line_materializations', 'slices', 'string_conversions')
        alignment_operations: List[str]
        full_iterations: int
        line_materializations: List[str]
        slices: List[slice]
        string_conversions: int

        def __new__(cls, value: str):  # type: ignore[no-untyped-def]
            instance = super().__new__(cls, value)
            instance.alignment_operations = []
            instance.full_iterations = 0
            instance.line_materializations = []
            instance.slices = []
            instance.string_conversions = 0
            return instance

        def __getitem__(self, key):  # type: ignore[no-untyped-def]
            if isinstance(key, slice):
                self.slices.append(key)
            return super().__getitem__(key)

        def __iter__(self):  # type: ignore[no-untyped-def]
            self.full_iterations += 1
            return super().__iter__()

        def __str__(self) -> str:
            self.string_conversions += 1
            return super().__str__()

        def find(self, substring, *args):  # type: ignore[no-untyped-def]
            self.alignment_operations.append('find')
            return super().find(substring, *args)

        def startswith(self, prefix, *args):  # type: ignore[no-untyped-def]
            self.alignment_operations.append('startswith')
            return super().startswith(prefix, *args)

        def split(self, separator=None, maxsplit=-1):  # type: ignore[no-untyped-def]
            self.line_materializations.append('split')
            return super().split(separator, maxsplit)

        def splitlines(self, keepends=False):  # type: ignore[no-untyped-def]
            self.line_materializations.append('splitlines')
            return super().splitlines(keepends)

    source = TrackingString('header\nleft + right\n')
    coordinate = Coordinate(None, 'Add', 2, 5, 2, 6)
    node_range = CodeRange(CodePosition(2, 4), CodePosition(2, 7))
    resolver = SourceOffsetResolver(parse_module(source), source, [node_range])
    alignment_ranges = []
    resolve_offsets = SourceOffsetResolver.__call__

    def track_alignment(source_offsets, requested_range):  # type: ignore[no-untyped-def]
        alignment_ranges.append(requested_range)
        return resolve_offsets(source_offsets, requested_range)

    with patch.object(SourceOffsetResolver, '__call__', track_alignment):
        position = SourcePosition(coordinate, source, node_range, resolver)
        equal_position = SourcePosition(coordinate, source, node_range, resolver)
        context = Context(position, 'key: action')
        equal_context = Context(equal_position, 'key: action')

        assert context == equal_context
        assert context.position.coordinate == coordinate
        assert context.comment == 'key: action'
        assert context.get_metacodes('key') == [ParsedComment(key='key', command='action', arguments=[])]
        assert alignment_ranges == []
        assert source.alignment_operations == []
        assert source.full_iterations == 0
        assert source.line_materializations == []
        assert source.slices == []
        assert source.string_conversions == 0
        assert 'start_offset' not in position.__dict__
        assert 'end_offset' not in position.__dict__
        assert 'code_before' not in position.__dict__
        assert 'code_after' not in position.__dict__

        assert context.position.start_offset == 11
        assert alignment_ranges == [node_range]
        assert source.alignment_operations
        assert source.slices == []
        assert position.__dict__['start_offset'] == 11
        assert 'end_offset' not in position.__dict__

        assert context.position.end_offset == 14
        assert alignment_ranges == [node_range, node_range]
        assert source.slices == []
        assert position.__dict__['end_offset'] == 14

        assert context.position.code_before == 'header\nleft'
        assert alignment_ranges == [node_range, node_range]
        assert source.slices == [slice(None, 11)]
        assert context.position.code_before == 'header\nleft'
        assert alignment_ranges == [node_range, node_range]
        assert source.slices == [slice(None, 11)]
        assert 'code_after' not in position.__dict__

        assert context.position.code_after == 'right\n'
        assert alignment_ranges == [node_range, node_range]
        assert source.full_iterations == 0
        assert source.line_materializations == []
        assert source.slices == [slice(None, 11), slice(14, None)]
        assert source.string_conversions == 0
        assert context.position.code_after == 'right\n'
        assert alignment_ranges == [node_range, node_range]
        assert source.slices == [slice(None, 11), slice(14, None)]


def test_source_position_maps_code_range_without_matching_node():
    """
    An in-bounds CodeRange partitions source without a matching CST node.
    """
    node_range = CodeRange(CodePosition(1, 1), CodePosition(1, 2))
    coordinate = Coordinate(None, 'manual', 1, 1, 1, 2)
    resolver = SourceOffsetResolver(parse_module('abc'), 'abc', [node_range])
    position = SourcePosition(coordinate, 'abc', node_range, resolver)

    assert position.code_before == 'a'
    assert position.node_range == node_range
    assert position.code_after == 'c'
    assert position.code_before + 'b' + position.code_after == position.source


@pytest.mark.parametrize(
    ('source', 'position', 'expected_offset'),
    [
        pytest.param('', CodePosition(1, 0), 0, id='empty-source'),
        pytest.param('x=1', CodePosition(2, 0), 3, id='virtual-eof'),
        pytest.param('x=1\n', CodePosition(2, 0), 4, id='physical-eof'),
        pytest.param('x=1\n\f', CodePosition(3, 0), 5, id='form-feed-after-code'),
        pytest.param('\ufeff', CodePosition(1, 0), 1, id='bom-only'),
        pytest.param('\ufeffx=1\n', CodePosition(2, 0), 5, id='bom-and-code'),
    ],
)
def test_source_offset_resolver_returns_exact_eof_offsets(source, position, expected_offset):
    """
    EOF positions resolve exactly to len(source), including virtual newlines and an omitted initial BOM.
    """
    node_range = CodeRange(position, position)
    module = parse_module(source)
    resolver = SourceOffsetResolver(module, source, [node_range])

    assert expected_offset == len(source)
    assert resolver(node_range) == (expected_offset, expected_offset)


def test_source_offset_resolver_batches_unique_ranges_and_caches_codegen():
    """
    One lazy codegen pass resolves every unique registered endpoint and serves later ranges from cache.
    """
    source = 'a = 1 + 2\nb = 3 * 4\n'
    module = parse_module(source)
    add_range = CodeRange(CodePosition(1, 5), CodePosition(1, 8))
    multiply_range = CodeRange(CodePosition(2, 5), CodePosition(2, 8))
    registered_ranges = (node_range for node_range in [add_range, add_range, multiply_range])

    with patch('cstvis.source_offsets._SourceOffsetCodegenState', wraps=source_offsets_module._SourceOffsetCodegenState) as create_state:
        resolver = SourceOffsetResolver(module, source, registered_ranges)

        assert resolver.target_positions == {add_range.start, add_range.end, multiply_range.start, multiply_range.end}
        assert create_state.call_count == 0
        assert resolver(multiply_range) == (15, 18)
        assert create_state.call_count == 1
        assert set(resolver._offsets) == resolver.target_positions
        assert resolver(add_range) == (5, 8)
        assert resolver(multiply_range) == (15, 18)
        assert create_state.call_count == 1


@pytest.mark.parametrize(
    'source',
    [
        pytest.param(
            '@decorator\ndef function(value: int = 1):\n\ttext = f"{value}"\n\treturn (text, value + 1)\n',
            id='grammar-and-tab-indent',
        ),
        pytest.param(
            '\ufeffhead = "🙂e\u0301"\r\nvalue = 1 + 2\r',
            id='bom-unicode-and-mixed-newlines',
        ),
        pytest.param(
            'if True:\n    x=0\n\\\nresult    = 1 + 2\n',
            id='codegen-omitted-continuation',
        ),
    ],
)
def test_source_offset_resolver_preserves_global_range_invariants(source):
    """
    Every provider range stays bounded, ordered, monotone, shared-position consistent, and batch/single equivalent.
    """
    wrapper = MetadataWrapper(parse_module(source))
    node_ranges = list(wrapper.resolve(WhitespaceInclusivePositionProvider).values())
    forward_resolver = SourceOffsetResolver(wrapper.module, source, node_ranges)
    reverse_resolver = SourceOffsetResolver(wrapper.module, source, reversed(node_ranges))

    for node_range in reversed(node_ranges):
        reverse_resolver(node_range)

    position_offsets = {}
    for node_range in node_ranges:
        start_offset, end_offset = forward_resolver(node_range)
        assert 0 <= start_offset <= end_offset <= len(source)
        assert reverse_resolver(node_range) == (start_offset, end_offset)

        for position, offset in ((node_range.start, start_offset), (node_range.end, end_offset)):
            if position in position_offsets:
                assert position_offsets[position] == offset
            else:
                position_offsets[position] = offset
                zero_width_range = CodeRange(position, position)
                single_resolver = SourceOffsetResolver(parse_module(source), source, [zero_width_range])
                assert single_resolver(zero_width_range) == (offset, offset)

    ordered_offsets = [
        position_offsets[position]
        for position in sorted(position_offsets, key=lambda position: (position.line, position.column))
    ]
    assert ordered_offsets == sorted(ordered_offsets)


def test_source_position_maps_multiline_range_across_codegen_omitted_prefix():
    """
    A manual multiline range maps across CRLF and a form feed omitted by LibCST code generation.
    """
    source = 'a=1\r\n\fvalue=2\n'
    node_range = CodeRange(CodePosition(1, 1), CodePosition(2, 2))
    coordinate = Coordinate(None, 'manual', 1, 1, 2, 2)
    resolver = SourceOffsetResolver(parse_module(source), source, [node_range])
    position = SourcePosition(coordinate, source, node_range, resolver)

    assert position.code_before == 'a'
    assert position.node_range == node_range
    assert position.code_after == 'lue=2\n'
    assert position.code_before + '=1\r\n\fva' + position.code_after == position.source


def test_filter_context_exposes_whitespace_inclusive_fragments():
    """
    Context.position exposes an Add's whitespace-inclusive range, offsets, and fragments to filters.

    The ordinary coordinate remains limited to the '+' token.
    """
    source = 'left = 1  +\t2 # tail\r\nright = 3\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add) -> Add:
        return node

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.coordinate == Coordinate(None, 'Add', 1, 10, 1, 11)
    assert context.position.node_range == CodeRange(CodePosition(1, 8), CodePosition(1, 12))
    assert context.position.start_offset == 8
    assert context.position.end_offset == 12
    assert context.position.code_before == 'left = 1'
    assert context.position.code_after == '2 # tail\r\nright = 3\n'
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


def test_converter_context_exposes_original_fragments():
    """
    A converter's Context.position retains the original Add's range, offsets, and fragments after replacement.
    """
    source = 'left = 1  +\t2 # tail\r\nright = 3\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add, context: Context) -> Subtract:
        contexts.append(context)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    coordinate = next(changer.iterate_coordinates())
    transformed_source = changer.apply_coordinate(coordinate)

    assert transformed_source == 'left = 1  -\t2 # tail\r\nright = 3\n'
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.coordinate == Coordinate(None, 'Add', 1, 10, 1, 11)
    assert context.position.node_range == CodeRange(CodePosition(1, 8), CodePosition(1, 12))
    assert context.position.start_offset == 8
    assert context.position.end_offset == 12
    assert context.position.code_before == 'left = 1'
    assert context.position.code_after == '2 # tail\r\nright = 3\n'
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


@pytest.mark.parametrize('callback_kind', ['filter', 'converter'])
def test_context_pipeline_does_not_materialize_unread_fragments(callback_kind):  # noqa: C901
    """
    Coordinate-only filter and converter callbacks neither resolve fragment offsets nor slice the source.
    """
    class TrackingString(str):
        __slots__ = ('alignment_operations', 'slices')
        alignment_operations: List[str]
        slices: List[slice]

        def __new__(cls, value: str):  # type: ignore[no-untyped-def]
            instance = super().__new__(cls, value)
            instance.alignment_operations = []
            instance.slices = []
            return instance

        def __getitem__(self, key):  # type: ignore[no-untyped-def]
            if isinstance(key, slice):
                self.slices.append(key)
            return super().__getitem__(key)

        def find(self, substring, *args):  # type: ignore[no-untyped-def]
            self.alignment_operations.append('find')
            return super().find(substring, *args)

        def startswith(self, prefix, *args):  # type: ignore[no-untyped-def]
            self.alignment_operations.append('startswith')
            return super().startswith(prefix, *args)

    source = TrackingString('x = 1 + 2\n')
    changer = Changer(source)
    source.alignment_operations.clear()
    source.slices.clear()
    observed_coordinates = []

    if callback_kind == 'filter':
        @changer.converter
        def convert(node: Add) -> Add:
            return node

        @changer.filter
        def inspect_coordinate(node: Add, context: Context) -> bool:  # noqa: ARG001
            observed_coordinates.append(context.position.coordinate)
            return False
    else:
        @changer.converter
        def convert(node: Add, context: Context) -> Subtract:
            observed_coordinates.append(context.position.coordinate)
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    alignment_ranges = []
    resolve_offsets = SourceOffsetResolver.__call__

    def track_alignment(resolver, node_range):  # type: ignore[no-untyped-def]
        alignment_ranges.append(node_range)
        return resolve_offsets(resolver, node_range)

    with patch.object(SourceOffsetResolver, '__call__', track_alignment):
        coordinates = list(changer.iterate_coordinates())
        if callback_kind == 'filter':
            assert coordinates == []
        else:
            assert len(coordinates) == 1
            assert changer.apply_coordinate(coordinates[0]) == 'x = 1 - 2\n'

    assert observed_coordinates == [Coordinate(None, 'Add', 1, 6, 1, 7)]
    assert alignment_ranges == []
    assert source.alignment_operations == []
    assert source.slices == []


@pytest.mark.parametrize('callback_kind', ['filter', 'converter'])
def test_node_only_callbacks_do_not_materialize_context_fragments(callback_kind):
    """
    Node-only filter and converter callbacks neither resolve fragment offsets nor slice the source.
    """
    class TrackingString(str):
        __slots__ = ('slices',)
        slices: List[slice]

        def __new__(cls, value: str):  # type: ignore[no-untyped-def]
            instance = super().__new__(cls, value)
            instance.slices = []
            return instance

        def __getitem__(self, key):  # type: ignore[no-untyped-def]
            if isinstance(key, slice):
                self.slices.append(key)
            return super().__getitem__(key)

    source = TrackingString('x = 1 + 2\n')
    changer = Changer(source)
    source.slices.clear()
    converter_inputs = []
    filter_inputs = []
    alignment_ranges = []

    @changer.converter
    def convert(node: Add) -> Subtract:
        converter_inputs.append(node)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    if callback_kind == 'filter':
        @changer.filter
        def reject(node: Add) -> bool:
            filter_inputs.append(node)
            return False

    resolve_offsets = SourceOffsetResolver.__call__

    def track_alignment(resolver, node_range):  # type: ignore[no-untyped-def]
        alignment_ranges.append(node_range)
        return resolve_offsets(resolver, node_range)

    with patch.object(SourceOffsetResolver, '__call__', track_alignment):
        coordinates = list(changer.iterate_coordinates())
        if callback_kind == 'converter':
            assert changer.apply_coordinate(coordinates[0]) == 'x = 1 - 2\n'

    if callback_kind == 'filter':
        assert coordinates == []
        assert len(filter_inputs) == 1
        assert isinstance(filter_inputs[0], Add)
        assert converter_inputs == []
    else:
        assert len(coordinates) == 1
        assert len(converter_inputs) == 1
        assert isinstance(converter_inputs[0], Add)
    assert alignment_ranges == []
    assert source.slices == []


@pytest.mark.parametrize('callback_kind', ['filter', 'converter'])
@pytest.mark.parametrize('fragment_name', ['code_before', 'code_after'])
def test_context_pipeline_materializes_only_requested_fragment(callback_kind, fragment_name):
    """
    Filter and converter paths resolve and slice only the requested fragment once despite repeated reads.
    """
    class TrackingString(str):
        __slots__ = ('slices',)
        slices: List[slice]

        def __new__(cls, value: str):  # type: ignore[no-untyped-def]
            instance = super().__new__(cls, value)
            instance.slices = []
            return instance

        def __getitem__(self, key):  # type: ignore[no-untyped-def]
            if isinstance(key, slice):
                self.slices.append(key)
            return super().__getitem__(key)

    source = TrackingString('x = 1 + 2\n')
    changer = Changer(source)
    fragment_values = []
    contexts = []
    source.slices.clear()

    if callback_kind == 'filter':
        @changer.converter
        def convert(node: Add) -> Add:
            return node

        @changer.filter
        def read_fragment(node: Add, context: Context) -> bool:  # noqa: ARG001
            contexts.append(context)
            fragment_values.extend([getattr(context.position, fragment_name), getattr(context.position, fragment_name)])
            return True
    else:
        @changer.converter
        def convert(node: Add, context: Context) -> Add:
            contexts.append(context)
            fragment_values.extend([getattr(context.position, fragment_name), getattr(context.position, fragment_name)])
            return node

    alignment_ranges = []
    resolve_offsets = SourceOffsetResolver.__call__

    def track_alignment(resolver, node_range):  # type: ignore[no-untyped-def]
        alignment_ranges.append(node_range)
        return resolve_offsets(resolver, node_range)

    with patch.object(SourceOffsetResolver, '__call__', track_alignment):
        coordinates = list(changer.iterate_coordinates())
        if callback_kind == 'converter':
            changer.apply_coordinate(coordinates[0])

    expected_fragment = 'x = 1' if fragment_name == 'code_before' else '2\n'
    expected_slice = slice(None, 5) if fragment_name == 'code_before' else slice(8, None)
    other_fragment_name = 'code_after' if fragment_name == 'code_before' else 'code_before'
    assert len(contexts) == 1
    assert fragment_name in contexts[0].position.__dict__
    assert other_fragment_name not in contexts[0].position.__dict__
    assert fragment_values == [expected_fragment, expected_fragment]
    assert alignment_ranges == [CodeRange(CodePosition(1, 5), CodePosition(1, 8))]
    assert source.slices == [expected_slice]


@pytest.mark.parametrize('callback_kind', ['filter', 'converter'])
def test_context_fragments_can_be_read_after_traversal(callback_kind):
    """
    A captured Context.position can resolve unread fragments after traversal and reconstruct the source.
    """
    class TrackingString(str):
        __slots__ = ('slices',)
        slices: List[slice]

        def __new__(cls, value: str):  # type: ignore[no-untyped-def]
            instance = super().__new__(cls, value)
            instance.slices = []
            return instance

        def __getitem__(self, key):  # type: ignore[no-untyped-def]
            if isinstance(key, slice):
                self.slices.append(key)
            return super().__getitem__(key)

    source = TrackingString('x = 1 + 2\n')
    changer = Changer(source)
    contexts = []
    source.slices.clear()

    if callback_kind == 'filter':
        @changer.converter
        def convert(node: Add) -> Add:
            return node

        @changer.filter
        def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
            contexts.append(context)
            return True
    else:
        @changer.converter
        def convert(node: Add, context: Context) -> Add:
            contexts.append(context)
            return node

    coordinates = list(changer.iterate_coordinates())
    if callback_kind == 'converter':
        changer.apply_coordinate(coordinates[0])

    assert source.slices == []
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 5), CodePosition(1, 8))
    assert context.position.code_before == 'x = 1'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + ' + ' + context.position.code_after == context.position.source


def test_code_fragments_cover_single_node_and_file_boundaries():
    """
    Nodes spanning or touching file boundaries leave the corresponding surrounding fragments empty.
    """
    single_node_changer = Changer('1')
    single_node_contexts = []

    @single_node_changer.converter
    def convert_single_node(node: Integer) -> Integer:
        return node

    @single_node_changer.filter
    def capture_single_node(node: Integer, context: Context) -> bool:  # noqa: ARG001
        single_node_contexts.append(context)
        return True

    assert len(list(single_node_changer.iterate_coordinates())) == 1
    single_node_context = single_node_contexts[0]
    assert single_node_context.position.code_before == ''
    assert single_node_context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(1, 1))
    assert single_node_context.position.code_after == ''
    assert single_node_context.position.code_before + '1' + single_node_context.position.code_after == single_node_context.position.source

    boundary_changer = Changer('x = 1')
    first_node_contexts = []
    last_node_contexts = []

    @boundary_changer.converter
    def convert_first_node(node: Name) -> Name:
        return node

    @boundary_changer.converter
    def convert_last_node(node: Integer) -> Integer:
        return node

    @boundary_changer.filter
    def capture_first_node(node: Name, context: Context) -> bool:  # noqa: ARG001
        first_node_contexts.append(context)
        return True

    @boundary_changer.filter
    def capture_last_node(node: Integer, context: Context) -> bool:  # noqa: ARG001
        last_node_contexts.append(context)
        return True

    assert len(list(boundary_changer.iterate_coordinates())) == 2
    first_node_context = first_node_contexts[0]
    assert first_node_context.position.code_before == ''
    assert first_node_context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(1, 1))
    assert first_node_context.position.code_after == ' = 1'
    assert first_node_context.position.code_before + 'x' + first_node_context.position.code_after == first_node_context.position.source

    last_node_context = last_node_contexts[0]
    assert last_node_context.position.code_before == 'x = '
    assert last_node_context.position.node_range == CodeRange(CodePosition(1, 4), CodePosition(1, 5))
    assert last_node_context.position.code_after == ''
    assert last_node_context.position.code_before + '1' + last_node_context.position.code_after == last_node_context.position.source


def test_code_fragments_partition_zero_width_parameters():
    """
    A zero-width Parameters node partitions non-empty source without shifting either fragment.
    """
    source = 'def f():\n    pass\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Parameters) -> Parameters:
        return node

    @changer.filter
    def capture(node: Parameters, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 6), CodePosition(1, 6))
    assert context.position.code_before == 'def f('
    assert context.position.code_after == '):\n    pass\n'
    assert context.position.code_before + '' + context.position.code_after == context.position.source


def test_code_fragments_handle_later_statement_without_final_newline():
    """
    At virtual EOF, a statement keeps the preceding CRLF and Context adds no final newline, unlike code_for_node().
    """
    source = 'head = 0\r\nx = 1'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: SimpleStatementLine) -> SimpleStatementLine:
        return node

    @changer.filter
    def capture(node: SimpleStatementLine, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 2
    context = contexts[1]
    assert context.position.node_range == CodeRange(CodePosition(2, 0), CodePosition(3, 0))
    assert context.position.code_before == 'head = 0\r\n'
    assert context.position.code_after == ''
    assert context.position.code_before + 'x = 1' + context.position.code_after == context.position.source


def test_code_fragments_preserve_semicolon_owned_trivia():
    """
    The first Assign owns its trailing semicolon and space, excluding them from code_after.
    """
    source = 'x=1; y=2\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Assign) -> Assign:
        return node

    @changer.filter
    def capture(node: Assign, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 2
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(1, 5))
    assert context.position.code_before == ''
    assert context.position.code_after == 'y=2\n'
    assert context.position.code_before + 'x=1; ' + context.position.code_after == context.position.source


def test_code_fragments_preserve_decorators_and_surrounding_comments():
    """
    FunctionDef's span includes decorators, an indented body, and newlines but excludes surrounding comments.
    """
    source = '# h\n@dec\ndef f(x: int = 1):\n    return x\n# f\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: FunctionDef) -> FunctionDef:
        return node

    @changer.filter
    def capture(node: FunctionDef, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(2, 0), CodePosition(5, 0))
    assert context.position.code_before == '# h\n'
    assert context.position.code_after == '# f\n'
    assert context.position.code_before + '@dec\ndef f(x: int = 1):\n    return x\n' + context.position.code_after == context.position.source


def test_code_fragments_preserve_nested_indentation_and_comments():
    """
    A nested statement span retains ambient indentation that Module.code_for_node() would omit.

    The exact partition also preserves its leading and inline comments and multiline assignment.
    """
    source = '# header\nif True:\n    # lead\n    value = (\n        1 + 2  # inner\n    )\n# footer\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: SimpleStatementLine) -> SimpleStatementLine:
        return node

    @changer.filter
    def capture(node: SimpleStatementLine, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(3, 0), CodePosition(7, 0))
    assert context.position.code_before == '# header\nif True:\n'
    assert context.position.code_after == '# footer\n'
    assert context.position.code_before + '    # lead\n    value = (\n        1 + 2  # inner\n    )\n' + context.position.code_after == context.position.source


def test_codegen_indent_does_not_search_forward_in_source():
    """
    A generated suite indent cannot jump to matching spaces later in source after an omitted continuation.
    """
    source = 'if True:\n    x=0\n\\\nresult    = 1 + 2\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Name) -> Name:
        return node

    @changer.filter
    def capture(node: Name, context: Context) -> bool:
        if node.value != 'result':
            return False
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(3, 4), CodePosition(3, 10))
    assert context.position.code_before == 'if True:\n    x=0\n\\\n'
    assert context.position.code_after == '    = 1 + 2\n'
    assert context.position.code_before + 'result' + context.position.code_after == context.position.source


@pytest.mark.parametrize(
    ('indent', 'expected_range'),
    [
        pytest.param('\t', CodeRange(CodePosition(2, 11), CodePosition(2, 14)), id='tab'),
        pytest.param('  ', CodeRange(CodePosition(2, 12), CodePosition(2, 15)), id='two-spaces'),
    ],
)
def test_code_fragments_follow_module_default_indent(indent, expected_range):
    """
    Nested Add fragments use LibCST's inferred tab or two-space default indent instead of four hard-coded spaces.
    """
    source = f'if True:\n{indent}result = 1 + 2\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add) -> Add:
        return node

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == expected_range
    assert context.position.code_before == f'if True:\n{indent}result = 1'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + ' + ' + context.position.code_after == context.position.source


@pytest.mark.parametrize(
    'newline',
    [
        pytest.param('\r\n', id='crlf'),
        pytest.param('\r', id='bare-cr'),
    ],
)
def test_code_fragments_follow_module_default_newline_at_node_boundary(newline):
    """
    An Assign ending immediately before CRLF or bare CR leaves the complete inferred newline in code_after.
    """
    source = f'head=0{newline}x=1'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Assign) -> Assign:
        return node

    @changer.filter
    def capture(node: Assign, context: Context) -> bool:  # noqa: ARG001
        if context.position.coordinate.start_line != 1:
            return False
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(1, 6))
    assert context.position.code_before == ''
    assert context.position.code_after == f'{newline}x=1'
    assert context.position.code_before + 'head=0' + context.position.code_after == context.position.source


def test_code_fragments_preserve_multiline_parenthesized_expression():
    """
    A multiline BinaryOperation span includes its parentheses, continuation indentation, and inline comment.
    """
    source = '# header\nif True:\n    value = (\n        1 + 2  # inner\n    )\n# footer\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: BinaryOperation) -> BinaryOperation:
        return node

    @changer.filter
    def capture(node: BinaryOperation, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(3, 12), CodePosition(5, 5))
    assert context.position.code_before == '# header\nif True:\n    value = '
    assert context.position.code_after == '\n# footer\n'
    assert context.position.code_before + '(\n        1 + 2  # inner\n    )' + context.position.code_after == context.position.source


def test_code_fragments_select_correct_repeated_occurrence():
    """
    Distinct ranges partition identical Add occurrences instead of using the first textual match.
    """
    source = 'foo = foo + foo\nfoo = foo + foo\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add) -> Add:
        return node

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 2
    first_context, second_context = contexts
    assert first_context.position.node_range == CodeRange(CodePosition(1, 9), CodePosition(1, 12))
    assert first_context.position.code_before == 'foo = foo'
    assert first_context.position.code_after == 'foo\nfoo = foo + foo\n'
    assert first_context.position.code_before + ' + ' + first_context.position.code_after == first_context.position.source
    assert second_context.position.node_range == CodeRange(CodePosition(2, 9), CodePosition(2, 12))
    assert second_context.position.code_before == 'foo = foo + foo\nfoo = foo'
    assert second_context.position.code_after == 'foo\n'
    assert second_context.position.code_before + ' + ' + second_context.position.code_after == second_context.position.source


def test_code_fragments_map_later_node_across_mixed_newlines():
    """
    A third-line Add maps across preceding CRLF and bare CR while preserving the following LF.
    """
    source = 'first=0\r\nsecond=1\rthird = 2  +\t3\nlast=4'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add) -> Add:
        return node

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(3, 9), CodePosition(3, 13))
    assert context.position.code_before == 'first=0\r\nsecond=1\rthird = 2'
    assert context.position.code_after == '3\nlast=4'
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


def test_code_fragments_preserve_unicode_before_later_node():
    """
    Non-BMP and combining characters before a later Add count as Python characters, not UTF-8 bytes.
    """
    source = 'header = "🙂e\u0301"\nvalue = π  +\t2\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add) -> Add:
        return node

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(2, 9), CodePosition(2, 13))
    assert context.position.code_before == 'header = "🙂e\u0301"\nvalue = π'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


def test_code_fragments_count_same_line_unicode_as_python_characters():
    """
    Non-BMP and combining characters on Add's line each occupy one LibCST column and one source index.
    """
    source = 'header = "🙂e\u0301"; value = π  +\t2\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add) -> Add:
        return node

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 25), CodePosition(1, 29))
    assert context.position.code_before == 'header = "🙂e\u0301"; value = π'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


def test_code_fragments_preserve_bom_before_later_node():
    """
    Absolute offsets count an initial BOM and Unicode header before a second-line Add.

    The BOM remains in code_before rather than shifting the Add's contextual span.
    """
    source = '\ufeffheader = "🙂e\u0301"\nvalue = 1  +\t2\ntail = 3\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add) -> Add:
        return node

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(2, 9), CodePosition(2, 13))
    assert context.position.start_offset == 25
    assert context.position.end_offset == 29
    assert context.position.code_before == '\ufeffheader = "🙂e\u0301"\nvalue = 1'
    assert context.position.code_after == '2\ntail = 3\n'
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


def test_internal_bom_does_not_shift_initial_source_offset():
    """
    A BOM inside a string does not trigger the one-character offset reserved for an initial BOM.
    """
    source = 'prefix = "\ufeff"\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Name) -> Name:
        return node

    @changer.filter
    def capture(node: Name, context: Context) -> bool:
        if node.value != 'prefix':
            return False
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(1, 6))
    assert context.position.code_before == ''
    assert context.position.code_after == ' = "\ufeff"\n'
    assert context.position.code_before + 'prefix' + context.position.code_after == context.position.source


@pytest.mark.parametrize('source', ['', 'x=1\n'], ids=['empty-source', 'ordinary-source'])
def test_module_fragments_cover_empty_and_nonempty_sources_completely(source):
    """
    Module spans empty and non-empty sources, including an empty range, without surrounding fragments.
    """
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Module, context: Context) -> Module:
        contexts.append(context)
        return node

    coordinate = next(changer.iterate_coordinates())
    assert changer.apply_coordinate(coordinate) == source
    assert len(contexts) == 1
    context = contexts[0]
    expected_end_position = CodePosition(1, 0) if not source else CodePosition(2, 0)
    assert context.position.node_range == CodeRange(CodePosition(1, 0), expected_end_position)
    assert context.position.code_before == ''
    assert context.position.code_after == ''
    assert context.position.code_before + source + context.position.code_after == context.position.source


def test_module_range_leaves_bom_in_code_before():
    """
    LibCST excludes an initial U+FEFF BOM from Module's range; SourcePosition keeps it in code_before.
    """
    source = '\ufeffx=1\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Module, context: Context) -> Module:
        contexts.append(context)
        return node

    coordinate = next(changer.iterate_coordinates())
    changer.apply_coordinate(coordinate)
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(2, 0))
    assert context.position.code_before == '\ufeff'
    assert context.position.code_after == ''
    assert context.position.code_before + 'x=1\n' + context.position.code_after == context.position.source


@pytest.mark.parametrize(
    ('source', 'expected_before', 'expected_module_span'),
    [
        pytest.param('\f', '', '\f', id='form-feed-only'),
        pytest.param(' \f', '', ' \f', id='space-and-form-feed'),
        pytest.param('\ufeff\f', '\ufeff', '\f', id='bom-and-form-feed'),
    ],
)
def test_module_fragments_keep_eof_form_feed_in_module_span(source, expected_before, expected_module_span):
    """
    An EOF form feed remains in Module's span for whitespace-only files, with or without a BOM.
    """
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Module, context: Context) -> Module:
        contexts.append(context)
        return node

    coordinate = next(changer.iterate_coordinates())
    changer.apply_coordinate(coordinate)
    assert len(contexts) == 1
    context = contexts[0]
    assert context.position.code_before == expected_before
    assert context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(2, 0))
    assert context.position.code_after == ''
    assert context.position.code_before + expected_module_span + context.position.code_after == context.position.source


@pytest.mark.parametrize('prefix', [pytest.param('\f', id='form-feed'), pytest.param('\t\f', id='tab-and-form-feed')])
def test_code_fragments_preserve_leading_form_feed_prefix(prefix):
    """
    A codegen-omitted form-feed prefix remains in code_before without shifting Add's span, with or without a tab.
    """
    source = f'{prefix}result = 1  + 2\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add) -> Add:
        return node

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 10), CodePosition(1, 14))
    assert context.position.code_before == f'{prefix}result = 1'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + '  + ' + context.position.code_after == context.position.source


@pytest.mark.parametrize(
    'prefix',
    [
        pytest.param('\\\n', id='lf-continuation'),
        pytest.param('\\\r', id='cr-continuation'),
        pytest.param('\\\r\n', id='crlf-continuation'),
        pytest.param('\f\\\n', id='form-feed-and-continuation'),
        pytest.param('\ufeff\\\n', id='bom-and-continuation'),
        pytest.param('\\\n\t\f', id='continued-tab-and-form-feed'),
    ],
)
def test_code_fragments_preserve_leading_line_continuation_prefix(prefix):
    """
    Codegen-omitted LF, CR, and CRLF continuations stay in code_before across BOM, form-feed, and indentation variants.
    """
    source = f'{prefix}result = 1  + 2\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add) -> Add:
        return node

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 10), CodePosition(1, 14))
    assert context.position.code_before == f'{prefix}result = 1'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + '  + ' + context.position.code_after == context.position.source


@pytest.mark.parametrize(
    'prefix',
    [
        pytest.param('\n\f', id='blank-line-before-form-feed'),
        pytest.param('# lead\n \f', id='comment-before-form-feed'),
        pytest.param('\n\\\n', id='blank-line-before-continuation'),
        pytest.param('# lead\r\n\\\r\n', id='crlf-comment-before-continuation'),
    ],
)
def test_code_fragments_preserve_codegen_omitted_prefix_after_blank_or_comment_line(prefix):
    """
    An omitted form feed or continuation stays in code_before after a blank or comment line without shifting the later Add.
    """
    source = f'{prefix}result = 1  + 2\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add) -> Add:
        return node

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(2, 10), CodePosition(2, 14))
    assert context.position.code_before == f'{prefix}result = 1'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + '  + ' + context.position.code_after == context.position.source


def test_code_fragments_preserve_nested_form_feed_indentation():
    """
    A form feed in suite indentation affects LibCST columns without misaligning nested fragments.
    """
    source = 'if True:\n\f    result = 1  + 2\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add) -> Add:
        return node

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(2, 15), CodePosition(2, 19))
    assert context.position.code_before == 'if True:\n\f    result = 1'
    assert context.position.code_after == '2\n'
    assert context.position.code_before + '  + ' + context.position.code_after == context.position.source


@pytest.mark.parametrize(
    ('source', 'expected_range', 'expected_before', 'expected_after'),
    [
        pytest.param(
            'value = (\n\f1  +\t2\n)\n',
            CodeRange(CodePosition(2, 2), CodePosition(2, 6)),
            'value = (\n\f1',
            '2\n)\n',
            id='form-feed-in-parenthesized-expression',
        ),
        pytest.param(
            'value=(\n\\\n1  +\t2\n)\n',
            CodeRange(CodePosition(3, 1), CodePosition(3, 5)),
            'value=(\n\\\n1',
            '2\n)\n',
            id='continuation-in-parenthesized-expression',
        ),
        pytest.param(
            's = f"""\n\f{1  +\t2}\n"""\n',
            CodeRange(CodePosition(2, 3), CodePosition(2, 7)),
            's = f"""\n\f{1',
            '2}\n"""\n',
            id='form-feed-in-fstring',
        ),
        pytest.param(
            's = """\n\\\ntext\n"""\nresult=π  +\t2\n',
            CodeRange(CodePosition(5, 8), CodePosition(5, 12)),
            's = """\n\\\ntext\n"""\nresult=π',
            '2\n',
            id='continuation-in-preceding-triple-string',
        ),
        pytest.param(
            'if True:\n    x = 0\n\\\nresult = 1  +\t2\n',
            CodeRange(CodePosition(3, 14), CodePosition(3, 18)),
            'if True:\n    x = 0\n\\\nresult = 1',
            '2\n',
            id='continuation-after-indented-suite',
        ),
    ],
)
def test_code_fragments_preserve_alignment_across_parser_contexts(source, expected_range, expected_before, expected_after):
    """
    Exact fragments verify Add alignment across form feeds and continuations inside parentheses and f-strings, after a triple-quoted string, and after an indented suite.
    """
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: Add) -> Add:
        return node

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    context = contexts[0]
    assert context.position.node_range == expected_range
    assert context.position.code_before == expected_before
    assert context.position.code_after == expected_after
    assert context.position.code_before + '  +\t' + context.position.code_after == context.position.source


def test_code_fragments_align_nested_string_matching_enclosing_fstring_quotes():
    """
    A nested SimpleString sharing its f-string's quotes includes enclosing parentheses but excludes the closing brace.
    """
    source = 'value = f"""{("""inner\n\fbody""")}\ntail"""\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: SimpleString) -> SimpleString:
        return node

    @changer.filter
    def capture(node: SimpleString, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    context = contexts[0]
    assert context.position.node_range == CodeRange(CodePosition(1, 13), CodePosition(2, 9))
    assert context.position.code_before == 'value = f"""{'
    assert context.position.code_after == '}\ntail"""\n'
    assert context.position.code_before + '("""inner\n\fbody""")' + context.position.code_after == context.position.source


def test_pipeline_and_direct_source_positions_partition_form_feed_identically():
    """
    Pipeline and directly constructed SourcePositions partition an omitted form feed identically.
    """
    source = 'x=1\n\fresult=2\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def convert(node: SimpleStatementLine) -> SimpleStatementLine:
        return node

    @changer.filter
    def capture(node: SimpleStatementLine, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 2
    first_context, second_context = contexts
    assert first_context.position.node_range == CodeRange(CodePosition(1, 0), CodePosition(2, 0))
    assert first_context.position.code_before == ''
    assert first_context.position.code_after == 'result=2\n'
    assert first_context.position.code_before + 'x=1\n\f' + first_context.position.code_after == first_context.position.source
    direct_resolver = SourceOffsetResolver(
        parse_module(first_context.position.source),
        first_context.position.source,
        [first_context.position.node_range],
    )
    direct_position = SourcePosition(
        first_context.position.coordinate,
        first_context.position.source,
        first_context.position.node_range,
        direct_resolver,
    )
    assert direct_position == first_context.position
    assert direct_position.code_before == first_context.position.code_before
    assert direct_position.code_after == first_context.position.code_after
    assert second_context.position.node_range == CodeRange(CodePosition(2, 0), CodePosition(3, 0))
    assert second_context.position.code_before == 'x=1\n\f'
    assert second_context.position.code_after == ''
    assert second_context.position.code_before + 'result=2\n' + second_context.position.code_after == second_context.position.source


def test_multiple_filters_receive_contexts_with_isolated_meta():
    """
    Filter Context copies share one SourcePosition while their mutable meta copies remain isolated.
    """
    source = 'x = 1 + 2\n'
    changer = Changer(source)
    first_filter_meta = {'filter': 1}
    second_filter_meta = {'filter': 2}
    contexts = []

    @changer.converter
    def convert(node: Add) -> Add:
        return node

    @changer.filter(meta=first_filter_meta)
    def first_filter(node: Add, context: Context) -> bool:  # noqa: ARG001
        assert context.meta is not None
        context.meta['changed'] = True
        contexts.append(context)
        return True

    @changer.filter(meta=second_filter_meta)
    def second_filter(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(contexts) == 2
    assert contexts[0].position is contexts[1].position
    assert contexts[0].meta == {'filter': 1, 'changed': True}
    assert contexts[1].meta == {'filter': 2}
    assert first_filter_meta == {'filter': 1}
    assert second_filter_meta == {'filter': 2}
    with patch('cstvis.source_offsets._SourceOffsetCodegenState', wraps=source_offsets_module._SourceOffsetCodegenState) as create_state:
        for context in contexts:
            assert context.position.node_range == CodeRange(CodePosition(1, 5), CodePosition(1, 8))
            assert context.position.code_before == 'x = 1'
            assert context.position.code_after == '2\n'
            assert context.position.code_before + ' + ' + context.position.code_after == context.position.source
        assert create_state.call_count == 1


def test_multiple_converters_receive_equal_original_fragments():
    """
    Different Add replacements receive equal original fragments and produce distinct transformed sources.
    """
    source = 'x = 1 + 2\n'
    changer = Changer(source)
    contexts = []

    @changer.converter
    def subtract(node: Add, context: Context) -> Subtract:
        contexts.append(context)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.converter
    def multiply(node: Add, context: Context) -> Multiply:
        contexts.append(context)
        return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    transformed_sources = {changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()}

    assert transformed_sources == {'x = 1 - 2\n', 'x = 1 * 2\n'}
    assert len(contexts) == 2
    for context in contexts:
        assert context.position.source == source
        assert context.position.node_range == CodeRange(CodePosition(1, 5), CodePosition(1, 8))
        assert context.position.code_before == 'x = 1'
        assert context.position.code_after == '2\n'
        assert context.position.code_before + ' + ' + context.position.code_after == context.position.source
