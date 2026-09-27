"""``python -m atlas_web`` — serve the Atlas-HQ web API."""

from __future__ import annotations

import sys

from .http import main

if __name__ == "__main__":
    sys.exit(main())
