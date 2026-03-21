from cstvis.wrapper import CallableWrapper


def test_repr():
    def function(a, b):
        ...

    assert repr(CallableWrapper(function)) == 'CallableWrapper(function)'
