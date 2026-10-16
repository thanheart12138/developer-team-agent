"""可信预览读取同一冻结字节并保持 origin 的回环验证。"""

import json
import threading

import httpx

from backend.app.runtime.container_execution import freeze_product
from backend.app.runtime.snapshot_preview import create_server


def test_static_preview_switches_snapshot_without_changing_origin(tmp_path):
    """程序更新冻结引用后，同地址提供新版本，绝不执行生成 Python。"""
    product = tmp_path / "product"
    product.mkdir()
    (product / "index.html").write_text("first version")
    (product / "generated.py").write_text("raise RuntimeError('must never run')")
    first = tmp_path / "first"
    freeze_product(product, first)
    (product / "index.html").write_text("second version")
    second = tmp_path / "second"
    freeze_product(product, second)
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps({"snapshot": str(first), "submission_id": "first"}))
    server = create_server(reference, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with httpx.Client(trust_env=False) as client:
            assert client.get(origin).text == "first version"
            assert client.get(origin + "/__repair_health").json() == {"submission_id": "first"}
            assert client.get(origin + "/generated.py").text.startswith("raise RuntimeError")
            pending = reference.with_suffix(".pending")
            pending.write_text(json.dumps({"snapshot": str(second), "submission_id": "second"}))
            pending.replace(reference)
            assert client.get(origin).text == "second version"
            assert client.get(origin + "/__repair_health").json() == {"submission_id": "second"}
            assert client.get(origin + "/../../reference.json").status_code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
