"""容器可信控制：同回环静态服务、固定命令和可恢复输出，不接受任意 shell。"""

import json
import subprocess
import sys
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def resource_events() -> dict:
    """读取内核 cgroup 计数，区分资源耗尽与普通产品测试失败。"""
    events = {}
    for name in ("memory.events", "pids.events"):
        path = Path("/sys/fs/cgroup") / name
        if path.exists():
            events[name] = dict(line.split() for line in path.read_text().splitlines())
    return events


def serve() -> None:
    """程序在私有回环启动可信静态服务，生成脚本不负责服务托管。"""
    server = ThreadingHTTPServer(("127.0.0.1", 8080), SimpleHTTPRequestHandler)
    server.request_queue_size = 128
    server.serve_forever()


def run(command_id: str, kind: str, arguments: list[str]) -> None:
    """执行固定入口并有界收集输出，未写宿主结果时不允许推测完成。"""
    if kind == "node":
        command = ["node", "--test", *arguments]
    elif kind == "browser" and not arguments:
        command = ["python", "verify_product.py", "http://127.0.0.1:8080"]
    else:
        raise ValueError("unsupported_execution_kind")
    before = resource_events()
    # 参数来自宿主固定测试清单，无 shell；所有后代仍受容器限制。
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        result = subprocess.run(command, stdout=stdout, stderr=stderr)
        stdout.seek(0); stderr.seek(0)
        out, err = stdout.read(102401), stderr.read(102401)
    value = {"command_id": command_id, "command": command, "exit_code": result.returncode,
             "stdout": out[:102400].decode(errors="replace"), "stderr": err[:102400].decode(errors="replace"),
             "truncated": len(out) > 102400 or len(err) > 102400}
    value["resource_events_before"] = before
    value["resource_events_after"] = resource_events()
    print(json.dumps(value))


def main() -> None:
    """主进程托管服务，exec 控制只接受程序生成的动作。"""
    if len(sys.argv) == 1:
        serve()
    elif sys.argv[1] == "run":
        run(sys.argv[2], sys.argv[3], sys.argv[4:])
    elif sys.argv[1] == "health":
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8080", timeout=2) as response:
            print(json.dumps({"status": response.status}))
    else:
        raise ValueError("unsupported_controller_action")


if __name__ == "__main__":
    main()
