"""验证实际 Worker 静态服务能接纳短暂调度暂停时的模块连接突发，不调用模型。"""

import os
import signal
import socket
import time

import httpx
import pytest

from backend.app.models import Step, StepRun, StepStatus, Task, TaskStatus
from backend.app.runtime import worker
from backend.app.runtime.tools import ToolRuntime


@pytest.mark.skipif(os.name == "nt", reason="连接队列回归使用 POSIX 暂停，Windows 需独立验证")
def test_worker_static_server_accepts_module_connection_burst(tmp_path, monkeypatch):
    # 直接运行实际启动入口；仅隔离数据库记录和阶段推进，不替换进程或 HTTP。
    tools = ToolRuntime(tmp_path)
    (tools.product / "index.html").write_text('<script type="module" src="main.js"></script>', encoding="utf-8")
    (tools.product / "main.js").write_text('export const ready = true;', encoding="utf-8")
    task = Task(task_name="static server burst", status=TaskStatus.running,
                cur_step=Step.start_product, workspace_path=str(tmp_path))
    run = StepRun(step=Step.start_product, status=StepStatus.running, attempt=1)
    next_steps = []

    def execute_real_tool(db, current_task, current_run, runtime, call):
        # 保留真实 ToolRuntime 子进程执行，避免只验证命令字符串。
        return runtime.execute(call)

    def ignore_trace(*args, **kwargs):
        # 该回归仅验证服务能力，不连接正式库或生成审计事件。
        return None

    def record_next_step(db, current_task, current_run, step):
        # 记录启动健康后应交给真实浏览器验证，不继续模型流程。
        next_steps.append(step)

    monkeypatch.setattr(worker, "execute_tool", execute_real_tool)
    monkeypatch.setattr(worker, "safe_record_trace", ignore_trace)
    monkeypatch.setattr(worker, "finish_step", record_next_step)
    clients = []
    paused_group = None
    try:
        worker.handle_start(None, task, run, tools)
        assert task.process_id and next_steps == [Step.verify_product]
        assert task.result_url == f"http://127.0.0.1:{task.port}"
        with httpx.Client(trust_env=False, timeout=2) as client:
            assert client.get(task.result_url).text == (tools.product / "index.html").read_text()
            module = client.get(task.result_url + "/main.js")
            assert module.status_code == 200 and module.text == 'export const ready = true;'

        # 暂停本测试独占进程组，模拟短暂调度延迟，让连接真正进入内核监听队列。
        group = os.getpgid(task.process_id)
        assert group == task.process_id
        os.killpg(group, signal.SIGSTOP)
        paused_group = group
        # 确认暂停信号已经生效，避免客户端先于停止状态建立连接而假通过。
        for _ in range(100):
            child, state = os.waitpid(task.process_id, os.WUNTRACED | os.WNOHANG)
            if child:
                assert os.WIFSTOPPED(state)
                break
            time.sleep(0.005)
        else:
            raise AssertionError("static_server_did_not_stop_for_queue_probe")
        for _ in range(10):
            connection = socket.socket()
            clients.append(connection)
            connection.settimeout(0.5)
            connection.connect(("127.0.0.1", task.port))

        # 恢复服务后确认静态模块继续可读，不能仅把建连成功当作服务健康。
        os.killpg(group, signal.SIGCONT)
        paused_group = None
        for connection in clients:
            connection.close()
        clients.clear()
        with httpx.Client(trust_env=False, timeout=2) as client:
            assert client.get(task.result_url + "/main.js").text == 'export const ready = true;'
    finally:
        # 任何断言失败都先恢复本测试进程，再关闭连接和后台服务。
        if paused_group is not None:
            os.killpg(paused_group, signal.SIGCONT)
        for connection in clients:
            connection.close()
        for pid, process in list(tools._processes.items()):
            if process.poll() is None:
                tools._exec("stop", process_id=pid)
