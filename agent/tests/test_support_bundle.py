from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def test_support_bundle_creates_zip_and_includes_diagnostics(tmp_path: Path) -> None:
    sd = tmp_path / "state"
    (sd / "logs" / "runs").mkdir(parents=True)
    (sd / "queue").mkdir(parents=True)

    (sd / "state.json").write_text('{"last_effective_policy_hash":"abc123"}', encoding="utf-8")
    (sd / "health.json").write_text("{}", encoding="utf-8")
    (sd / "device_token.dpapi").write_text("SECRET", encoding="utf-8")
    (sd / "logs" / "agent.log").write_text("hello", encoding="utf-8")
    (sd / "logs" / "runs" / "r1.jsonl").write_text("{}\n", encoding="utf-8")
    (sd / "queue" / "q1.json").write_text("{}", encoding="utf-8")

    from baseliner_agent.support_bundle import create_support_bundle

    out = tmp_path / "bundle.zip"

    p = create_support_bundle(
        state_dir=sd,
        out_path=out,
        since_hours=0,
        max_run_logs=10,
        include_queue=True,
        include_config_redacted={"enroll_token": "***redacted***", "winget_path": None},
        winget_path_hint=None,
    )

    assert p.exists()

    with zipfile.ZipFile(p, "r") as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "policy/summary.json" in names
        assert "diagnostics/winget.json" in names
        assert "device_token.dpapi" not in names

        policy = json.loads(zf.read("policy/summary.json").decode("utf-8"))
        assert policy.get("last_effective_policy_hash") == "abc123"

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert "policy" in manifest
        assert "diagnostics" in manifest
