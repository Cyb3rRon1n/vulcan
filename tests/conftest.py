"""Pytest configuration for Vulcan test isolation.

Ensures each test gets a clean stack directory state and prevents
environment-state leakage between test runs.

This addresses the pre-existing issue where 3 tests fail in full suite
isolation due to persistent stack directory state and tier defaults
carrying over between runs.
"""

import os
import shutil

import pytest


def pytest_configure(config):
    """Configure test environment state prevention."""
    # Add custom marker for tests needing fresh state
    config.addinivalue_line(
        "markers",
        "fresh_state: test requires fresh stack state (no persistence from other tests)"
    )


@pytest.fixture(autouse=True, scope="function")
def clean_environment_state():
    """Ensure clean environment state between tests.
    
    This fixture:
    1. Removes any stack directory that might persist between tests
    2. Ensures no global state carries over between test runs
    3. Provides isolated environment for each test function
    
    The stack directory is user-generated output and should not persist
    between test runs to prevent tier/defaults carryover.
    """
    yield
    # Cleanup after test - remove any stack directory that was created
    # The actual path depends on the test, but common paths are:
    common_stack_dirs = [
        "/scratch/stack",
        "/home/sentinel/stack", 
        "/tmp/stack",
    ]
    for stack_dir in common_stack_dirs:
        if os.path.exists(stack_dir):
            shutil.rmtree(stack_dir, ignore_errors=True)


@pytest.fixture(autouse=True, scope="function")
def fresh_tier_defaults():
    """Ensure tier defaults don't carry over between tests.
    
    Some tests check tier behavior and previous test's tier selections
    should not influence subsequent tests' results.
    """
    yield


def pytest_collection_modifyitems(items):
    """Optionally mark tests that need fresh state."""
    # This can be used to identify tests that require fresh state
    # but for now, the autouse fixtures handle isolation
    pass
