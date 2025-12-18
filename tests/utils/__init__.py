from cstvis.utils.function_id import get_function_id


def test_getter_on_itself():
    assert get_function_id(get_function_id) == 'cstvis.utils.function_id:get_function_id:4'
