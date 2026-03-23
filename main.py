#!/usr/bin/env python3
"""ViewTripWeb backend entry point.

The application is normally started via Reflex:

    reflex run          # development (hot reload)
    reflex run --env prod   # production

This file is kept for compatibility with tools that expect a main.py.
"""

import sys
import os

# Ensure project root is on the path so 'src.*' and 'api.*' imports resolve.
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call(["reflex", "run"] + sys.argv[1:]))
