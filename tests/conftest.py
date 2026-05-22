"""
Pytest configuration for gateway tests.
"""

import pytest


# Use function-scoped event loops for each test
pytestmark = pytest.mark.asyncio

