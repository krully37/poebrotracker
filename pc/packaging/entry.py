"""The .exe's entry point. Double-clicking it (no arguments) starts the app, like `stashdisplay run`."""

import sys

from stashdisplay.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["run"]))
