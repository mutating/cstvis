from dataclasses import replace
from functools import partial
from typing import Any, Union

import pytest
from full_match import match
from libcst import (
    Add,
    CSTNode,
    Expr,
    Float,
    If,
    Integer,
    Multiply,
    SimpleString,
    Subtract,
)
from libcst.metadata import CodePosition, CodeRange
from metacode import ParsedComment
from sigmatch import SignatureMismatchError

from cstvis import Changer, Collector, Context, Coordinate
from tests.helpers import collect_nodes


def test_node_type_filter_union_with_cstnode_runs_once_per_matching_node():
    """Although a `Union[Add, CSTNode]` filter is registered for both node types, its wrapper is deduplicated per node, so a stateful filter runs once per `Add` candidate."""
    changer = Changer('1 + 2 + 3')
    calls = []

    @changer.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.filter
    def only_first(node: Union[Add, CSTNode]) -> bool:
        calls.append(node)
        return len(calls) == 1

    assert set(changer.filters_by_types) == {Add, CSTNode}
    assert [wrapper.function for wrapper in changer.filters_by_types[Add]] == [only_first]
    assert [wrapper.function for wrapper in changer.filters_by_types[CSTNode]] == [only_first]

    coordinates = list(changer.iterate_coordinates())

    assert len(calls) == 2
    assert calls[0] is not calls[1]
    assert all(isinstance(node, Add) for node in calls)
    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == '1 - 2 + 3'


@pytest.mark.parametrize('rejecting_filter', ['first', 'second'])
def test_node_type_filters_run_before_bound_filters_and_short_circuit(rejecting_filter):
    """Node-type filters run first in registration order; any rejection vetoes the node globally. The converter-bound filter runs after them even if registered earlier, and a rejecting first or second filter skips every later filter."""
    changer = Changer('1 + 2')
    log = []
    filter_results = {'first': True, 'second': True}

    @changer.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @convert.filter
    def bound(node: Add) -> bool:  # noqa: ARG001
        log.append('bound')
        return True

    @changer.filter
    def filter_first(node: Add) -> bool:  # noqa: ARG001
        log.append('first')
        return filter_results['first']

    @changer.filter
    def filter_second(node: Add) -> bool:  # noqa: ARG001
        log.append('second')
        return filter_results['second']

    assert [wrapper.function for wrapper in changer.filters_by_types[Add]] == [filter_first, filter_second]
    assert [wrapper.function for wrapper in convert.filters] == [bound]

    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 1
    assert log == ['first', 'second', 'bound']
    assert changer.apply_coordinate(coordinates[0]) == '1 - 2'

    filter_results[rejecting_filter] = False
    log.clear()

    assert list(changer.iterate_coordinates()) == []
    expected_log = ['first'] if rejecting_filter == 'first' else ['first', 'second']
    assert log == expected_log


def test_bound_filter_rejects_after_node_type_filter_allows():
    """Even when the node-type filter allows a node, the converter-bound filter runs afterward and can still reject it."""
    changer = Changer('1 + 2')
    log = []

    @changer.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.filter
    def allow(node: Add) -> bool:  # noqa: ARG001
        log.append('node')
        return True

    @convert.filter
    def reject(node: Add) -> bool:  # noqa: ARG001
        log.append('bound')
        return False

    assert list(changer.iterate_coordinates()) == []
    assert log == ['node', 'bound']


def test_converter_bound_filters_short_circuit_in_registration_order():
    """
    Bound filters of one converter are combined with logical AND in registration order.

    The first falsy filter stops the chain for that converter, but another
    converter for the same node still evaluates its own filters and emits.
    """
    changer = Changer('1 + 2')
    log = []

    @changer.converter
    def subtract(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @subtract.filter
    def subtract_allow(node: Add) -> bool:  # noqa: ARG001
        log.append('subtract_allow')
        return True

    @subtract.filter
    def subtract_reject(node: Add) -> bool:  # noqa: ARG001
        log.append('subtract_reject')
        return False

    @subtract.filter
    def subtract_after_reject(node: Add) -> bool:  # noqa: ARG001
        log.append('subtract_after_reject')
        return True

    @changer.converter
    def multiply(node: Add):
        return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @multiply.filter
    def multiply_allow(node: Add) -> bool:  # noqa: ARG001
        log.append('multiply_allow')
        return True

    assert [wrapper.function for wrapper in subtract.filters] == [
        subtract_allow,
        subtract_reject,
        subtract_after_reject,
    ]
    assert [wrapper.function for wrapper in multiply.filters] == [multiply_allow]

    coordinates = list(changer.iterate_coordinates())

    assert log == ['subtract_allow', 'subtract_reject', 'multiply_allow']
    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == '1 * 2'


@pytest.mark.parametrize('filter_kind', ['node_type', 'bound_filter'])
def test_apply_coordinate_does_not_reevaluate_discovery_filters(filter_kind):
    """
    Coordinate discovery is the only stage that evaluates filters.

    A coordinate found while the filter allowed the node remains applicable after
    the filter changes to rejecting; a new discovery pass then yields nothing and
    evaluates the filter again.
    """
    changer = Changer('1 + 2')
    allow = True
    filter_calls = []

    @changer.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    def gate(node: Add) -> bool:
        filter_calls.append(node)
        return allow

    if filter_kind == 'node_type':
        changer.filter(gate)
    else:
        convert.filter(gate)

    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 1
    assert len(filter_calls) == 1

    allow = False

    assert changer.apply_coordinate(coordinates[0]) == '1 - 2'
    assert len(filter_calls) == 1
    assert list(changer.iterate_coordinates()) == []
    assert len(filter_calls) == 2


def test_node_type_filter_applies_to_all_converters():
    """
    A node-type filter remains global for every converter targeting the node.

    One rejecting gate suppresses both converters; once the gate allows the node,
    both converter choices are emitted.
    """
    changer = Changer('5 + 5')
    allow = False

    @changer.converter
    def subtract(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.converter
    def multiply(node: Add):
        return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.filter
    def gate(node: Add) -> bool:  # noqa: ARG001
        return allow

    assert list(changer.iterate_coordinates()) == []
    assert changer.filters_by_types[Add][0].function is gate
    assert subtract.filters == []
    assert multiply.filters == []

    allow = True

    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 2
    results = {coordinate.converter_id: changer.apply_coordinate(coordinate) for coordinate in coordinates}
    assert results == {
        subtract.get_function_id(): '5 - 5',
        multiply.get_function_id(): '5 * 5',
    }


def test_collector_converter_bound_filter_does_not_become_global():
    """
    A bound filter on a collected converter never becomes a node-type filter.

    In a combined collector, rejecting one converter must leave another
    converter for the same Add node untouched and emit only its coordinate.
    """
    collector_1 = Collector()
    collector_2 = Collector()
    filter_calls = []

    @collector_1.converter
    def subtract(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @subtract.filter
    def reject(node: Add) -> bool:
        filter_calls.append(node)
        return False

    @collector_2.converter
    def multiply(node: Add):
        return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    changer = Changer('1 + 2', collector=collector_1 + collector_2)
    coordinates = list(changer.iterate_coordinates())

    assert len(filter_calls) == 1
    assert isinstance(filter_calls[0], Add)
    assert multiply.filters == []
    assert not changer.filters_by_types
    assert len(coordinates) == 1
    assert coordinates[0].converter_id == multiply.get_function_id()
    assert changer.apply_coordinate(coordinates[0]) == '1 * 2'


@pytest.mark.parametrize(
    ('source', 'expected_source'),
    [
        pytest.param('1 + 2', '1 - 2', id='plain'),
        pytest.param('# lead\nx = 1 + 2\n', '# lead\nx = 1 - 2\n', id='comment-prefix'),
        pytest.param('\ufeffx = 1 + 2\n', '\ufeffx = 1 - 2\n', id='bom'),
    ],
)
@pytest.mark.parametrize(
    'variant_builder',
    [
        pytest.param(lambda coordinate: replace(coordinate, converter_id='missing'), id='missing-id'),
        pytest.param(lambda coordinate: replace(coordinate, converter_id=None), id='none-id'),
        pytest.param(lambda coordinate: replace(coordinate, converter_id=f'{coordinate.converter_id}#1'), id='suffixed-id'),
        pytest.param(lambda coordinate: replace(coordinate, class_name='Subtract'), id='wrong-class'),
        pytest.param(lambda coordinate: replace(coordinate, start_line=coordinate.start_line + 1), id='start-line'),
        pytest.param(lambda coordinate: replace(coordinate, start_column=coordinate.start_column + 1), id='start-column'),
        pytest.param(lambda coordinate: replace(coordinate, end_line=coordinate.end_line + 1), id='end-line'),
        pytest.param(lambda coordinate: replace(coordinate, end_column=coordinate.end_column + 1), id='end-column'),
    ],
)
def test_apply_coordinate_with_unmatched_target_is_a_noop(variant_builder, source, expected_source):
    """
    Coordinates whose converter id, node type or position do not match are ignored.

    They preserve the source and never call any converter. A valid coordinate for
    the same position still applies normally.
    """
    changer = Changer(source)
    converter_calls = []

    @changer.converter
    def convert(node: Add):
        converter_calls.append(node)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    coordinate = next(changer.iterate_coordinates())

    assert changer.apply_coordinate(variant_builder(coordinate)) == source
    assert converter_calls == []
    assert changer.apply_coordinate(coordinate) == expected_source
    assert len(converter_calls) == 1


def test_each_iterate_coordinates_call_reevaluates_filters_and_is_independent():
    """
    Every iterate_coordinates call builds an independent traversal.

    Repeated passes over unchanged registrations produce identical coordinates,
    a partially consumed generator does not disturb a new one, and stateful
    filters are evaluated again for every traversal.
    """
    changer = Changer('1 + 2 + 3')

    @changer.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    first_pass = list(changer.iterate_coordinates())
    second_pass = list(changer.iterate_coordinates())

    assert first_pass == second_pass

    generator = changer.iterate_coordinates()
    first_coordinate = next(generator)
    fresh_pass = list(changer.iterate_coordinates())
    remaining = list(generator)

    assert len(fresh_pass) == 2
    assert fresh_pass[0] == first_coordinate
    assert remaining == fresh_pass[1:]

    stateful_changer = Changer('1 + 2 + 3')
    filter_calls = []

    @stateful_changer.converter
    def stateful_convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @stateful_convert.filter
    def accept_first_call(node: Add) -> bool:
        filter_calls.append(node)
        return len(filter_calls) == 1

    assert len(list(stateful_changer.iterate_coordinates())) == 1
    assert len(filter_calls) == 2
    assert list(stateful_changer.iterate_coordinates()) == []
    assert len(filter_calls) == 4
    assert filter_calls[0] is not filter_calls[1]
    assert filter_calls[2] is not filter_calls[3]


def test_converter_bound_filter_dispatches_for_each_type_in_union():
    """
    Bound-filter candidates come from the converter annotation, not the filter annotation.

    For a Union[Add, Subtract] converter, a filter annotated only with Add is still
    called for Subtract and decides eligibility through its body.
    """
    changer = Changer('5 - 4 + 3')
    seen_types = []

    @changer.converter
    def convert(node: Union[Add, Subtract]):
        return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @convert.filter
    def only_add(node: Add) -> bool:
        seen_types.append(type(node))
        return isinstance(node, Add)

    coordinates = list(changer.iterate_coordinates())

    assert len(seen_types) == 2
    assert set(seen_types) == {Subtract, Add}
    assert [coordinate.class_name for coordinate in coordinates] == ['Add']
    assert changer.apply_coordinate(coordinates[0]) == '5 - 4 * 3'


def test_bound_filter_of_catch_all_converter_receives_every_visited_node():
    """
    A catch-all converter dispatches its bound filter for every visited node.

    The filter's own Add annotation is ignored: it receives the same nodes in the
    same order as a plain CST traversal and must decide from the node itself.
    """
    changer = Changer('1 + 2')
    seen_nodes = []
    visited_nodes = collect_nodes(changer.module)

    @changer.converter
    def convert(node: CSTNode):
        if isinstance(node, Add):
            return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)
        return node

    @convert.filter
    def only_add(node: Add) -> bool:
        seen_nodes.append(node)
        return isinstance(node, Add)

    coordinates = list(changer.iterate_coordinates())

    assert len(seen_nodes) == len(visited_nodes)
    assert all(seen.deep_equals(visited) for seen, visited in zip(seen_nodes, visited_nodes))
    assert [coordinate.class_name for coordinate in coordinates] == ['Add']
    assert changer.apply_coordinate(coordinates[0]) == '1 - 2'


@pytest.mark.parametrize('catch_all_first', [False, True], ids=['specific-first', 'catch-all-first'])
def test_specific_and_catch_all_converters_both_emit_for_same_node(catch_all_first):
    """
    Specific and catch-all converters coexist for one node in a stable order.

    The specific converter is listed before the catch-all one regardless of
    registration order; both provide independent Add coordinates and each
    coordinate applies its own converter result.
    """
    changer = Changer('1 + 2')

    def specific_impl(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    def catch_all_impl(node: CSTNode):
        if isinstance(node, Add):
            return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)
        return node

    if catch_all_first:
        catch_all = changer.converter(catch_all_impl)
        specific = changer.converter(specific_impl)
    else:
        specific = changer.converter(specific_impl)
        catch_all = changer.converter(catch_all_impl)

    coordinates = [coordinate for coordinate in changer.iterate_coordinates() if coordinate.class_name == 'Add']

    assert len(coordinates) == 2
    assert [coordinate.converter_id for coordinate in coordinates] == [
        specific.get_function_id(),
        catch_all.get_function_id(),
    ]
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1 - 2', '1 * 2']


@pytest.mark.parametrize('predicate_result', [True, False], ids=['allow', 'reject'])
def test_bound_filter_receives_nodes_matched_by_shortcut_converter(predicate_result):
    """
    Bound filters follow the converter annotations for built-in shortcuts.

    A `Union[int, float, str]` converter maps to `Integer`, `Float`, and
    `SimpleString` nodes. Its `CSTNode`-annotated bound filter sees exactly those
    three node types in source order, and its return value decides whether the
    coordinates are emitted.
    """
    changer = Changer('a = 5\nb = 5.0\nc = "x"\n')
    seen_nodes = []

    @changer.converter
    def convert(node: Union[int, float, str]):
        return node

    @convert.filter
    def filter_nodes(node: CSTNode) -> bool:
        seen_nodes.append(node)
        return predicate_result

    coordinates = list(changer.iterate_coordinates())

    assert not changer.filters_by_types
    assert [type(node) for node in seen_nodes] == [Integer, Float, SimpleString]
    if predicate_result:
        assert [coordinate.class_name for coordinate in coordinates] == ['Integer', 'Float', 'SimpleString']
        assert {coordinate.converter_id for coordinate in coordinates} == {convert.get_function_id()}
    else:
        assert coordinates == []


def test_collector_filters_run_before_changer_filters():
    """
    Collected filters run before local Changer filters targeting the same node type.

    The collector filter can short-circuit the local filter when it rejects, and
    when both allow the node the calls appear in collector-then-local order.
    """
    collector = Collector()
    collector_allows = True
    local_allows = True
    log = []

    @collector.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @collector.filter
    def collector_filter(node: Add) -> bool:  # noqa: ARG001
        log.append('collector')
        return collector_allows

    changer = Changer('1 + 2', collector=collector)

    @changer.filter
    def local_filter(node: Add) -> bool:  # noqa: ARG001
        log.append('local')
        return local_allows

    assert len(list(changer.iterate_coordinates())) == 1
    assert log == ['collector', 'local']

    collector_allows = False
    log.clear()

    assert list(changer.iterate_coordinates()) == []
    assert log == ['collector']

    collector_allows = True
    local_allows = False
    log.clear()

    assert list(changer.iterate_coordinates()) == []
    assert log == ['collector', 'local']


def test_collector_converters_run_before_local_converters():
    """Collected converters run before local Changer converters for the same node."""
    collector = Collector()

    @collector.converter
    def collected(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    changer = Changer('1 + 2', collector=collector)

    @changer.converter
    def local(node: Add):
        return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    coordinates = list(changer.iterate_coordinates())

    assert [coordinate.converter_id for coordinate in coordinates] == [
        collected.get_function_id(),
        local.get_function_id(),
    ]
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1 - 2', '1 * 2']


def test_stateful_node_type_filter_runs_once_per_node_not_per_converter():
    """
    A node-type filter runs once per matching node, not once per converter.

    With two converters and two Add nodes, the stateful filter sees exactly two
    calls and admits only the first node for both converters.
    """
    changer = Changer('1 + 2 + 3')
    filter_calls = []

    @changer.converter
    def subtract(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.converter
    def multiply(node: Add):
        return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.filter
    def only_first_node(node: Add) -> bool:
        filter_calls.append(node)
        return len(filter_calls) == 1

    coordinates = list(changer.iterate_coordinates())

    assert len(filter_calls) == 2
    assert filter_calls[0] is not filter_calls[1]
    assert len(coordinates) == 2
    results = {coordinate.converter_id: changer.apply_coordinate(coordinate) for coordinate in coordinates}
    assert results == {
        subtract.get_function_id(): '1 - 2 + 3',
        multiply.get_function_id(): '1 * 2 + 3',
    }


def test_concrete_node_type_filters_run_before_cstnode_filters():
    """Concrete-type filters run before `CSTNode` filters even when the broad filter was registered first, so a rejecting concrete filter prevents the broad filter from running."""
    changer = Changer('1 + 2')
    log = []
    allow = True

    @changer.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.filter
    def broad(node: CSTNode) -> bool:  # noqa: ARG001
        log.append('broad')
        return True

    @changer.filter
    def specific(node: Add) -> bool:  # noqa: ARG001
        log.append('specific')
        return allow

    assert len(list(changer.iterate_coordinates())) == 1
    assert log == ['specific', 'broad']

    allow = False
    log.clear()

    assert list(changer.iterate_coordinates()) == []
    assert log == ['specific']


def test_collector_self_addition_does_not_duplicate_converter_coordinates():
    """Collector self-addition stores the same Converter twice, but emits one coordinate with the converter's bare function-based id."""
    collector = Collector()
    filter_calls = []

    @collector.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @convert.filter
    def record_filter(node: Add) -> bool:
        filter_calls.append(node)
        return True

    changer = Changer('1 + 2', collector=collector + collector)

    assert changer.converters_by_types[Add] == [convert, convert]

    coordinates = list(changer.iterate_coordinates())

    assert len(filter_calls) == 1
    assert len(coordinates) == 1
    assert coordinates[0].converter_id == convert.get_function_id()
    assert changer.apply_coordinate(coordinates[0]) == '1 - 2'


@pytest.mark.parametrize('filter_kind', ['node_type', 'bound_filter'])
@pytest.mark.parametrize(
    ('filter_return_value', 'expected_allowed'),
    [
        pytest.param(1, True, id='truthy-int'),
        pytest.param([1], True, id='non-empty-list'),
        pytest.param('x', True, id='non-empty-string'),
        pytest.param(0, False, id='falsy-int'),
        pytest.param([], False, id='empty-list'),
        pytest.param('', False, id='empty-string'),
        pytest.param(None, False, id='none'),
    ],
)
def test_filters_use_truthiness_not_strict_bool(filter_kind, filter_return_value, expected_allowed):
    """
    Filters use truthiness semantics rather than identity with True.

    Any truthy return value allows the converter; any falsy value rejects it for
    both node-type and converter-bound filters.
    """
    changer = Changer('1 + 2')
    predicate_calls = []

    @changer.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    def predicate(node: Add) -> Any:
        predicate_calls.append(node)
        return filter_return_value

    if filter_kind == 'node_type':
        changer.filter(predicate)
    else:
        convert.filter(predicate)

    coordinates = list(changer.iterate_coordinates())

    assert len(predicate_calls) == 1
    assert isinstance(predicate_calls[0], Add)

    if expected_allowed:
        assert len(coordinates) == 1
        assert changer.apply_coordinate(coordinates[0]) == '1 - 2'
    else:
        assert coordinates == []


def test_converter_exception_propagates_and_later_application_succeeds():
    """
    Converter failures propagate from apply_coordinate and are not swallowed.

    A converter can succeed after its failing state is cleared.
    """
    changer = Changer('1 + 2')
    fail = True
    converter_calls = []

    @changer.converter
    def convert(node: Add):
        converter_calls.append(node)
        if fail:
            raise RuntimeError('boom')
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    coordinate = next(changer.iterate_coordinates())

    with pytest.raises(RuntimeError, match='boom'):
        changer.apply_coordinate(coordinate)

    fail = False

    assert changer.apply_coordinate(coordinate) == '1 - 2'
    assert len(converter_calls) == 2


@pytest.mark.parametrize(
    ('filter_scope', 'message'),
    [('node_type', 'global boom'), ('bound_filter', 'bound boom')],
)
def test_filter_exceptions_propagate_from_discovery(filter_scope, message):
    """Node-type and converter-bound filter exceptions reach the caller during discovery, before any coordinate is emitted."""
    changer = Changer('1 + 2')

    @changer.converter
    def convert(node: Add):
        return node

    def broken_filter(node: Add) -> bool:  # noqa: ARG001
        raise ValueError(message)

    if filter_scope == 'node_type':
        changer.filter(broken_filter)
    else:
        convert.filter(broken_filter)

    iterator = changer.iterate_coordinates()
    with pytest.raises(ValueError, match=message):
        next(iterator)


def test_invalid_callback_annotations_are_rejected_atomically():
    """Invalid converter and filter annotations — a plain non-CST class and a union containing one — are rejected before type mappings change; valid registrations remain untouched."""
    changer = Changer('1 + 2')
    message = match('The type annotation for the first argument of the function must be descended from the libcst.CSTNode class.')

    @changer.converter
    def valid_converter(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.filter
    def valid_filter(node: Add) -> bool:  # noqa: ARG001
        return True

    converters_snapshot = {node_type: list(converters) for node_type, converters in changer.converters_by_types.items()}
    filters_snapshot = {node_type: list(filters) for node_type, filters in changer.filters_by_types.items()}

    with pytest.raises(TypeError, match=message):
        @changer.converter
        def invalid_converter(node: object):
            return node

    assert changer.converters_by_types == converters_snapshot

    with pytest.raises(TypeError, match=message):
        @changer.filter
        def invalid_filter(_node: object) -> bool:
            return True

    assert changer.filters_by_types == filters_snapshot

    with pytest.raises(TypeError, match=message):
        @changer.converter
        def invalid_converter_union(node: Union[Add, object]):
            return node

    assert changer.converters_by_types == converters_snapshot

    with pytest.raises(TypeError, match=message):
        @changer.filter
        def invalid_filter_union(_node: Union[Add, object]) -> bool:
            return True

    assert changer.filters_by_types == filters_snapshot
    assert changer.converters_by_types[Add] == [valid_converter]
    assert changer.filters_by_types[Add][0].function is valid_filter


def test_collector_self_addition_does_not_repeat_filter_calls():
    """
    Repeating the same node-type filter object does not duplicate its calls.

    Collector self-addition stores the same wrapper twice, but the filter is
    deduplicated before evaluation and runs exactly once per matching node.
    """
    collector = Collector()
    calls = []

    @collector.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @collector.filter
    def allow(node: Add) -> bool:
        calls.append(node)
        return True

    changer = Changer('1 + 2 + 3', collector=collector + collector)
    filter_wrapper = changer.filters_by_types[Add][0]

    assert changer.filters_by_types[Add] == [filter_wrapper, filter_wrapper]
    assert len(list(changer.iterate_coordinates())) == 2
    assert len(calls) == 2
    assert calls[0] is not calls[1]
    assert all(isinstance(node, Add) for node in calls)


def test_same_filter_function_registered_in_two_collectors_keeps_both_wrappers():
    """
    Two wrappers around one filter function are not deduplicated.

    Registering the same function in two collectors with different metadata
    keeps both wrappers, so the filter sees both metadata copies.
    """
    collector_one = Collector(meta={'filter': 'one'})
    collector_two = Collector(meta={'filter': 'two'})
    received_meta = []

    def gate(node: Add, context: Context) -> bool:  # noqa: ARG001
        received_meta.append(context.meta)
        return True

    collector_one.filter(gate)
    collector_two.filter(gate)

    changer = Changer('1 + 2', collector=collector_one + collector_two)

    @changer.converter
    def convert(node: Add):
        return node

    assert len(list(changer.iterate_coordinates())) == 1
    assert received_meta == [{'filter': 'one'}, {'filter': 'two'}]
    filter_wrappers = changer.filters_by_types[Add]
    assert len(filter_wrappers) == 2
    assert filter_wrappers[0] is not filter_wrappers[1]
    assert [wrapper.meta for wrapper in filter_wrappers] == [{'filter': 'one'}, {'filter': 'two'}]


def test_node_type_filters_are_not_called_without_matching_converter():
    """
    Node-type filters only run when the node has a matching converter.

    A filter registered for Add does not run for Add nodes when only a Subtract
    converter exists, while the Subtract filter still runs for its own node.
    """
    changer = Changer('1 + 2 - 3')
    add_calls = []
    subtract_calls = []

    @changer.converter
    def convert(node: Subtract):
        return node

    @changer.filter
    def observe_add(node: Add) -> bool:
        add_calls.append(node)
        return True

    @changer.filter
    def observe_subtract(node: Subtract) -> bool:
        subtract_calls.append(node)
        return True

    assert [wrapper.function for wrapper in changer.filters_by_types[Add]] == [observe_add]
    assert [wrapper.function for wrapper in changer.filters_by_types[Subtract]] == [observe_subtract]

    coordinates = list(changer.iterate_coordinates())

    assert [coordinate.class_name for coordinate in coordinates] == ['Subtract']
    assert add_calls == []
    assert len(subtract_calls) == 1
    assert isinstance(subtract_calls[0], Subtract)


@pytest.mark.parametrize('registration_kind', ['changer', 'collector'])
def test_filters_are_not_called_without_converters(registration_kind):
    """
    Filters are not evaluated when no converter can produce a coordinate.

    This holds for filters registered directly on the Changer and through a
    Collector.
    """
    calls = []

    if registration_kind == 'changer':
        changer = Changer('1 + 2')

        @changer.filter
        def observe(node: Add) -> bool:
            calls.append(node)
            return True
    else:
        collector = Collector()

        @collector.filter
        def observe(node: Add) -> bool:
            calls.append(node)
            return True

        changer = Changer('1 + 2', collector=collector)

    assert [wrapper.function for wrapper in changer.filters_by_types[Add]] == [observe]
    assert list(changer.iterate_coordinates()) == []
    assert calls == []

    @changer.converter
    def convert(node: Add):
        return node

    assert len(list(changer.iterate_coordinates())) == 1
    assert len(calls) == 1
    assert isinstance(calls[0], Add)


def test_concrete_and_cstnode_filters_run_for_catch_all_converter():
    """
    A catch-all converter runs concrete and `CSTNode` filters in order for
    matching nodes.

    The concrete filter sees only `Add` nodes, the broad filter sees every
    visited node, and for `Add` the concrete filter runs before the broad one.
    """
    changer = Changer('1 + 2')
    log = []

    @changer.converter
    def convert(node: CSTNode):
        return node

    @changer.filter
    def concrete(node: Add) -> bool:
        log.append(('concrete', type(node).__name__))
        return True

    @changer.filter
    def broad(node: CSTNode) -> bool:
        log.append(('broad', type(node).__name__))
        return True

    coordinates = list(changer.iterate_coordinates())
    visited_nodes = collect_nodes(changer.module)

    assert len(coordinates) == len(visited_nodes)
    assert [coordinate.class_name for coordinate in coordinates] == [type(node).__name__ for node in visited_nodes]
    assert [coordinate.converter_id for coordinate in coordinates] == [convert.get_function_id()] * len(visited_nodes)
    concrete_entries = [entry for entry in log if entry[0] == 'concrete']
    broad_entries = [entry for entry in log if entry[0] == 'broad']
    assert [name for _, name in concrete_entries] == ['Add']
    assert [name for _, name in broad_entries] == [type(node).__name__ for node in visited_nodes]
    concrete_add_index = log.index(('concrete', 'Add'))
    broad_add_index = log.index(('broad', 'Add'))
    assert concrete_add_index < broad_add_index


def test_bound_filter_dispatches_by_converter_annotation_not_filter_annotation():
    """With a `Subtract` converter and an `Add` filter annotation, the `Add` node never reaches the filter; only the `Subtract` candidate does."""
    changer = Changer('1 + 2 - 3')
    calls = []

    @changer.converter
    def convert(node: Subtract):
        return node

    @convert.filter
    def observe(node: Add) -> bool:
        calls.append(node)
        return True

    coordinates = list(changer.iterate_coordinates())

    assert [coordinate.class_name for coordinate in coordinates] == ['Subtract']
    assert len(calls) == 1
    assert isinstance(calls[0], Subtract)


@pytest.mark.parametrize('filter_scope', ['node_type', 'bound_filter'])
def test_rejecting_filter_does_not_prune_nested_candidates(filter_scope):
    """The rejected node is a non-leaf `Expr`; `Add` candidates inside it are still discovered by both filter scopes."""
    changer = Changer('1 + 2 + 3')
    rejected = []

    @changer.converter
    def convert(node: CSTNode):
        return node

    if filter_scope == 'node_type':
        @changer.filter
        def reject(node: Expr) -> bool:
            rejected.append(node)
            return False
    else:
        @convert.filter
        def reject(node: CSTNode) -> bool:
            if isinstance(node, Expr):
                rejected.append(node)
                return False
            return True

    coordinates = list(changer.iterate_coordinates())
    add_coordinates = [coordinate for coordinate in coordinates if coordinate.class_name == 'Add']
    expr_coordinates = [coordinate for coordinate in coordinates if coordinate.class_name == 'Expr']

    assert len(rejected) == 1
    assert len(add_coordinates) == 2
    assert expr_coordinates == []
    visited_nodes = collect_nodes(changer.module)
    assert [coordinate.class_name for coordinate in coordinates] == [
        type(node).__name__ for node in visited_nodes if not isinstance(node, Expr)
    ]


def test_collected_filters_and_converters_keep_registration_order():
    """
    One Collector preserves registration order for both filters and converters.

    Filters log in registration order, and coordinates are emitted in converter
    registration order for the same Add node.
    """
    collector = Collector()
    log = []

    @collector.converter
    def subtract(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @collector.converter
    def multiply(node: Add):
        return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @collector.filter
    def first_filter(node: Add) -> bool:  # noqa: ARG001
        log.append('first')
        return True

    @collector.filter
    def second_filter(node: Add) -> bool:  # noqa: ARG001
        log.append('second')
        return True

    changer = Changer('1 + 2', collector=collector)
    coordinates = list(changer.iterate_coordinates())

    assert log == ['first', 'second']
    assert [coordinate.converter_id for coordinate in coordinates] == [
        subtract.get_function_id(),
        multiply.get_function_id(),
    ]
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1 - 2', '1 * 2']


def test_collector_filter_applies_to_locally_registered_converter():
    """
    A Collector filter is global and gates converters registered on the Changer.

    Collector and Changer registrations are merged independently, so a rejecting
    collected filter suppresses a local converter for the same node.
    """
    collector = Collector()

    @collector.filter
    def reject(node: Add) -> bool:  # noqa: ARG001
        return False

    changer = Changer('1 + 2', collector=collector)

    @changer.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    assert changer.converters_by_types[Add] == [convert]
    assert [wrapper.function for wrapper in changer.filters_by_types[Add]] == [reject]
    assert list(changer.iterate_coordinates()) == []


def test_converter_bound_filter_rejects_only_its_own_converter():
    """A converter-bound filter restricts only its own converter; other converters still emit for the same node."""
    changer = Changer('1 + 2 + 3')
    subtract_filter_calls = []

    @changer.converter
    def subtract(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @subtract.filter
    def only_first(node: Add) -> bool:
        subtract_filter_calls.append(node)
        return len(subtract_filter_calls) <= 1

    @changer.converter
    def multiply(node: Add):
        return Multiply(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    results = [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()]

    assert len(subtract_filter_calls) == 2
    assert subtract_filter_calls[0] is not subtract_filter_calls[1]
    assert results == ['1 - 2 + 3', '1 * 2 + 3', '1 + 2 * 3']


@pytest.mark.parametrize('filter_annotation', [Subtract, object], ids=['unrelated-cst', 'non-cst'])
def test_converter_bound_filter_ignores_its_annotation(filter_annotation):
    """
    A converter-bound filter ignores its own node annotation during dispatch.

    Both an unrelated CST type and a non-CST type are accepted without annotation
    validation, and the filter still receives the Add candidate.
    """
    changer = Changer('1 + 2')
    received_nodes = []

    @changer.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    def reject(node):
        received_nodes.append(node)
        return False

    reject.__annotations__['node'] = filter_annotation
    convert.filter(reject)

    assert [wrapper.function for wrapper in convert.filters] == [reject]
    assert not changer.filters_by_types
    assert list(changer.iterate_coordinates()) == []
    assert len(received_nodes) == 1
    assert isinstance(received_nodes[0], Add)


@pytest.mark.parametrize('registration_kind', ['changer', 'collector'])
def test_rejected_bound_filter_hides_coordinate_until_allowed(registration_kind):
    """A rejecting bound filter suppresses the coordinate for direct and Collector registration; once it allows the node, the same registration produces the expected replacement exactly once."""
    converter_calls = []
    allow = False

    def convert(node: Add):
        converter_calls.append(node)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    if registration_kind == 'changer':
        changer = Changer('1 + 2')
        converter = changer.converter(convert)
    else:
        collector = Collector()
        converter = collector.converter(convert)
        changer = Changer('1 + 2', collector=collector)

    @converter.filter
    def gate(node: Add) -> bool:  # noqa: ARG001
        return allow

    assert [wrapper.function for wrapper in converter.filters] == [gate]
    assert not changer.filters_by_types

    assert list(changer.iterate_coordinates()) == []
    assert converter_calls == []

    allow = True

    assert [changer.apply_coordinate(coordinate) for coordinate in changer.iterate_coordinates()] == ['1 - 2']
    assert len(converter_calls) == 1


def test_converter_bound_filter_with_unsupported_arity_is_rejected(unfold):
    """
    Converter-bound filters with unsupported arity are rejected at registration.

    Zero-argument and three-argument filters fail with SignatureMismatchError for
    both direct and called decorator forms, and leave existing filters unchanged.
    """
    changer = Changer('1 + 2')
    message = match('A function that takes a CST node and a context is expected.')

    @changer.converter
    def convert(node: Add):
        return node

    @convert.filter
    def keep(node: Add) -> bool:  # noqa: ARG001
        return True

    filters_before = list(convert.filters)

    with pytest.raises(SignatureMismatchError, match=message):
        @unfold(convert.filter)
        def filter_without_parameters():
            return True

    with pytest.raises(SignatureMismatchError, match=message):
        @unfold(convert.filter)
        def filter_with_extra_parameter(node: Add, context: Context, extra: str):  # noqa: ARG001
            return True

    assert convert.filters == filters_before
    assert filters_before[0].function is keep
    assert not changer.filters_by_types


def test_converter_bound_filter_is_not_duplicated_for_union_with_cstnode():
    """
    A converter registered for both Add and CSTNode evaluates its bound filter once per visited node.

    Duplicate converter entries and duplicate Add candidates are removed, so each
    Add node is emitted once.
    """
    changer = Changer('1 + 2 + 3')
    all_filter_calls = []
    add_filter_calls = []
    converter_call_types = []
    visited_nodes = collect_nodes(changer.module)

    @changer.converter
    def convert(node: Union[Add, CSTNode]):
        converter_call_types.append(type(node))
        if not isinstance(node, Add):
            return node
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @convert.filter
    def allow_only_add(node: CSTNode) -> bool:
        all_filter_calls.append(node)
        if not isinstance(node, Add):
            return False

        add_filter_calls.append(node)
        return True

    assert changer.converters_by_types[Add] == [convert]
    assert changer.converters_by_types[CSTNode] == [convert]
    assert [wrapper.function for wrapper in convert.filters] == [allow_only_add]
    assert not changer.filters_by_types

    coordinates = list(changer.iterate_coordinates())

    assert [coordinate.class_name for coordinate in coordinates] == ['Add', 'Add']
    assert [coordinate.converter_id for coordinate in coordinates] == [convert.get_function_id(), convert.get_function_id()]
    assert len(all_filter_calls) == len(visited_nodes)
    assert all(seen.deep_equals(visited) for seen, visited in zip(all_filter_calls, visited_nodes))
    assert len(add_filter_calls) == 2
    assert add_filter_calls[0] is not add_filter_calls[1]
    assert converter_call_types == []
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1 - 2 + 3', '1 + 2 - 3']
    assert converter_call_types == [Add, Add]


@pytest.mark.parametrize('predicate_result', [True, False], ids=['allow', 'reject'])
@pytest.mark.parametrize(
    ('annotation', 'expected_type'),
    [
        pytest.param(int, Integer, id='int-to-integer'),
        pytest.param(float, Float, id='float-to-float'),
        pytest.param(str, SimpleString, id='str-to-simple-string'),
    ],
)
def test_node_type_filter_follows_builtin_shortcut(annotation, expected_type, predicate_result):
    """
    A node-type filter with a built-in shortcut annotation is dispatched by its mapped type.

    The filter runs only for the matching value node. Other nodes keep their
    catch-all converter coordinates regardless of the filter result.
    """
    changer = Changer('a = 5\nb = 5.0\nc = "x"\n')
    seen_nodes = []

    @changer.converter
    def convert(node: CSTNode):
        return node

    def predicate(node):
        seen_nodes.append(node)
        return predicate_result

    predicate.__annotations__['node'] = annotation
    changer.filter(predicate)

    assert set(changer.filters_by_types) == {expected_type}
    assert [wrapper.function for wrapper in changer.filters_by_types[expected_type]] == [predicate]

    coordinates = list(changer.iterate_coordinates())
    visited_names = [type(node).__name__ for node in collect_nodes(changer.module)]
    expected_names = visited_names if predicate_result else [name for name in visited_names if name != expected_type.__name__]

    assert len(seen_nodes) == 1
    assert isinstance(seen_nodes[0], expected_type)
    assert [coordinate.class_name for coordinate in coordinates] == expected_names


@pytest.mark.parametrize(
    ('annotation', 'expected_types'),
    [
        pytest.param(Union[int, str], {Integer, SimpleString}, id='shortcuts'),
        pytest.param(Union[Add, int], {Add, Integer}, id='mixed'),
    ],
)
@pytest.mark.parametrize('predicate_result', [True, False], ids=['allow', 'reject'])
def test_node_type_filter_union_with_shortcut_annotations(annotation, expected_types, predicate_result):
    """
    A node-type filter union registers each builtin shortcut and dispatches to
    every mapped node.

    The filter sees each matching node exactly once; its return value decides
    whether those nodes keep their coordinates.
    """
    changer = Changer('a = 5\nb = "x"\n1 + 2')
    seen_nodes = []

    @changer.converter
    def convert(node: CSTNode):
        return node

    def predicate(node):
        seen_nodes.append(node)
        return predicate_result

    predicate.__annotations__['node'] = annotation
    changer.filter(predicate)

    assert set(changer.filters_by_types) == expected_types
    coordinates = list(changer.iterate_coordinates())
    visited_nodes = collect_nodes(changer.module)
    expected_seen_nodes = [node for node in visited_nodes if type(node) in expected_types]

    assert [type(node) for node in seen_nodes] == [type(node) for node in expected_seen_nodes]
    assert all(actual.deep_equals(expected) for actual, expected in zip(seen_nodes, expected_seen_nodes))
    if predicate_result:
        expected_class_names = [type(node).__name__ for node in visited_nodes]
    else:
        expected_class_names = [
            type(node).__name__ for node in visited_nodes if type(node) not in expected_types
        ]
    assert [coordinate.class_name for coordinate in coordinates] == expected_class_names


def test_collected_filters_from_combined_collectors_run_in_order():
    """Filters merged from two collectors run left-then-right during discovery."""
    collector_1 = Collector()
    collector_2 = Collector()
    left_allows = True
    right_allows = True
    log = []

    @collector_1.filter
    def left_filter(node: Add) -> bool:  # noqa: ARG001
        log.append('left')
        return left_allows

    @collector_2.filter
    def right_filter(node: Add) -> bool:  # noqa: ARG001
        log.append('right')
        return right_allows

    changer = Changer('1 + 2', collector=collector_1 + collector_2)

    @changer.converter
    def convert(node: Add):
        return node

    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 1
    assert log == ['left', 'right']

    left_allows = False
    log.clear()

    assert list(changer.iterate_coordinates()) == []
    assert log == ['left']

    left_allows = True
    right_allows = False
    log.clear()

    assert list(changer.iterate_coordinates()) == []
    assert log == ['left', 'right']


def test_cstnode_filter_runs_for_every_node_with_catch_all_converter():
    """
    A `CSTNode`-annotated filter sees every visited node under a catch-all converter.

    Rejecting Add suppresses only Add coordinates while all other nodes still
    receive coordinates from the catch-all converter.
    """
    changer = Changer('1 + 2')
    seen_nodes = []

    @changer.converter
    def convert(node: CSTNode):
        return node

    @changer.filter
    def gate(node: CSTNode) -> bool:
        seen_nodes.append(node)
        return not isinstance(node, Add)

    coordinates = list(changer.iterate_coordinates())
    visited_nodes = collect_nodes(changer.module)

    assert len(seen_nodes) == len(visited_nodes)
    assert all(seen.deep_equals(visited) for seen, visited in zip(seen_nodes, visited_nodes))
    visited_names = [type(node).__name__ for node in visited_nodes]
    assert [coordinate.class_name for coordinate in coordinates] == [name for name in visited_names if name != 'Add']


@pytest.mark.parametrize('rejected_converter', ['specific', 'catch_all'])
def test_rejecting_bound_filter_preserves_other_converter_id(rejected_converter):
    """
    A rejecting bound filter suppresses only the converter it belongs to.

    Both converters share one function id. When the specific converter is
    rejected, the surviving catch-all Add coordinate carries `#1`; when the
    catch-all converter is rejected, the surviving specific Add coordinate
    carries the base id.
    """
    changer = Changer('1 + 2')

    def convert(node: Add, replacement):
        if not isinstance(node, Add):
            return node
        return replacement(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    convert.__annotations__['node'] = Add
    specific = changer.converter(partial(convert, replacement=Subtract))

    convert.__annotations__['node'] = CSTNode
    catch_all = changer.converter(partial(convert, replacement=Multiply))

    target_converter = specific if rejected_converter == 'specific' else catch_all

    @target_converter.filter
    def reject(node: Add) -> bool:  # noqa: ARG001
        return False

    function_id = specific.get_function_id()
    coordinates = list(changer.iterate_coordinates())
    add_coordinates = [coordinate for coordinate in coordinates if coordinate.class_name == 'Add']

    if rejected_converter == 'specific':
        non_add_coordinates = [coordinate for coordinate in coordinates if coordinate.class_name != 'Add']
        assert [coordinate.converter_id for coordinate in add_coordinates] == [f'{function_id}#1']
        expected_non_add_class_names = [
            type(node).__name__ for node in collect_nodes(changer.module) if not isinstance(node, Add)
        ]
        assert [coordinate.class_name for coordinate in non_add_coordinates] == expected_non_add_class_names
        assert {coordinate.converter_id for coordinate in non_add_coordinates} == {function_id}
        assert [changer.apply_coordinate(coordinate) for coordinate in add_coordinates] == ['1 * 2']
    else:
        assert [(coordinate.class_name, coordinate.converter_id) for coordinate in coordinates] == [('Add', function_id)]
        assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1 - 2']


def test_node_type_and_bound_filters_share_position_and_isolate_meta():
    """All filters for one node share a `SourcePosition` but receive isolated metadata copies; callbacks without metadata get `None`, and mutations do not leak between filters or into the original dictionaries."""
    changer = Changer('x = 1 + 2\n')
    contexts = {'first_node_type': [], 'second_node_type': [], 'first_bound': [], 'second_bound': [], 'plain_bound': []}
    shared_meta = {'shared': 0}
    second_node_type_meta = {'node_type': 2}
    second_bound_meta = {'filter': 2}

    @changer.converter
    def convert(node: Add) -> Subtract:
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.filter(meta=shared_meta)
    def node_type_filter(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts['first_node_type'].append(context)
        assert context.meta is not None
        context.meta['changed'] = True
        return True

    @changer.filter(meta=second_node_type_meta)
    def second_node_type_filter(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts['second_node_type'].append(context)
        return True

    @convert.filter(meta=shared_meta)
    def first_bound_filter(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts['first_bound'].append(context)
        return True

    @convert.filter(meta=second_bound_meta)
    def second_bound_filter(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts['second_bound'].append(context)
        return True

    @convert.filter
    def plain_bound_filter(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts['plain_bound'].append(context)
        return True

    assert [wrapper.function for wrapper in convert.filters] == [first_bound_filter, second_bound_filter, plain_bound_filter]
    assert [wrapper.function for wrapper in changer.filters_by_types[Add]] == [
        node_type_filter,
        second_node_type_filter,
    ]

    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 1
    assert all(len(recorded) == 1 for recorded in contexts.values())

    positions = [recorded[0].position for recorded in contexts.values()]
    assert all(position is positions[0] for position in positions)

    assert contexts['first_node_type'][0].meta == {'shared': 0, 'changed': True}
    assert contexts['second_node_type'][0].meta == {'node_type': 2}
    assert contexts['first_bound'][0].meta == {'shared': 0}
    assert contexts['first_node_type'][0].meta is not contexts['first_bound'][0].meta
    assert contexts['second_bound'][0].meta == {'filter': 2}
    assert contexts['plain_bound'][0].meta is None
    assert contexts['first_node_type'][0].meta is not shared_meta
    assert contexts['second_node_type'][0].meta is not second_node_type_meta
    assert contexts['first_bound'][0].meta is not shared_meta
    assert contexts['second_bound'][0].meta is not second_bound_meta

    assert shared_meta == {'shared': 0}
    assert second_node_type_meta == {'node_type': 2}
    assert second_bound_meta == {'filter': 2}

    position = positions[0]
    assert position.node_range == CodeRange(CodePosition(1, 5), CodePosition(1, 8))
    assert position.code_before == 'x = 1'
    assert position.code_after == '2\n'
    assert position.code_before + ' + ' + position.code_after == position.source


def test_converter_context_uses_original_position_and_isolated_meta():
    """
    A converter receives a copied meta and the original node position.

    Discovery and application use separate traversals; the converter's
    `SourcePosition` compares equal to the one captured by the filter.
    """
    changer = Changer('x = 1 + 2\n')
    converter_meta = {'converter': 1}
    filter_contexts = []
    converter_contexts = []

    @changer.converter(meta=converter_meta)
    def convert(node: Add, context: Context) -> Subtract:
        converter_contexts.append(context)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @changer.filter
    def capture(node: Add, context: Context) -> bool:  # noqa: ARG001
        filter_contexts.append(context)
        return True

    coordinate = next(changer.iterate_coordinates())

    assert changer.apply_coordinate(coordinate) == 'x = 1 - 2\n'
    assert len(filter_contexts) == 1
    assert filter_contexts[0].meta is None
    assert len(converter_contexts) == 1
    context = converter_contexts[0]
    position = context.position
    assert context.meta == {'converter': 1}
    assert context.meta is not converter_meta
    assert converter_meta == {'converter': 1}
    assert position.coordinate == Coordinate(None, 'Add', 1, 6, 1, 7)
    assert position.node_range == CodeRange(CodePosition(1, 5), CodePosition(1, 8))
    assert position.start_offset == 5
    assert position.end_offset == 8
    assert position.code_before == 'x = 1'
    assert position.code_after == '2\n'
    assert position.code_before + ' + ' + position.code_after == position.source
    assert position == filter_contexts[0].position


def test_bound_filter_meta_does_not_inherit_collector_or_converter_meta():
    """
    Converter-bound filter meta is independent of collector and converter meta.

    Collector and converter metadata merge into the converter context, while a
    bound filter receives only its own meta (or None), and none of the original
    dictionaries are mutated.
    """
    collector_meta = {'collector': 1}
    converter_meta = {'converter': 2}
    filter_meta = {'filter': 3}
    collector = Collector(meta=collector_meta)
    converter_contexts = []
    filter_contexts = {'plain': [], 'with_meta': []}

    @collector.converter(meta=converter_meta)
    def convert(node: Add, context: Context):
        converter_contexts.append(context)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @convert.filter
    def plain_filter(node: Add, context: Context) -> bool:  # noqa: ARG001
        filter_contexts['plain'].append(context)
        return True

    @convert.filter(meta=filter_meta)
    def meta_filter(node: Add, context: Context) -> bool:  # noqa: ARG001
        filter_contexts['with_meta'].append(context)
        return True

    assert [wrapper.function for wrapper in convert.filters] == [plain_filter, meta_filter]

    changer = Changer('1 + 2', collector=collector)
    assert not changer.filters_by_types
    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 1
    assert len(filter_contexts['plain']) == 1
    assert len(filter_contexts['with_meta']) == 1
    assert filter_contexts['plain'][0].position == filter_contexts['with_meta'][0].position
    assert convert.meta == {'collector': 1, 'converter': 2}
    assert filter_contexts['plain'][0].meta is None
    assert filter_contexts['with_meta'][0].meta == {'filter': 3}
    assert filter_contexts['with_meta'][0].meta is not filter_meta
    filter_contexts['with_meta'][0].meta['changed'] = True

    assert changer.apply_coordinate(coordinates[0]) == '1 - 2'
    assert len(converter_contexts) == 1
    assert converter_contexts[0].meta == {'collector': 1, 'converter': 2}
    assert converter_contexts[0].meta is not convert.meta
    converter_contexts[0].meta['changed'] = True

    assert collector_meta == {'collector': 1}
    assert converter_meta == {'converter': 2}
    assert filter_meta == {'filter': 3}
    assert convert.meta == {'collector': 1, 'converter': 2}


def test_collector_meta_is_merged_into_runtime_context_end_to_end():
    """
    Collector and decorator metadata reach runtime contexts after merging.

    Decorator keys override collector keys, converter and node-type filter
    contexts receive the merged dictionaries, and the original dictionaries stay
    unmodified.
    """
    collector_meta = {'a': 1, 'b': 2}
    converter_meta = {'b': 3, 'c': 4}
    filter_meta = {'b': 5}
    collector = Collector(meta=collector_meta)
    converter_contexts = []
    filter_contexts = []

    @collector.converter(meta=converter_meta)
    def convert(node: Add, context: Context):
        converter_contexts.append(context)
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @collector.filter(meta=filter_meta)
    def gate(node: Add, context: Context) -> bool:  # noqa: ARG001
        filter_contexts.append(context)
        return True

    changer = Changer('1 + 2', collector=collector)
    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 1
    assert len(filter_contexts) == 1
    assert convert.meta == {'a': 1, 'b': 3, 'c': 4}
    assert filter_contexts[0].meta == {'a': 1, 'b': 5}
    assert filter_contexts[0].meta is not filter_meta

    assert changer.apply_coordinate(coordinates[0]) == '1 - 2'
    assert len(converter_contexts) == 1
    assert converter_contexts[0].meta == {'a': 1, 'b': 3, 'c': 4}
    assert converter_contexts[0].meta is not convert.meta

    assert collector_meta == {'a': 1, 'b': 2}
    assert converter_meta == {'b': 3, 'c': 4}
    assert filter_meta == {'b': 5}


@pytest.mark.parametrize('scope', ['converter', 'node_type_filter', 'bound_filter'])
def test_empty_decorator_meta_reaches_context_as_empty_dict(scope):
    """Converter and filter callbacks receive a fresh empty dictionary, not `None`, when `meta={}` is supplied."""
    supplied_meta = {}
    received_meta = []
    changer = Changer('1 + 2')

    def convert_with_meta(node: Add, context: Context):
        received_meta.append(context.meta)
        return node

    def capture_filter(node: Add, context: Context) -> bool:  # noqa: ARG001
        received_meta.append(context.meta)
        return True

    def identity(node: Add):
        return node

    if scope == 'converter':
        changer.converter(meta=supplied_meta)(convert_with_meta)
        changer.apply_coordinate(next(changer.iterate_coordinates()))
    elif scope == 'node_type_filter':
        changer.converter(identity)
        changer.filter(meta=supplied_meta)(capture_filter)
        list(changer.iterate_coordinates())
    else:
        converter = changer.converter(identity)
        converter.filter(meta=supplied_meta)(capture_filter)
        list(changer.iterate_coordinates())

    assert received_meta == [{}]
    assert received_meta[0] is not supplied_meta


@pytest.mark.parametrize('registration_kind', ['converter', 'filter'])
@pytest.mark.parametrize(
    ('collector_meta', 'decorator_meta', 'expected_meta'),
    [
        pytest.param(None, None, None, id='no-meta'),
        pytest.param({}, None, None, id='empty-collector'),
        pytest.param({'a': 1}, None, {'a': 1}, id='collector-only'),
        pytest.param(None, {}, {}, id='empty-decorator'),
        pytest.param({}, {}, {}, id='empty-decorator-and-collector'),
        pytest.param({'a': 1}, {}, {'a': 1}, id='empty-decorator-with-collector'),
        pytest.param(None, {'b': 2}, {'b': 2}, id='decorator-only'),
        pytest.param({}, {'b': 2}, {'b': 2}, id='decorator-only-empty-collector'),
        pytest.param({'a': 1}, {'b': 2}, {'a': 1, 'b': 2}, id='decorator-adds-key'),
        pytest.param({'a': 1}, {'a': 2}, {'a': 2}, id='decorator-overrides-key'),
    ],
)
def test_decorator_meta_merges_with_collector_meta(registration_kind, collector_meta, decorator_meta, expected_meta):
    """Decorator meta is copied over collector meta, with decorator keys overriding; omission yields `None` or a collector copy, and `meta={}` leaves that copy unchanged."""
    collector = Collector(meta=collector_meta)
    original_collector_meta = collector_meta.copy() if collector_meta is not None else None
    original_decorator_meta = decorator_meta.copy() if decorator_meta is not None else None
    received_meta = []

    def convert_callback(node: Add, context: Context):
        received_meta.append(context.meta)
        return node

    def filter_callback(node: Add, context: Context) -> bool:  # noqa: ARG001
        received_meta.append(context.meta)
        return True

    def identity(node: Add):
        return node

    if registration_kind == 'converter':
        collector.converter(meta=decorator_meta)(convert_callback)
        changer = Changer('1 + 2', collector=collector)
        changer.apply_coordinate(next(changer.iterate_coordinates()))
    else:
        collector.converter(identity)
        collector.filter(meta=decorator_meta)(filter_callback)
        changer = Changer('1 + 2', collector=collector)
        list(changer.iterate_coordinates())

    assert received_meta == [expected_meta]
    assert collector_meta == original_collector_meta
    assert decorator_meta == original_decorator_meta
    if expected_meta is not None:
        assert received_meta[0] is not collector_meta
        assert received_meta[0] is not decorator_meta


def test_bound_filters_on_different_converters_share_position():
    """
    Bound filters on different converters for one node share the same SourcePosition object.

    Both converters still produce their own coordinate and replacement result.
    """
    changer = Changer('1 + 2')
    contexts = []

    @changer.converter
    def subtract(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    @subtract.filter
    def allow_subtract(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    @changer.converter
    def identity(node: Add):
        return node

    @identity.filter
    def allow_identity(node: Add, context: Context) -> bool:  # noqa: ARG001
        contexts.append(context)
        return True

    assert [wrapper.function for wrapper in subtract.filters] == [allow_subtract]
    assert [wrapper.function for wrapper in identity.filters] == [allow_identity]
    assert not changer.filters_by_types

    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 2
    assert len(contexts) == 2
    assert contexts[0].position is contexts[1].position
    assert [coordinate.converter_id for coordinate in coordinates] == [
        subtract.get_function_id(),
        identity.get_function_id(),
    ]
    assert [changer.apply_coordinate(coordinate) for coordinate in coordinates] == ['1 - 2', '1 + 2']


@pytest.mark.parametrize('filter_scope', ['node_type', 'bound_filter'])
def test_filter_meta_is_fresh_for_each_node(filter_scope):
    """
    Each filter invocation receives a fresh copy of its registered meta.

    Mutating context.meta for the first Add node does not affect the second Add
    or the original decorator dictionary.
    """
    changer = Changer('1 + 2 + 3')
    supplied_meta = {'count': 0}
    received_calls = []

    @changer.converter
    def convert(node: Add):
        return Subtract(whitespace_before=node.whitespace_before, whitespace_after=node.whitespace_after)

    def predicate(node: Add, context: Context) -> bool:
        received_calls.append((node, context))
        assert context.meta is not None
        context.meta['count'] += 1
        return True

    if filter_scope == 'node_type':
        changer.filter(meta=supplied_meta)(predicate)
    else:
        convert.filter(meta=supplied_meta)(predicate)

    list(changer.iterate_coordinates())

    assert len(received_calls) == 2
    first_node, first_context = received_calls[0]
    second_node, second_context = received_calls[1]
    assert first_node is not second_node
    assert isinstance(first_node, Add)
    assert isinstance(second_node, Add)
    assert first_context.meta is not second_context.meta
    assert first_context.meta == {'count': 1}
    assert second_context.meta == {'count': 1}
    assert supplied_meta == {'count': 0}


@pytest.mark.parametrize('registration_kind', ['converter', 'filter'])
@pytest.mark.parametrize('local_meta', [None, {}, {'local': 2}], ids=['omitted', 'empty', 'non-empty'])
def test_local_changer_meta_does_not_inherit_collector_meta(registration_kind, local_meta):
    """Collector meta applies only to registrations made through that Collector; a callback registered directly on the Changer sees only its own decorator meta."""
    collector = Collector(meta={'collector': 1})
    changer = Changer('1 + 2', collector=collector)
    received_meta = []

    def convert_callback(node: Add, context: Context):
        received_meta.append(context.meta)
        return node

    def filter_callback(node: Add, context: Context) -> bool:  # noqa: ARG001
        received_meta.append(context.meta)
        return True

    def identity(node: Add):
        return node

    if registration_kind == 'converter':
        changer.converter(meta=local_meta)(convert_callback)
        changer.apply_coordinate(next(changer.iterate_coordinates()))
    else:
        changer.converter(identity)
        changer.filter(meta=local_meta)(filter_callback)
        list(changer.iterate_coordinates())

    assert received_meta == [local_meta]
    if local_meta is not None:
        assert received_meta[0] is not local_meta

    assert collector._converters == []
    assert collector._filters == []


def test_combined_collector_preserves_operand_meta_without_inheriting_it():
    """
    A Changer built from a combined Collector preserves each operand's
    constructor metadata.

    Converters and filters from each collector see that metadata, while callbacks
    registered on the combined Collector see no inherited metadata.
    """
    collector_1 = Collector(meta={'a': 1})
    collector_2 = Collector(meta={'b': 2})
    seen_meta = {'filter_a': [], 'filter_b': [], 'filter_combined': [], 'converter_a': [], 'converter_b': [], 'converter_combined': []}

    @collector_1.converter
    def convert_a(node: Add, context: Context):
        seen_meta['converter_a'].append(context.meta)
        return node

    @collector_2.converter
    def convert_b(node: Add, context: Context):
        seen_meta['converter_b'].append(context.meta)
        return node

    @collector_1.filter
    def filter_a(node: Add, context: Context) -> bool:  # noqa: ARG001
        seen_meta['filter_a'].append(context.meta)
        return True

    @collector_2.filter
    def filter_b(node: Add, context: Context) -> bool:  # noqa: ARG001
        seen_meta['filter_b'].append(context.meta)
        return True

    combined = collector_1 + collector_2

    @combined.converter
    def convert_combined(node: Add, context: Context):
        seen_meta['converter_combined'].append(context.meta)
        return node

    @combined.filter
    def filter_combined(node: Add, context: Context) -> bool:  # noqa: ARG001
        seen_meta['filter_combined'].append(context.meta)
        return True

    changer = Changer('1 + 2', collector=combined)
    coordinates = list(changer.iterate_coordinates())

    assert len(coordinates) == 3
    applied_sources = [changer.apply_coordinate(coordinate) for coordinate in coordinates]
    assert applied_sources == ['1 + 2'] * 3

    assert seen_meta == {
        'filter_a': [{'a': 1}],
        'filter_b': [{'b': 2}],
        'filter_combined': [None],
        'converter_a': [{'a': 1}],
        'converter_b': [{'b': 2}],
        'converter_combined': [None],
    }


@pytest.mark.parametrize(
    ('source', 'expected_comment', 'expected_metacodes'),
    [
        pytest.param(
            'if True:  # key: action\n    value = 1\n',
            ' key: action',
            [ParsedComment(key='key', command='action', arguments=[])],
            id='first-line',
        ),
        pytest.param(
            '# header\nif True:  # key: action\n    value = 1\n',
            ' key: action',
            [ParsedComment(key='key', command='action', arguments=[])],
            id='later-first-line',
        ),
        pytest.param(
            'if True:\n    value = 1  # key: later\n',
            None,
            [],
            id='nested-line',
        ),
    ],
)
def test_multiline_node_comment_and_metacodes_use_first_line(source, expected_comment, expected_metacodes):
    """
    A multiline node's Context comment and metacodes come only from its first line.
    """
    changer = Changer(source)
    filter_contexts = []
    converter_contexts = []

    @changer.converter
    def convert(node: If, context: Context):
        converter_contexts.append(context)
        return node

    @changer.filter
    def capture(node: If, context: Context) -> bool:  # noqa: ARG001
        filter_contexts.append(context)
        return True

    coordinates = list(changer.iterate_coordinates())
    assert len(coordinates) == 1
    assert changer.apply_coordinate(coordinates[0]) == source

    assert len(filter_contexts) == 1
    assert len(converter_contexts) == 1
    contexts = filter_contexts + converter_contexts
    assert [context.comment for context in contexts] == [expected_comment] * 2
    assert all(context.get_metacodes('key') == expected_metacodes for context in contexts)
