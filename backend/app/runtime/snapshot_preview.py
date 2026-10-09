"""可信冻结快照预览：固定本机服务，同一 origin 切换宿主控制引用。"""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path


class SnapshotPreviewHandler(SimpleHTTPRequestHandler):
    """请求开始时读取程序控制的冻结版本，不执行产品脚本。"""

    def __init__(self, *args, reference: Path, **kwargs):
        """将本次请求固定到已冻结目录，引用更新不改变服务端口。"""
        self.reference = reference
        value = json.loads(reference.read_text())
        snapshot = Path(value["snapshot"])
        if not snapshot.is_absolute() or snapshot.is_symlink() or not snapshot.is_dir():
            raise ValueError("invalid_preview_snapshot")
        self.submission_id = value["submission_id"]
        super().__init__(*args, directory=str(snapshot), **kwargs)

    def list_directory(self, path):
        """不向用户暴露冻结产品文件清单，缺失入口按失败处理。"""
        self.send_error(404, "Directory listing disabled")
        return None

    def do_GET(self):
        """健康证据返回当前提交标识，其余请求只提供静态文件。"""
        if self.path == "/__repair_health":
            content = json.dumps({"submission_id": self.submission_id}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        super().do_GET()


def create_server(reference: Path, port: int) -> ThreadingHTTPServer:
    """仅监听宿主回环，快照引用由宿主原子更新，浏览器 origin 保持。"""
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(SnapshotPreviewHandler, reference=reference))
    server.request_queue_size = 128
    server.daemon_threads = True
    return server


def main() -> None:
    """可信独立服务入口，参数来自宿主控制程序而非模型命令。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    arguments = parser.parse_args()
    create_server(arguments.reference, arguments.port).serve_forever()


if __name__ == "__main__":
    main()
