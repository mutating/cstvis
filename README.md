<details>
  <summary>ⓘ</summary>

[![Downloads](https://static.pepy.tech/badge/cstvis/month)](https://pepy.tech/project/cstvis)
[![Downloads](https://static.pepy.tech/badge/cstvis)](https://pepy.tech/project/cstvis)
[![Coverage Status](https://coveralls.io/repos/github/mutating/cstvis/badge.svg?branch=main)](https://coveralls.io/github/mutating/cstvis?branch=main)
[![Lines of code](https://sloc.xyz/github/mutating/cstvis/?category=code)](https://github.com/boyter/scc/)
[![Hits-of-Code](https://hitsofcode.com/github/mutating/cstvis?branch=main&label=Hits-of-Code&exclude=docs/)](https://hitsofcode.com/github/mutating/cstvis/view?branch=main)
[![Test-Package](https://github.com/mutating/cstvis/actions/workflows/tests_and_coverage.yml/badge.svg)](https://github.com/mutating/cstvis/actions/workflows/tests_and_coverage.yml)
[![Python versions](https://img.shields.io/pypi/pyversions/cstvis.svg)](https://pypi.python.org/pypi/cstvis)
[![PyPI version](https://badge.fury.io/py/cstvis.svg)](https://badge.fury.io/py/cstvis)
[![Checked with mypy](http://www.mypy-lang.org/static/mypy_badge.svg)](http://mypy-lang.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mutating/cstvis)

</details>

![logo](https://raw.githubusercontent.com/mutating/cstvis/develop/docs/assets/logo_1.svg)

Many source code tools (linters, formatters, and others) work with [CST](https://en.wikipedia.org/wiki/Parse_tree), a tree-structured representation of source code (like [AST](https://en.wikipedia.org/wiki/Abstract_syntax_tree), but it also retains nodes such as whitespace and comments). This library is a wrapper around such trees, designed for convenient iterative traversal and replacement of nodes.

It is built on top of [`libcst`](https://pypi.org/project/libcst/).


## Table of Contents

- [**Installation**](#installation)
- [**Changing nodes**](#changing-nodes)
- [**Filters**](#filters)
- [**Context**](#context)


## Installation

You can install [`cstvis`](https://pypi.org/project/cstvis) with `pip`:

```bash
pip install cstvis
```

You can also use [`instld`](https://github.com/pomponchik/instld) to quickly try this package and others without installing them.


## Changing nodes

The basic workflow is very simple:

- Create an object of the `Changer` class.
- Register converter functions with the `@<changer object>.converter` decorator. Each function converts one `CST` node type into another. It takes a node object as its first argument.
- If needed, register [filters](#filters) to prevent changes to certain nodes.
- Iterate over individual changes and apply them as needed.

Let me show you a simple example:

```python
from libcst import Subtract, Add
from cstvis import Changer
from pathlib import Path

# Content of the file:
# a = 4 + 5
# b = 15 - a
# c = b + a # kek
changer = Changer(Path('tests/some_code/simple_sum.py').read_text())

@changer.converter
def change_add(node: Add):
    return Subtract(
        whitespace_before=node.whitespace_before,
        whitespace_after=node.whitespace_after,
    )

for x in changer.iterate_coordinates():
    print(x)
    print(changer.apply_coordinate(x))

#> Coordinate(file=None, class_name='Add', start_line=1, start_column=6, end_line=1, end_column=7, converter_id='__main__:change_add:11')
#> a = 4 - 5
#> b = 15 - a
#> c = b + a # kek
#>
#> Coordinate(file=None, class_name='Add', start_line=3, start_column=6, end_line=3, end_column=7, converter_id='__main__:change_add:11')
#> a = 4 + 5
#> b = 15 - a
#> c = b - a # kek
```

As you can see in the example, the converter function takes an argument with a type hint. You don’t need to write type-checking if statements because the system determines which node types to convert based on this hint. You can omit the annotation entirely, specify [`Any`](https://docs.python.org/3/library/typing.html#the-any-type), or specify [`libcst.CSTNode`](https://libcst.readthedocs.io/en/latest/nodes.html#libcst.CSTNode), in which case the converter will be applied to all nodes. If you specify a more specific type, such as [`libcst.Add`](https://libcst.readthedocs.io/en/latest/nodes.html#libcst.Add), the converter will be applied only to those nodes. You can also specify multiple nodes using the `|` [syntax](https://docs.python.org/3/library/stdtypes.html#types-union) or [`Union`](https://docs.python.org/3/library/typing.html#typing.Union). Finally, several shortcuts are supported: `str` -> [`libcst.SimpleString`](https://libcst.readthedocs.io/en/latest/nodes.html#libcst.SimpleString), `int` -> [`libcst.Integer`](https://libcst.readthedocs.io/en/latest/nodes.html#libcst.Integer), and `float` -> [`libcst.Float`](https://libcst.readthedocs.io/en/latest/nodes.html#libcst.Float).

The key part of this example is the last two lines, where we iterate over the coordinates. What does that mean? The fact is that any code change made by this library happens in two stages: identify the coordinates of the change and then apply it. This separation makes it possible to distribute the work across multiple threads or even multiple machines. However, this design also has limitations. If you apply one coordinate change, the resulting code will differ from the original and the remaining coordinates will no longer be valid. You can only apply one change at a time.


## Filters

A filter is a special function, registered with the `@<changer object>.filter` decorator. It decides whether a specific `CST` node should be changed, and returns `True` if yes, or `False` if no. To determine the nodes to which the filter is applied, a type hint is used, which works in the same way as it does for converters.

Let's look at another example (part of the code is omitted):

```python
count_adds = 0

@changer.filter
def only_first(node: Add) -> bool:
    global count_adds
    
    count_adds += 1
    
    return True if count_adds <= 1 else False

for x in changer.iterate_coordinates():
    print(x)
    print(changer.apply_coordinate(x))

#> Coordinate(file=None, class_name='Add', start_line=1, start_column=6, end_line=1, end_column=7, converter_id='__main__:change_add:11')
#> a = 4 - 5
#> b = 15 - a
#> c = b + a # kek
```

You see? Now the iteration yields only the first possible change, the rest are filtered out automatically because the filter returns `False` for them.


## Context

By default, each converter or filter takes a single argument: the node to which it is applied. However, you can also specify a second argument: the context. The system analyzes the signatures of your functions, detects that they expect a second argument, and passes it to them:

```python
from cstvis import Context

@changer.converter
def change_add(node: Add, context: Context):  # <- The function takes a second argument.
    return Subtract(
        whitespace_before=node.whitespace_before,
        whitespace_after=node.whitespace_after,
    )
```

The context object has two necessary fields and one useful method:

- `coordinate` with fields `start_line: int`, `start_column: int`, `end_line: int`, `end_column: int` and some others. This identifies the current location in the code.
- `comment` - the comment on the first line of the node, if there is one, without the leading `#`, or `None` if there is no comment.
- `get_metacodes(key: Union[str, List[str]]) -> List[ParsedComment]` - a method that returns a list of parsed comments in [metacode format](https://github.com/mutating/metacode) associated with this line of code.
