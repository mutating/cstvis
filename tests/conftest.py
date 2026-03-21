from typing import List

import pytest


@pytest.fixture
def file(strings: List[str]) -> str:
    return '\n'.join(strings)


@pytest.fixture(params=[True, False])
def with_context(request) -> bool:
    return request.param
