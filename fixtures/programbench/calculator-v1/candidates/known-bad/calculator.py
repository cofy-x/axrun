#!/usr/bin/env python3
import sys

if len(sys.argv) != 4 or sys.argv[2] != "+":
    raise SystemExit(2)
print(int(sys.argv[1]) + int(sys.argv[3]))
