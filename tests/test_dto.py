import sys
from dataclasses import FrozenInstanceError
from typing import List
from unittest.mock import patch

import pytest
from full_match import match
from libcst import parse_module
from libcst.metadata import CodePosition, CodeRange
from metacode import ParsedComment
from printo import describe_call as printo_describe_call

from cstvis import Context, Coordinate
from cstvis.dto import SourcePosition
from cstvis.source_offsets import SourceOffsetResolver


def test_context_requires_source_position_with_resolver():
    """
    Context requires SourcePosition, which requires coordinate, source, node_range, and a resolver.

    Constructor TypeErrors include the class name starting with Python 3.10.
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
    context_init = 'Context.__init__' if sys.version_info >= (3, 10) else '__init__'
    source_position_init = 'SourcePosition.__init__' if sys.version_info >= (3, 10) else '__init__'
    with pytest.raises(TypeError, match=match(f"{context_init}() missing 1 required positional argument: 'position'")):
        Context(comment=None)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match=match(f"{source_position_init}() missing 1 required positional argument: 'offset_resolver'")):
        SourcePosition(coordinate, '1 + 2', node_range)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match=match(f"{source_position_init}() missing 2 required positional arguments: 'node_range' and 'offset_resolver'")):
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
