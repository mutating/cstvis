from functools import partial
from typing import Iterable, Optional
from unittest.mock import patch

import pytest
from libcst import (
    Add,
    Assign,
    CSTNode,
    Multiply,
    Name,
    Subtract,
    metadata,
    parse_module,
)
from libcst.metadata import CodePosition, CodeRange

from cstvis import Changer, Context, Converter, Coordinate
from cstvis.source_offsets import SourceOffsetResolver
from cstvis.transformers.super_transformer import SuperTransformer


def run_manual_transformer(converter_id: Optional[str], converter: Converter, additional_converters: Iterable[Converter] = ()) -> str:
    """Run SuperTransformer with a manually built coordinate and converter mapping."""
    source = '1 + 2\n'
    module = parse_module(source)
    wrapper = metadata.MetadataWrapper(module)
    node_ranges = wrapper.resolve(metadata.WhitespaceInclusivePositionProvider)
    coordinate = Coordinate(None, 'Add', 1, 2, 1, 3, converter_id=converter_id)
    transformer = SuperTransformer(
        coordinate,
        {Add: [converter, *additional_converters]},
        {},
        SourceOffsetResolver(wrapper.module, source, node_ranges.values()),
    )
    return wrapper.visit(transformer).code


def test_assign_converter_receives_updated_node_with_original_context():
    """After a subclass renames the target, the parent `Assign` converter runs once with the updated node and original context. Dispatch follows the converter id, so the catch-all `CSTNode` converter is skipped."""
    source = 'before = 1\n'
    changer = Changer(source)
    converter_calls = []
    catch_all_calls = []

    @changer.converter
    def capture_assign(node: Assign, context: Context) -> Assign:
        converter_calls.append((node, context))
        return node

    @changer.converter
    def capture_catch_all(node: CSTNode) -> CSTNode:
        catch_all_calls.append(node)
        return node

    assert changer.converters_by_types[CSTNode] == [capture_catch_all]

    assign_coordinates = [
        coordinate for coordinate in changer.iterate_coordinates() if coordinate.class_name == 'Assign'
    ]
    assert len(assign_coordinates) == 2
    assert {coordinate.converter_id for coordinate in assign_coordinates} == {
        capture_assign.get_function_id(),
        capture_catch_all.get_function_id(),
    }
    coordinate = next(
        coordinate
        for coordinate in assign_coordinates
        if coordinate.converter_id == capture_assign.get_function_id()
    )

    class ChildUpdatingSuperTransformer(SuperTransformer):
        def on_leave(self, original_node: CSTNode, updated_node: CSTNode) -> CSTNode:  # type: ignore[override]
            if isinstance(original_node, Name) and original_node.value == 'before':
                updated_node = Name('after_renaming')
            return super().on_leave(original_node, updated_node)

    with patch('cstvis.changer.SuperTransformer', ChildUpdatingSuperTransformer):
        transformed_source = changer.apply_coordinate(coordinate)

    assert transformed_source == 'after_renaming = 1\n'
    assert len(converter_calls) == 1
    assert catch_all_calls == []
    updated_assign, context = converter_calls[0]
    updated_target = updated_assign.targets[0].target
    assert isinstance(updated_target, Name)
    assert updated_target.value == 'after_renaming'
    position = context.position
    assert position.coordinate == Coordinate(None, 'Assign', 1, 0, 1, 10)
    assert position.node_range == CodeRange(CodePosition(1, 0), CodePosition(1, 10))
    assert position.source == source
    assert position.code_before == ''
    assert position.code_after == '\n'
    assert position.code_before + 'before = 1' + position.code_after == position.source


def test_super_transformer_manual_mapping_applies_matching_converter():
    """A manually assembled `SuperTransformer` mapping applies the matching converter: the real replacement rules out a silent no-op, and the callback runs once with the converter meta and the original `Add` position and fragments."""
    contexts = []

    def convert(node: Add, context):
        contexts.append(context)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    converter = Converter(convert, meta={'kind': 'manual'})

    assert run_manual_transformer(converter.get_function_id(), converter) == '1 - 2\n'
    assert len(contexts) == 1
    context = contexts[0]
    position = context.position
    assert context.meta == {'kind': 'manual'}
    assert position.coordinate == Coordinate(None, 'Add', 1, 2, 1, 3)
    assert position.source == '1 + 2\n'
    assert position.node_range == CodeRange(CodePosition(1, 1), CodePosition(1, 4))
    assert position.start_offset == 1
    assert position.end_offset == 4
    assert position.code_before == '1'
    assert position.code_after == '2\n'
    assert position.code_before + ' + ' + position.code_after == position.source


@pytest.mark.parametrize('converter_id', [None, 'missing'])
def test_super_transformer_unknown_or_missing_converter_id_is_noop(converter_id):
    """The source is preserved and the converter is never invoked."""
    calls = []

    def convert(node: Add):
        calls.append(node)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    converter = Converter(convert)

    assert run_manual_transformer(converter_id, converter) == '1 + 2\n'
    assert calls == []


@pytest.mark.parametrize(
    ('converter_name', 'expected_source'),
    [
        pytest.param('first', '1 - 2\n', id='first'),
        pytest.param('second', '1 * 2\n', id='second'),
    ],
)
def test_super_transformer_selects_converter_by_id(converter_name, expected_source):
    """A manual mapping with multiple converters invokes only the converter whose id is requested."""
    calls = []

    def convert_first(node: Add):
        calls.append('first')
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    def convert_second(node: Add):
        calls.append('second')
        return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    first_converter = Converter(convert_first)
    second_converter = Converter(convert_second)
    target_converter = first_converter if converter_name == 'first' else second_converter

    assert run_manual_transformer(target_converter.get_function_id(), first_converter, [second_converter]) == expected_source
    assert calls == [converter_name]


def test_super_transformer_resolves_disambiguated_converter_id():
    """Both converters share one function id, but the unsuffixed coordinate resolves to the first and `#1` to the second; their different replacements identify each registration."""
    replacement_types = []

    def convert(node: Add, replacement_type):
        replacement_types.append(replacement_type)
        return replacement_type(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    first_converter = Converter(partial(convert, replacement_type=Subtract))
    second_converter = Converter(partial(convert, replacement_type=Multiply))
    function_id = first_converter.get_function_id()

    assert first_converter.get_function_id() == second_converter.get_function_id()
    assert run_manual_transformer(function_id, first_converter, [second_converter]) == '1 - 2\n'
    assert run_manual_transformer(f'{function_id}#1', first_converter, [second_converter]) == '1 * 2\n'
    assert replacement_types == [Subtract, Multiply]
