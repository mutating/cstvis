from typing import List

import pytest


@pytest.fixture
def file(strings: List[str]) -> str:
    return '\n'.join(strings)
