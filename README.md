<details>
  <summary>ⓘ</summary>

[![Downloads](https://static.pepy.tech/badge/cstvis/month)](https://pepy.tech/project/cstvis)
[![Downloads](https://static.pepy.tech/badge/cstvis)](https://pepy.tech/project/cstvis)
[![Coverage Status](https://coveralls.io/repos/github/pomponchik/cstvis/badge.svg?branch=main)](https://coveralls.io/github/pomponchik/cstvis?branch=main)
[![Lines of code](https://sloc.xyz/github/pomponchik/cstvis/?category=code)](https://github.com/boyter/scc/)
[![Hits-of-Code](https://hitsofcode.com/github/pomponchik/cstvis?branch=main&label=Hits-of-Code&exclude=docs/)](https://hitsofcode.com/github/pomponchik/cstvis/view?branch=main)
[![Test-Package](https://github.com/pomponchik/cstvis/actions/workflows/tests_and_coverage.yml/badge.svg)](https://github.com/pomponchik/cstvis/actions/workflows/tests_and_coverage.yml)
[![Python versions](https://img.shields.io/pypi/pyversions/cstvis.svg)](https://pypi.python.org/pypi/cstvis)
[![PyPI version](https://badge.fury.io/py/cstvis.svg)](https://badge.fury.io/py/cstvis)
[![Checked with mypy](http://www.mypy-lang.org/static/mypy_badge.svg)](http://mypy-lang.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/pomponchik/cstvis)

</details>

![logo](docs/assets/logo_1.svg)

A large number of source code tools (linters, formatters, and others) work with [CST](https://en.wikipedia.org/wiki/Parse_tree), a special representation of the source code that already has a tree shape (like [AST](https://en.wikipedia.org/wiki/Abstract_syntax_tree)), but still contains "extra" nodes such as spaces or comments. This library is a wrapper around such a tree, designed for convenient and iterative work with nodes: traversal and replacement.


## Table of contents

- [**Installation**](#installation)
- [**Usage**](#usage)


## Installation

Install it:

```bash
pip install cstvis
```

You can also quickly try out this and other packages without having to install using [instld](https://github.com/pomponchik/instld).


## Usage

This library is a wrapper around the [`libcst`](https://pypi.org/project/libcst/) library. 

The flow of work is very simple:

- Create an object of the `Changer` class.
- Register converter functions that will convert some `CST` nodes to others, using the decorator. Each such function takes a node object as the first argument, and it must be accompanied by a type annotation. It is based on the annotation that the system will understand which nodes it needs to be applied to and which ones it does not.
- If necessary, also register filters, which are special functions that can prevent the system from changing certain nodes.
- Iterate over atomic changes and apply them if necessary.

Let me show you a simple example:

```python
from libcst import Subtract, Add
from cstvis import Changer, Context
from pathlib import Path

# Content of the file:
# a = 4 + 5
# b = 15 - a
# c = b + a # kek
changer = Changer(Path('tests/some_code/simple_sum.py').read_text())

@changer.converter
def change_add(node: Add, context: Context):
    return Subtract(
        whitespace_before=node.whitespace_before,
        whitespace_after=node.whitespace_after,
    )

for x in changer.iterate_coordinates():
    print(x)
    print(changer.apply_coordinate(x))

#> Coordinate(file=None, class_name='Add', start_line=1, start_column=6, end_line=1, end_column=7)
#> a = 4 - 5
#> b = 15 - a
#> c = b + a # kek
#> 
#> Coordinate(file=None, class_name='Add', start_line=3, start_column=6, end_line=3, end_column=7)
#> a = 4 + 5
#> b = 15 - a
#> c = b - a # kek
```

The key part of this example is the last two lines where the coordinates are iterated. What does it mean? The fact is that any change to the code that this library makes occurs in 2 stages: outline the coordinates of the change and make the change. Due to this separation, it becomes possible, for example, to divide this work between several threads or even several computers. However, this scheme also limits us. If you apply one coordinate change, the resulting code will differ from the original one and subsequent coordinates will no longer be possible to apply. You can only apply one change at a time.

A filter is a special function with the same signature as a converter, which we mark with the `@filter` decorator. This should decide whether to change a specific `CST` node or not, and return `True` if yes, or `False` if no. The filter is applied to all nodes if the node parameter does not have a type annotation, or if [Any](https://docs.python.org/3/library/typing.html#typing.Any) / [CSTNode](https://libcst.readthedocs.io/en/latest/nodes.html#libcst.CSTNode) annotation is used. If you specify a specific type of node in the annotation, the filter will be applied only to them. Any other annotations are not allowed.

Let's look at another example (part of the code is omitted):

```python
count_adds = 0

@changer.filter
def only_first(node: Add, context: Context) -> bool:
    global count_adds
    
    count_adds += 1
    
    return True if count_adds <= 1 else False

for x in changer.iterate_coordinates():
    print(x)
    print(changer.apply_coordinate(x))

#> Coordinate(file=None, class_name='Add', start_line=1, start_column=6, end_line=1, end_column=7)
#> a = 4 - 5
#> b = 15 - a
#> c = b + a # kek
```

You see? Now, during the iteration, we got only the first version of possible changes, the rest are automatically filtered out because the filter function told us to do so.

So, now it's roughly clear how to use it. But what kind of `context` parameter do we see in converters and filters? It has 2 fields and 1 interesting method:

- `coordinate` with fields `start_line: int`, `start_column: int`, `end_line: int`, `end_column: int` and some others. This identifies where we are at in the code.
- `comment` - a comment line, if there is such a comment in the first line of this node, without a `#` at the beginning, or `None` if there is no comment.
- `get_metacodes(key: Union[str, List[str]]) -> List[ParsedComment]` - a method that returns a list of parsed comments in [metacode format](https://github.com/pomponchik/metacode) related to this line of code.
