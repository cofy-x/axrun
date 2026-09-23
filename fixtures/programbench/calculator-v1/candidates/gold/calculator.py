#!/usr/bin/env python3
import operator
import sys


def main() -> int:
    if len(sys.argv) != 4:
        return 2
    operations = {"+": operator.add, "-": operator.sub, "*": operator.mul}
    operation = operations.get(sys.argv[2])
    if operation is None:
        return 2
    try:
        result = operation(int(sys.argv[1]), int(sys.argv[3]))
    except ValueError:
        return 2
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
