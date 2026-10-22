#!/usr/bin/env python3
"""Read-only localization checks. Run with --help; no AI or Unity runtime needed."""
import sys
sys.dont_write_bytecode = True
from localization.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
