from typing import Any, Callable


def get_function_id(function: Callable[..., Any]) -> str:
    return f'{function.__module__}:{function.__name__}:{function.__code__.co_firstlineno}'
