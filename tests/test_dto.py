from dataclasses import FrozenInstanceError
from typing import List
from unittest.mock import patch

import pytest
from libcst import parse_module
from libcst.metadata import CodePosition, CodeRange
from metacode import ParsedComment
from printo import describe_call as printo_describe_call

from cstvis import Context, Coordinate
from cstvis.dto import SourcePosition
from cstvis.source_offsets import SourceOffsetResolver


def test_context_exposes_position_and_context_and_source_position_reject_missing_fields():
    """
    `Context` exposes `position` instead of flattened source attributes, and
    `Context`/`SourcePosition` reject missing required fields.

    `Context.comment` is required but may be `None`; `Context.meta` is optional
    and defaults to `None`.
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
    assert not hasattr(context, 'coordinate')
    assert not hasattr(context, 'source')
    assert not hasattr(context, 'node_range')
    with pytest.raises(TypeError, match=r"missing .*'position'"):
        Context(comment=None)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match=r"missing .*'offset_resolver'"):
        SourcePosition(coordinate, '1 + 2', node_range)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match=r"missing .*'source'"):
        SourcePosition(coordinate, node_range=node_range, offset_resolver=resolver)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match=r"missing .*'node_range'"):
        SourcePosition(coordinate, '1 + 2', offset_resolver=resolver)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match=r"missing .*'coordinate'"):
        SourcePosition(source='1 + 2', node_range=node_range, offset_resolver=resolver)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match=r"missing .*'comment'"):
        Context(position)  # type: ignore[call-arg]


def test_context_and_source_position_are_frozen_but_meta_contents_are_mutable():
    """
    `Context` and `SourcePosition` are frozen dataclasses: their fields cannot be
    reassigned, while the contents of the `meta` dictionary remain mutable.
    """
    coordinate = Coordinate(None, 'Add', 1, 2, 1, 3)
    node_range = CodeRange(CodePosition(1, 1), CodePosition(1, 4))
    resolver = SourceOffsetResolver(parse_module('1 + 2'), '1 + 2', [node_range])
    position = SourcePosition(coordinate, '1 + 2', node_range, resolver)
    context = Context(position, None, {'key': 'value'})

    with pytest.raises(FrozenInstanceError, match=r"cannot assign to field 'source'"):
        position.source = '3 + 4'  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError, match=r"cannot assign to field 'node_range'"):
        position.node_range = CodeRange(CodePosition(1, 0), CodePosition(1, 1))  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError, match=r"cannot assign to field 'offset_resolver'"):
        position.offset_resolver = resolver  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError, match=r"cannot assign to field 'position'"):
        context.position = position  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError, match=r"cannot assign to field 'coordinate'"):
        position.coordinate = Coordinate(None, 'Add', 1, 0, 1, 1)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError, match=r"cannot assign to field 'comment'"):
        context.comment = 'replacement'  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError, match=r"cannot assign to field 'meta'"):
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
    Equality compares every dataclass field of `Context` and `SourcePosition` by
    value, except `SourcePosition.offset_resolver`; lazily derived offsets and
    fragments are ignored.
    """
    coordinate = Coordinate(None, 'Add', 1, 2, 1, 3)
    node_range = CodeRange(CodePosition(1, 1), CodePosition(1, 4))
    resolver = SourceOffsetResolver(parse_module('1 + 2'), '1 + 2', [node_range])
    other_resolver = SourceOffsetResolver(parse_module('1 + 2'), '1 + 2', [node_range])
    position = SourcePosition(coordinate, '1 + 2', node_range, resolver)
    equal_position = SourcePosition(
        Coordinate(None, 'Add', 1, 2, 1, 3),
        '1 + 2',
        CodeRange(CodePosition(1, 1), CodePosition(1, 4)),
        other_resolver,
    )
    context = Context(position, 'note', {'key': 'value'})
    equal_context = Context(equal_position, 'note', {'key': 'value'})

    assert position == equal_position
    assert position != object()
    assert position != SourcePosition(coordinate, '3 + 4', node_range, resolver)
    assert context.meta is not equal_context.meta
    assert context.position.code_before == '1'
    assert context.position.code_after == '2'
    assert context.position.start_offset == 1
    assert context.position.end_offset == 4
    assert context == equal_context
    assert context != Context(SourcePosition(coordinate, '3 + 4', node_range, resolver), 'note', {'key': 'value'})
    different_range = CodeRange(CodePosition(1, 0), CodePosition(1, 1))
    assert context != Context(SourcePosition(coordinate, '1 + 2', different_range, resolver), 'note', {'key': 'value'})
    different_coordinate = Coordinate(None, 'Add', 1, 0, 1, 1)
    assert context != Context(SourcePosition(different_coordinate, '1 + 2', node_range, resolver), 'note', {'key': 'value'})
    assert context != object()
    assert context != Context(position, 'other', {'key': 'value'})
    assert context != Context(position, 'note', {'key': 'other'})


def test_dto_reprs_delegate_fields_and_keep_fragments_lazy():  # noqa: PLR0915
    """The reprs pass public fields to printo with `item_limit=80`, truncating long values; `offset_resolver` is omitted and fragments stay lazy."""
    coordinate = Coordinate(None, 'Add', 1, 2, 1, 3)
    node_range = CodeRange(CodePosition(1, 1), CodePosition(1, 4))
    comment = 'keep this comment'
    long_comment = 'c' * 200
    meta = {'mode': 'test'}
    long_meta = {f'key{index}': index for index in range(20)}
    short_source = '1 + 2'
    short_resolver = SourceOffsetResolver(parse_module(short_source), short_source, [node_range])
    short_position = SourcePosition(coordinate, short_source, node_range, short_resolver)
    short_context = Context(short_position, comment, meta)
    long_source = 'x' * 200
    long_resolver = SourceOffsetResolver(parse_module(long_source), long_source, [node_range])
    long_position = SourcePosition(coordinate, long_source, node_range, long_resolver)
    long_context = Context(long_position, long_comment, long_meta)
    default_context = Context(short_position, None)

    with patch('cstvis.dto.describe_call', wraps=printo_describe_call) as describe_call:
        short_position_repr = repr(short_position)
        long_position_repr = repr(long_position)
        short_context_repr = repr(short_context)
        long_context_repr = repr(long_context)
        default_context_repr = repr(default_context)

    assert "source='1 + 2'" in short_position_repr
    assert 'start_offset=1' in short_position_repr
    assert 'end_offset=4' in short_position_repr
    assert long_source not in long_position_repr
    assert 'x' * 80 in long_position_repr
    assert 'x' * 81 not in long_position_repr
    assert long_source not in long_context_repr
    assert long_comment not in long_context_repr
    assert 'c' * 80 in long_context_repr
    assert 'c' * 81 not in long_context_repr
    assert str(long_meta) not in long_context_repr
    assert "'key0': 0" in long_context_repr
    assert "'key19'" not in long_context_repr
    assert 'source=' in long_position_repr
    assert 'offset_resolver' not in short_position_repr
    assert 'offset_resolver' not in long_position_repr
    assert 'offset_resolver' not in short_context_repr
    assert 'offset_resolver' not in long_context_repr
    assert 'position=SourcePosition(' in short_context_repr
    assert 'position=SourcePosition(' in long_context_repr
    assert 'comment=None' in default_context_repr
    assert 'meta=None' in default_context_repr
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
    assert len(context_calls) == 3
    assert len(position_calls) == 5
    short_context_call = next(call for call in context_calls if call.args[2]['comment'] == comment)
    long_context_call = next(call for call in context_calls if call.args[2]['comment'] == long_comment)
    short_position_call = next(call for call in position_calls if call.args[2]['source'] is short_source)
    long_position_call = next(call for call in position_calls if call.args[2]['source'] is long_source)
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
            'comment': long_comment,
            'meta': long_meta,
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
    """Construction, equality, coordinate access, and metacode parsing materialize no offsets or fragments. Reading either offset calls the shared resolver without slicing, fully copying, or splitting the source; each fragment then caches only its own offset and slice, in either read order."""
    class TrackingString(str):
        __slots__ = ('alignment_operations', 'full_iterations', 'line_materializations', 'slices', 'string_conversions')
        alignment_operations: List[str]
        full_iterations: int
        line_materializations: List[str]
        slices: List[slice]
        string_conversions: int

        def __init__(self, _value: str) -> None:
            self.alignment_operations = []
            self.full_iterations = 0
            self.line_materializations = []
            self.slices = []
            self.string_conversions = 0

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
    source.alignment_operations.clear()
    source.full_iterations = 0
    source.line_materializations.clear()
    source.slices.clear()
    source.string_conversions = 0
    alignment_ranges = []
    resolve_offsets = SourceOffsetResolver.__call__

    def track_alignment(source_resolver, requested_range):  # type: ignore[no-untyped-def]
        alignment_ranges.append(requested_range)
        return resolve_offsets(source_resolver, requested_range)

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
        alignment_operations_after_offsets = list(source.alignment_operations)

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
        assert source.alignment_operations == alignment_operations_after_offsets
        assert context.position.node_range == node_range
        assert context.position.code_before + ' + ' + context.position.code_after == context.position.source
        assert source.slices == [slice(None, 11), slice(14, None)]
        assert 'code_before' in position.__dict__
        assert 'code_after' in position.__dict__

    reverse_position = SourcePosition(coordinate, source, node_range, resolver)
    assert 'end_offset' not in reverse_position.__dict__
    assert reverse_position.end_offset == 14
    assert 'start_offset' not in reverse_position.__dict__
    assert reverse_position.code_after == 'right\n'
    assert 'code_before' not in reverse_position.__dict__
    assert reverse_position.start_offset == 11
    assert reverse_position.code_before == 'header\nleft'

    code_before_read_first = SourcePosition(coordinate, source, node_range, resolver)
    assert code_before_read_first.code_before == 'header\nleft'
    assert 'start_offset' in code_before_read_first.__dict__
    assert 'end_offset' not in code_before_read_first.__dict__
    assert 'code_after' not in code_before_read_first.__dict__

    code_after_read_first = SourcePosition(coordinate, source, node_range, resolver)
    assert code_after_read_first.code_after == 'right\n'
    assert 'end_offset' in code_after_read_first.__dict__
    assert 'start_offset' not in code_after_read_first.__dict__
    assert 'code_before' not in code_after_read_first.__dict__


def test_source_position_maps_code_range_without_matching_node():
    """An in-bounds `CodeRange` that matches no CST node still splits the source into `code_before` and `code_after`."""
    node_range = CodeRange(CodePosition(1, 1), CodePosition(1, 2))
    coordinate = Coordinate(None, 'manual', 1, 1, 1, 2)
    resolver = SourceOffsetResolver(parse_module('abc'), 'abc', [node_range])
    position = SourcePosition(coordinate, 'abc', node_range, resolver)

    assert position.code_before == 'a'
    assert position.node_range == node_range
    assert position.code_after == 'c'
    assert position.code_before + 'b' + position.code_after == position.source


def test_source_position_maps_multiline_range_across_codegen_omitted_prefix():
    """A manually supplied multiline range crossing a CRLF and an omitted form feed maps back to the original source."""
    source = 'a=1\r\n\fvalue=2\n'
    node_range = CodeRange(CodePosition(1, 1), CodePosition(2, 2))
    coordinate = Coordinate(None, 'manual', 1, 1, 2, 2)
    resolver = SourceOffsetResolver(parse_module(source), source, [node_range])
    position = SourcePosition(coordinate, source, node_range, resolver)

    assert position.code_before == 'a'
    assert position.node_range == node_range
    assert position.code_after == 'lue=2\n'
    assert position.code_before + '=1\r\n\fva' + position.code_after == position.source
