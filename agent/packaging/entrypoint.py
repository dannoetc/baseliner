"""PyInstaller entrypoint.

Keep this tiny and stable so packaging doesn't depend on `python -m`.
"""

from baseliner_agent.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
