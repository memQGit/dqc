## Code Style

### Type Hints

This codebase uses [PEP 484](https://peps.python.org/pep-0484/) type hints. See example below:

```python
def greeting(name: str) -> str:
    return 'Hello ' + name
```

### Docstrings

This library uses [Google-style docstrings](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings). All modules, functions, and classes must have an appropriate
docstrings, though module-level docstrings for test files are not required. Note, since
we use type hints, type information should not be included in the docstrings. See example below:

```python
"""Example function with PEP 484 type annotations.

Args:
    param1: The first parameter.
    param2: The second parameter.

Returns:
    The return value. True for success, False otherwise.

"""
```
