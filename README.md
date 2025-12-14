# cstvis

A large number of source code tools (linters, formatters, and others) work with CST, a special representation of the source code that already has a tree shape (like AST), but still contains "extra" nodes such as spaces or comments. This library is a wrapper around such a tree, designed for convenient and iterative work with nodes: traversal and replacement.
