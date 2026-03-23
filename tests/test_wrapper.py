from cstvis.wrapper import CallableWrapper


def test_repr():
    def function(a, b):
        ...

    assert repr(CallableWrapper(function)) == 'CallableWrapper(function)'
    assert repr(CallableWrapper(function, meta={'kek': 1234})) == "CallableWrapper(function, {'kek': 1234})"
