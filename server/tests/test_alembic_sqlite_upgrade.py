from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import which


def test_alembic_sqlite_upgrade_head_smoke() -> None:
    """Smoke test: Alembic migrations must upgrade cleanly on SQLite.

    This catches regressions where migrations use Postgres-only constructs (e.g. JSONB)
    directly, which breaks SQLite compilation, and ensures the full migrations chain
    can run from an empty database.
    """
    server_dir = Path(__file__).resolve().parents[1]
    alembic_ini = server_dir / "alembic.ini"

    with tempfile.TemporaryDirectory(prefix="baseliner_alembic_smoke_") as td:
        db_path = Path(td) / "alembic_smoke.db"
        db_url = f"sqlite:///{db_path}"

        env = os.environ.copy()
        env["DATABASE_URL"] = db_url

        alembic_exe = which("alembic")
        if alembic_exe:
            cmd = [alembic_exe, "-c", str(alembic_ini), "upgrade", "head"]
        else:
            # Some environments don't expose an `alembic` console script on PATH.
            # Call the Alembic CLI entrypoint via Python instead.
            cmd = [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "from alembic.config import main as alembic_main; "
                    f"sys.exit(alembic_main(['-c','{alembic_ini}','upgrade','head']))"
                ),
            ]

        proc = subprocess.run(
            cmd,
            cwd=str(server_dir),
            env=env,
            capture_output=True,
            text=True,
        )

        if proc.returncode != 0:
            raise AssertionError(
                "Alembic upgrade head failed on SQLite\n"
                f"DATABASE_URL={db_url}\n"
                f"cmd={cmd}\n\n"
                f"stdout:\n{proc.stdout}\n\n"
                f"stderr:\n{proc.stderr}\n"
            )
