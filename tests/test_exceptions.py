import pytest
from full_match import match

from cstvis import Converter, ConverterWrappingError


def test_converter_wrapping_error_is_catchable_as_type_error():
    """
    Wrapping an existing Converter raises `ConverterWrappingError` with the
    documented message, and the error is catchable as `TypeError`.
    """
    def function(node):
        return node

    converter = Converter(function)

    with pytest.raises(
        ConverterWrappingError,
        match=match('A converter cannot be wrapped in another converter.'),
    ) as error:
        Converter(converter)

    assert isinstance(error.value, TypeError)
