from __future__ import annotations

import sys


def main(argv: list[str]) -> int:
    shout = len(argv) == 2 and argv[0] == "--shout"
    if len(argv) == 1:
        name = argv[0]
    elif shout:
        name = argv[1]
    else:
        print("usage: greeter.py [--shout] NAME", file=sys.stderr)
        return 2
    if not name:
        print("name must not be empty", file=sys.stderr)
        return 2
    greeting = f"Hello, {name}!"
    print(greeting.upper() if shout else greeting)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
