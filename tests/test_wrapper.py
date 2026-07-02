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
