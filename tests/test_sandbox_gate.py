"""隔离启用证据缺失或失效时关闭门禁，不代替真实探针。"""

import hashlib
import json
from types import SimpleNamespace

from backend.app.runtime import sandbox_gate as gate


def test_profile_requires_current_proof_and_runtime(tmp_path, monkeypatch):
    """只认可完整当前证据，篡改证据或缺检查均关闭。"""
    profile = tmp_path / "profile.json"
    monkeypatch.setattr(gate, "PROFILE", profile)
    assert not gate.ready()
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"synthetic": true}')
    value = {"configuration_hash": gate.sandbox.configuration_hash(), "gate_hash": gate.gate_hash(),
             "checks": dict.fromkeys(gate.REQUIRED, True), "image_id": "fixture",
             "docker_identity": "fixture Docker", "evidence_hashes": {"evidence.json": hashlib.sha256(evidence.read_bytes()).hexdigest()}}
    monkeypatch.setattr(gate.sandbox, "image_identity", lambda: "fixture")
    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="fixture Docker"))
    profile.write_text(json.dumps(value))
    assert gate.ready()
    evidence.write_text("changed")
    assert not gate.ready()
    evidence.write_text('{"synthetic": true}')
    value["checks"]["timeout"] = False
    profile.write_text(json.dumps(value))
    assert not gate.ready()
    value["checks"]["timeout"] = True
    value["configuration_hash"] = "old"
    profile.write_text(json.dumps(value))
    assert not gate.ready()
