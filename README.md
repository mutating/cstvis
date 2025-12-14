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

![logo](https://raw.githubusercontent.com/pomponchik/cstvis/develop/docs/assets/logo_1.svg)

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

This library is a wrapper around the [`libcst`](https://pypi.org/project/libcst/) library. Let's start the demonstration with the import:

```python
from cstvis import Changer, Coordinate
```

The flow of work is very simple:

- Create an object of the `Changer` class.
- Register converter functions that will convert some `CST` nodes to others. Each such function takes a node object as the first argument, and it must be accompanied by a type annotation. It is based on the annotation that the system will understand which nodes it needs to be applied to and which ones it does not.
