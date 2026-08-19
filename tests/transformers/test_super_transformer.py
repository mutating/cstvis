from libcst import Assign, CSTNode, Name, metadata
from libcst.metadata import CodePosition, CodeRange

from cstvis import Changer, Context, Coordinate
from cstvis.source_offsets import SourceOffsetResolver
from cstvis.transformers.super_transformer import SuperTransformer


def test_converter_receives_updated_parent_with_original_context():
    """
    Pass a child update to the parent converter with the parent's original context.

    The transformer renames the assignment target on child leave, then delegates
    parent leave to `SuperTransformer`. The converter receives the updated
    `Assign` exactly once, while its `Context` retains the original coordinate,
    whitespace-inclusive range, and source.
    """
    source = 'before = 1\n'
    changer = Changer(source)
    converter_calls = []

    @changer.converter
    def capture_assign(node: Assign, context: Context) -> Assign:
        converter_calls.append((node, context))
        return node

    coordinate = next(changer.iterate_coordinates())

    class ChildUpdatingSuperTransformer(SuperTransformer):
        def on_leave(self, original_node: CSTNode, updated_node: CSTNode) -> CSTNode:  # type: ignore[override]
            if isinstance(original_node, Name) and original_node.value == 'before':
                return Name('after')
            return super().on_leave(original_node, updated_node)

    wrapper = metadata.MetadataWrapper(changer.module)
    node_ranges = wrapper.resolve(metadata.WhitespaceInclusivePositionProvider)
    transformer = ChildUpdatingSuperTransformer(
        coordinate,
        changer.converters_by_types,
        changer._comments_by_lines,
        SourceOffsetResolver(wrapper.module, source, node_ranges.values()),
    )
    transformed_source = wrapper.visit(transformer).code

    assert transformed_source == 'after = 1\n'
    assert len(converter_calls) == 1
    updated_assign, context = converter_calls[0]
    updated_target = updated_assign.targets[0].target
    assert isinstance(updated_target, Name)
    assert updated_target.value == 'after'
    position = context.position
    assert position.coordinate == Coordinate(None, 'Assign', 1, 0, 1, 10)
    assert position.node_range == CodeRange(CodePosition(1, 0), CodePosition(1, 10))
    assert position.source == source
