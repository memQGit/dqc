"""Basic tests for memq_dqc main module."""

import pytest

from memq_dqc.main import main


def test_main_function_exists():
    """Test that the main function exists and is callable."""
    assert callable(main)


def test_main_function_output(capsys):
    """Test that the main function produces expected output."""
    main()
    captured = capsys.readouterr()
    assert "Welcome to memq_dqc!" in captured.out
    assert "main entry point" in captured.out


def test_main_function_no_exceptions():
    """Test that the main function runs without raising exceptions."""
    try:
        main()
    except Exception as e:
        pytest.fail(f"main() raised an exception: {e}")


@pytest.mark.parametrize("test_input,expected", [
    ("memq_dqc", True),
    ("entry point", True),
    ("application", True),
])
def test_main_output_contains_keywords(test_input, expected, capsys):
    """Parametrized test to check for specific keywords in output."""
    main()
    captured = capsys.readouterr()
    assert (test_input in captured.out) == expected