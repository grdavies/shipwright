#!/usr/bin/env python3
"""Synthetic script with executed and un-executed lines for coverage fixtures."""

def executed_fn() -> int:
    return 1


def unexecuted_fn() -> int:
    return 2


if __name__ == "__main__":
    print(executed_fn())
