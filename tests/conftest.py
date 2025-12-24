import sys
from pathlib import Path

# Prioritize the in-repo server package during tests.
_SERVER_SRC = Path(__file__).resolve().parents[1] / "server" / "src"
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))
