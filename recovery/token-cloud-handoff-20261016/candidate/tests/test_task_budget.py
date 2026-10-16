"""只用标准库、临时文件和合成用量验证持久预算，不访问网络或数据库。"""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch

from backend.app.runtime import task_budget as budget


class TaskBudgetTests(TestCase):
    """覆盖新任务启用、恢复、逐 HTTP 结算、并发和保守停止。"""

    def setUp(self):
        """每个离线用例使用独立空目录，避免触碰正式任务与持久实验。"""
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "task"

    def initialize(self, **kwargs):
        """用小额合成配置建立可检查账本。"""
        return budget.initialize(self.root, **({"total_tokens": 1000, "http_limit": 3,
                                               "max_output_tokens": 100} | kwargs))

    def reserve(self, **kwargs):
        """生成一次无真实网络发送的合成请求预留。"""
        return budget.reserve(self.root, **({"request_id": "logical-1", "provider": "deepseek",
                                             "input_estimate": 200} | kwargs))

    def contents(self):
        """记录所有普通文件字节，验证拒绝路径和旧任务没有被改写。"""
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def test_opt_in_defaults_and_new_empty_root(self):
        """默认上限可配置，初始化只发生一次且启用后状态可恢复。"""
        state = budget.initialize(self.root)
        self.assertEqual(state["schema"], budget.SCHEMA)
        self.assertEqual(state["limits"], {"total_tokens": 1_000_000, "http_limit": 100,
                                         "max_output_tokens": 8192})
        self.assertEqual(state, budget.load(self.root))
        before = self.contents()
        with self.assertRaisesRegex(budget.TaskBudgetError, "new_empty_task_required"):
            budget.initialize(self.root)
        self.assertEqual(before, self.contents())

    def test_existing_empty_directory_is_accepted(self):
        """调用方预先创建的空任务目录可以显式启用。"""
        self.root.mkdir()
        self.initialize()
        self.assertEqual(budget.report(self.root)["status"], "ready")

    def test_legacy_task_unchanged_and_cannot_initialize(self):
        """未启用旧任务读取与发送路径返回 None，不能通过初始化改写旧现场。"""
        self.root.mkdir()
        (self.root / "old-task.txt").write_text("原任务", encoding="utf-8")
        before = self.contents()
        self.assertIsNone(budget.load(self.root))
        self.assertIsNone(self.reserve())
        self.assertIsNone(budget.report(self.root))
        self.assertIsNone(budget.finish(self.root, None, status="responded"))
        with self.assertRaisesRegex(budget.TaskBudgetError, "new_empty_task_required"):
            self.initialize()
        self.assertEqual(before, self.contents())

    def test_missing_root_is_not_silently_legacy(self):
        """恢复时整个任务目录缺失必须停止，不自动新建空现场。"""
        with self.assertRaisesRegex(budget.TaskBudgetError, "root_missing"):
            budget.load(self.root)
        self.assertFalse(self.root.exists())

    def test_invalid_limits_rejected_before_any_files(self):
        """负数、布尔、非整数及超出总额的输出上限均不能初始化。"""
        for kwargs in ({"total_tokens": 0}, {"http_limit": -1}, {"http_limit": True},
                       {"total_tokens": "1000"}, {"max_output_tokens": 1001},
                       {"max_output_tokens": 0}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(budget.TaskBudgetError, "limits_invalid"):
                    self.initialize(**kwargs)
                self.assertFalse(self.root.exists())

    def test_atomic_pre_send_counter_and_unknown_restart(self):
        """返回许可前计数和预留已持久化，进程重启不能再发送第二次请求。"""
        self.initialize()
        attempt = self.reserve()
        self.assertEqual(attempt["attempt"], 1)
        self.assertEqual(attempt["max_output_tokens"], 100)
        state = budget.load(self.root)
        self.assertEqual(state["http_attempts"], 1)
        self.assertEqual(state["attempts"][0], attempt)
        self.assertEqual(budget.report(self.root)["reserved_tokens"], 300)
        with self.assertRaisesRegex(budget.TaskBudgetError, "usage_unresolved"):
            self.reserve(request_id="second")
        self.assertEqual(budget.load(self.root)["http_attempts"], 1)

    def test_actual_usage_includes_thinking_once_and_cache_is_not_deducted(self):
        """供应商 total 已包括输出中的思考，缓存输入也完整计入 Token。"""
        self.initialize()
        attempt = self.reserve()
        state = budget.finish(self.root, attempt, status="responded", usage={
            "prompt_tokens": 210, "completion_tokens": 80, "total_tokens": 290,
            "completion_tokens_details": {"reasoning_tokens": 60},
            "prompt_cache_hit_tokens": 200, "arbitrary_private_field": "never store"})
        self.assertEqual(state["known_tokens"], 290)
        self.assertEqual(state["attempts"][0]["usage_source"], "provider_total")
        self.assertNotIn("never store", (self.root / budget.STATE_PATH).read_text())
        self.assertEqual(budget.report(self.root)["reserved_tokens"], 0)
        self.assertFalse(budget.report(self.root)["exact_token_cap_guaranteed"])

    def test_component_sum_and_same_logical_request_retry_count_separately(self):
        """缺 total 时可由完整输入输出组成结算，每次重试仍增加真实 HTTP 预留。"""
        self.initialize()
        first = self.reserve()
        state = budget.finish(self.root, first, status="protocol_failed",
                              usage={"prompt_tokens": 100, "completion_tokens": 30})
        self.assertEqual(state["known_tokens"], 130)
        self.assertEqual(state["attempts"][0]["usage_source"], "prompt_plus_completion")
        second = self.reserve()
        self.assertEqual(second["attempt"], 2)
        self.assertEqual(second["request_id"], first["request_id"])
        budget.finish(self.root, second, status="responded", usage={"total_tokens": 20})
        self.assertEqual(budget.load(self.root)["known_tokens"], 150)

    def test_unknown_or_malformed_usage_never_frees_reservation(self):
        """超时、空用量、非法类型和矛盾统计全部保守阻断，不推测为零费用。"""
        cases = [None, {}, {"prompt_tokens": 5}, {"total_tokens": -1},
                 {"total_tokens": True}, {"total_tokens": "5"},
                 {"total_tokens": 3, "prompt_tokens": 4},
                 {"total_tokens": 9, "prompt_tokens": 5, "completion_tokens": 5}]
        for index, usage in enumerate(cases):
            with self.subTest(usage=usage):
                root = self.root / str(index)
                budget.initialize(root, total_tokens=1000, max_output_tokens=100)
                attempt = budget.reserve(root, request_id="one", provider="kimi", input_estimate=200)
                budget.finish(root, attempt, status="failed", usage=usage)
                report = budget.report(root)
                self.assertEqual(report["known_tokens"], 0)
                self.assertEqual(report["reserved_tokens"], 300)
                self.assertEqual(report["stop_reason"], "usage_unresolved")
                with self.assertRaisesRegex(budget.TaskBudgetError, "usage_unresolved"):
                    budget.reserve(root, request_id="retry", provider="kimi", input_estimate=200)

    def test_unknown_attempt_can_be_reconciled_with_later_known_usage(self):
        """后续取得真实用量可补结算原请求，HTTP 次数不减、不另造请求。"""
        self.initialize()
        attempt = self.reserve()
        budget.finish(self.root, attempt, status="failed")
        state = budget.finish(self.root, attempt, status="failed", usage={"total_tokens": 20})
        self.assertEqual((state["http_attempts"], state["known_tokens"]), (1, 20))
        self.assertEqual(self.reserve()["attempt"], 2)

    def test_finish_idempotent_and_cannot_overwrite_known_usage(self):
        """重复收到相同结果不重复收费，也不能把已知成本改小或改为未知。"""
        self.initialize()
        attempt = self.reserve()
        budget.finish(self.root, attempt, status="responded", usage={"total_tokens": 20})
        before = self.contents()
        budget.finish(self.root, attempt, status="responded", usage={"total_tokens": 20})
        self.assertEqual(before, self.contents())
        for usage in (None, {"total_tokens": 1}, {"total_tokens": 50}):
            with self.assertRaisesRegex(budget.TaskBudgetError, "already_finalized"):
                budget.finish(self.root, attempt, status="responded", usage=usage)
        self.assertEqual(before, self.contents())

    def test_http_limit_persists_after_zero_token_attempts(self):
        """明确零 Token 仍消耗 HTTP 次数，达到上限后只保存拒绝证据而不增加计数。"""
        self.initialize(http_limit=2)
        for _ in range(2):
            budget.finish(self.root, self.reserve(), status="failed", usage={"total_tokens": 0})
        before = self.contents()
        with self.assertRaisesRegex(budget.TaskBudgetError, "http_exhausted") as caught:
            self.reserve()
        self.assertEqual(before, {key: value for key, value in self.contents().items()
                                  if key != budget.REJECTIONS_PATH})
        self.assertEqual(caught.exception.diagnostics["reason"], "http_exhausted")
        self.assertFalse(caught.exception.diagnostics["request_sent"])
        self.assertEqual(budget.report(self.root)["stop_reason"], "http_exhausted")

    def test_input_estimate_and_output_reserve_respect_remaining_budget(self):
        """已知实际成本加本轮输入估算与输出上限超过余额时，发前拒绝。"""
        self.initialize()
        budget.finish(self.root, self.reserve(), status="responded", usage={"total_tokens": 800})
        with self.assertRaisesRegex(budget.TaskBudgetError, "tokens_exhausted"):
            self.reserve(input_estimate=101)
        attempt = self.reserve(input_estimate=100)
        self.assertEqual(attempt["reserved_tokens"], 200)

    def test_rejected_reservation_preserves_exact_diagnostics_and_ledger(self):
        """复现已知成本未耗尽的提前拒绝，保存精确门槛且不伪造第十一次 HTTP。"""
        self.initialize(total_tokens=1_000_000, http_limit=40, max_output_tokens=65_536)
        for index in range(10):
            attempt = self.reserve(request_id=f"completed-{index}", input_estimate=100)
            budget.finish(self.root, attempt, status="responded",
                          usage={"total_tokens": 54_777 if index < 9 else 54_780})
        before = self.contents()
        with self.assertRaisesRegex(budget.TaskBudgetError, "tokens_exhausted") as caught:
            self.reserve(input_estimate=386_692)
        details = caught.exception.diagnostics
        self.assertEqual(details["reason"], "admission_reservation_exceeded")
        self.assertEqual(details["input_estimate"], 386_692)
        self.assertEqual(details["max_output_tokens"], 65_536)
        self.assertEqual(details["requested_tokens"], 452_228)
        self.assertEqual(details["known_tokens"], 547_773)
        self.assertEqual(details["remaining_known_tokens"], 452_227)
        self.assertEqual(details["input_estimate_limit"], 386_691)
        self.assertEqual((details["total_tokens"], details["http_limit"]), (1_000_000, 40))
        self.assertEqual((details["http_attempts"], details["reserved_tokens"]), (10, 0))
        self.assertEqual(details["unresolved_attempts"], [])
        self.assertIs(details["request_sent"], False)
        self.assertEqual(before, {key: value for key, value in self.contents().items()
                                  if key != budget.REJECTIONS_PATH})
        audit = json.loads((self.root / budget.REJECTIONS_PATH).read_text())
        self.assertEqual(audit["rejections"], [details])
        report = budget.report(self.root)
        self.assertEqual(report["last_rejection"], details)
        self.assertTrue(report["last_rejection_current"])
        self.assertEqual((report["status"], report["stop_reason"]),
                         ("blocked", "admission_reservation_exceeded"))
        self.assertFalse(report["report_is_send_permission"])
        self.assertFalse(report["known_tokens_exceeded_limit"])

    def test_rejection_diagnostics_do_not_persist_callers_strings(self):
        """拒绝证据不接收 request_id／provider 的任意文本，避免把密钥和正文写入日志。"""
        self.initialize()
        with self.assertRaises(budget.TaskBudgetError) as caught:
            self.reserve(request_id="synthetic-private-request", provider="synthetic-private-provider",
                         input_estimate=901)
        serialized = json.dumps(caught.exception.diagnostics)
        self.assertNotIn("synthetic-private", serialized)
        self.assertNotIn("synthetic-private", (self.root / budget.REJECTIONS_PATH).read_text())
        self.assertEqual(str(caught.exception), "task_budget_tokens_exhausted")
        self.assertEqual(budget.load(self.root)["http_attempts"], 0)

    def test_rejections_accumulate_and_success_makes_old_snapshot_historical(self):
        """多次被拒绝的估算各自保留，更小的合法请求仍可发送且不沿用旧阻塞结论。"""
        self.initialize()
        for estimate in (901, 902):
            with self.assertRaisesRegex(budget.TaskBudgetError, "tokens_exhausted"):
                self.reserve(input_estimate=estimate)
        original = json.loads((self.root / budget.REJECTIONS_PATH).read_text())
        self.assertEqual([item["rejection"] for item in original["rejections"]], [1, 2])
        self.assertEqual([item["input_estimate"] for item in original["rejections"]], [901, 902])
        attempt = self.reserve(input_estimate=900)
        budget.finish(self.root, attempt, status="responded", usage={"total_tokens": 20})
        report = budget.report(self.root)
        self.assertFalse(report["last_rejection_current"])
        self.assertEqual(report["last_rejection"], original["rejections"][-1])
        self.assertEqual((report["status"], report["stop_reason"]), ("ready", None))
        self.assertEqual(original, json.loads((self.root / budget.REJECTIONS_PATH).read_text()))

    def test_actual_usage_exhausted_has_distinct_rejection_reason(self):
        """实际已知用量用尽与预约保护拒绝分开，超额和负输入门槛按真值留存。"""
        self.initialize()
        budget.finish(self.root, self.reserve(), status="responded", usage={"total_tokens": 1050})
        with self.assertRaisesRegex(budget.TaskBudgetError, "tokens_exhausted") as caught:
            self.reserve(input_estimate=0)
        details = caught.exception.diagnostics
        self.assertEqual(details["reason"], "actual_usage_exhausted")
        self.assertEqual(details["remaining_known_tokens"], 0)
        self.assertEqual(details["input_estimate_limit"], -150)
        self.assertEqual(details["known_tokens"], 1050)
        self.assertEqual(budget.report(self.root)["stop_reason"], "tokens_exhausted")

    def test_unknown_rejection_retains_reservation_after_usage_reconciliation(self):
        """未知用量优先阻断；后来真实补结算不篡改拒绝当时的余额和在途预留。"""
        self.initialize()
        attempt = self.reserve()
        with self.assertRaisesRegex(budget.TaskBudgetError, "usage_unresolved") as caught:
            self.reserve(input_estimate=2000)
        details = caught.exception.diagnostics
        self.assertEqual(details["reason"], "usage_unresolved")
        self.assertEqual((details["known_tokens"], details["reserved_tokens"]), (0, 300))
        self.assertEqual(details["unresolved_attempts"], [1])
        self.assertEqual(budget.load(self.root)["http_attempts"], 1)
        budget.finish(self.root, attempt, status="responded", usage={"total_tokens": 42})
        report = budget.report(self.root)
        self.assertEqual(report["last_rejection"], details)
        self.assertFalse(report["last_rejection_current"])
        self.assertEqual((report["known_tokens"], report["reserved_tokens"]), (42, 0))
        self.assertEqual(self.reserve()["attempt"], 2)

    def test_rejection_evidence_survives_fresh_python_process(self):
        """重启后仍能取得原始拒绝精确估算与终态，不仅依赖异常对象或内存缓存。"""
        self.initialize()
        with self.assertRaises(budget.TaskBudgetError) as caught:
            self.reserve(input_estimate=901)
        code = ("import json,sys; from pathlib import Path; "
                "from backend.app.runtime.task_budget import report; "
                "print(json.dumps(report(Path(sys.argv[1]))))")
        result = subprocess.run([sys.executable, "-c", code, str(self.root)],
                                capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertEqual(report["last_rejection"], caught.exception.diagnostics)
        self.assertEqual((report["http_attempts"], report["known_tokens"]), (0, 0))
        self.assertEqual(report["stop_reason"], "admission_reservation_exceeded")

    def test_failed_rejection_evidence_write_does_not_issue_permission(self):
        """诊断落盘失败仍关闭发送入口，不消耗 HTTP 或抹掉原始账本。"""
        self.initialize()
        before = self.contents()
        with patch.object(budget.os, "replace", side_effect=OSError("synthetic audit write failure")):
            with self.assertRaisesRegex(budget.TaskBudgetError, "storage_error"):
                self.reserve(input_estimate=901)
        self.assertEqual(before, self.contents())
        self.assertEqual(budget.load(self.root)["http_attempts"], 0)

    def test_corrupt_rejection_history_blocks_new_reservation_without_overwriting(self):
        """损坏的诊断历史不能静默覆盖，字段注入、伪造计数和余额均关闭新发送。"""
        self.initialize()
        with self.assertRaises(budget.TaskBudgetError):
            self.reserve(input_estimate=901)
        path = self.root / budget.REJECTIONS_PATH
        original = path.read_text()
        mutations = ["{", "[]", original[:-1] + ', "rejections": []}']
        for key, value in (("input_estimate", True), ("remaining_known_tokens", 0),
                           ("http_attempts", 1), ("ledger_revision", 1), ("reason", "ready"),
                           ("request_sent", 0), ("private_extra", "synthetic-private")):
            data = json.loads(original)
            data["rejections"][0][key] = value
            mutations.append(json.dumps(data))
        for text in mutations:
            with self.subTest(text=text[:60]):
                path.write_text(text)
                with self.assertRaisesRegex(budget.TaskBudgetError, "corrupt"):
                    self.reserve()
                with self.assertRaisesRegex(budget.TaskBudgetError, "corrupt"):
                    budget.report(self.root)
                self.assertEqual(path.read_text(), text)
                self.assertEqual(budget.load(self.root)["http_attempts"], 0)
        path.write_text(original)
        self.assertEqual(self.reserve()["attempt"], 1)

    def test_rejection_evidence_symlink_or_orphan_fails_closed(self):
        """诊断文件不能借链接越界；仅剩拒绝痕迹时也不能被误认成旧任务。"""
        self.initialize()
        with self.assertRaises(budget.TaskBudgetError):
            self.reserve(input_estimate=901)
        path = self.root / budget.REJECTIONS_PATH
        copy = self.root / "old-rejections.json"
        path.rename(copy)
        path.symlink_to(copy)
        with self.assertRaisesRegex(budget.TaskBudgetError, "unsafe_path"):
            self.reserve()
        path.unlink()
        copy.rename(path)
        for name in (budget.STATE_PATH, budget.MARKER_PATH, budget.LOCK_PATH):
            (self.root / name).unlink()
        with self.assertRaisesRegex(budget.TaskBudgetError, "recovery_missing"):
            self.reserve()

    def test_output_cap_can_only_be_lowered_per_attempt(self):
        """单次请求可以减少输出预留，不得突破任务已配置的输出上限。"""
        self.initialize()
        for kwargs in ({"max_output_tokens": 101}, {"max_output_tokens": True},
                       {"input_estimate": -1}, {"input_estimate": 1.5}, {"provider": ""}):
            with self.assertRaisesRegex(budget.TaskBudgetError, "reservation_invalid"):
                self.reserve(**kwargs)
        attempt = self.reserve(max_output_tokens=25)
        self.assertEqual((attempt["max_output_tokens"], attempt["reserved_tokens"]), (25, 225))

    def test_actual_usage_overshoot_is_reported_without_truncating_cost(self):
        """输入估算误差可使实际成本超额，必须保留真值并停止，不能声称精确硬帽。"""
        self.initialize()
        budget.finish(self.root, self.reserve(), status="responded", usage={"total_tokens": 1050})
        report = budget.report(self.root)
        self.assertEqual(report["known_tokens"], 1050)
        self.assertTrue(report["known_tokens_exceeded_limit"])
        self.assertEqual(report["stop_reason"], "tokens_exhausted")
        with self.assertRaisesRegex(budget.TaskBudgetError, "tokens_exhausted"):
            self.reserve(input_estimate=0)

    def test_missing_any_recovery_file_fails_closed_and_never_resets(self):
        """锁、启用标记、账本任意遗失都不能静默回到旧模式或重新初始化。"""
        for index, name in enumerate((budget.STATE_PATH, budget.MARKER_PATH, budget.LOCK_PATH)):
            with self.subTest(name=name):
                root = self.root / str(index)
                budget.initialize(root)
                (root / name).unlink()
                with self.assertRaisesRegex(budget.TaskBudgetError, "recovery_missing"):
                    budget.load(root)
                with self.assertRaisesRegex(budget.TaskBudgetError, "new_empty_task_required"):
                    budget.initialize(root)
                self.assertFalse((root / name).exists())

    def test_corrupt_json_version_counts_and_limits_fail_closed(self):
        """损坏、版本漂移、汇总不一致及擅改限额不能作为恢复依据。"""
        self.initialize()
        attempt = self.reserve()
        budget.finish(self.root, attempt, status="responded", usage={"total_tokens": 20})
        path = self.root / budget.STATE_PATH
        original = path.read_text()
        mutations = ["{", "[]", original[:-1] + ', "http_attempts": 0}']
        for key, value in (("schema", "future-v2"), ("http_attempts", 0), ("known_tokens", 0),
                           ("revision", False), ("limits", {"total_tokens": 2000})):
            data = json.loads(original)
            data[key] = value
            mutations.append(json.dumps(data))
        for text in mutations:
            with self.subTest(text=text[:80]):
                path.write_text(text)
                with self.assertRaisesRegex(budget.TaskBudgetError, "corrupt"):
                    budget.load(self.root)
                with self.assertRaisesRegex(budget.TaskBudgetError, "corrupt"):
                    self.reserve()
                self.assertEqual(path.read_text(), text)
        path.write_text(original)
        self.assertEqual(budget.load(self.root)["known_tokens"], 20)

    def test_concurrent_reservations_cannot_overspend(self):
        """多个并发调用只有第一个取得已持久化许可，其余见到未决用量而停止。"""
        self.initialize()

        def try_reserve(index):
            """收集并发预留结果，不模拟任何模型响应或网络发送。"""
            try:
                return self.reserve(request_id=f"parallel-{index}")
            except budget.TaskBudgetError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(try_reserve, range(8)))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual(results.count("task_budget_usage_unresolved"), 7)
        self.assertEqual(budget.load(self.root)["http_attempts"], 1)
        rejections = json.loads((self.root / budget.REJECTIONS_PATH).read_text())["rejections"]
        self.assertEqual([item["rejection"] for item in rejections], list(range(1, 8)))
        self.assertTrue(all(item["http_attempts"] == 1 and item["request_sent"] is False
                            for item in rejections))

    def test_persistence_in_fresh_python_process(self):
        """用全新解释器只读恢复，证明预算并非仅保存在进程内存。"""
        self.initialize()
        budget.finish(self.root, self.reserve(), status="responded", usage={"total_tokens": 42})
        code = ("import json,sys; from pathlib import Path; "
                "from backend.app.runtime.task_budget import report; "
                "print(json.dumps(report(Path(sys.argv[1]))))")
        result = subprocess.run([sys.executable, "-c", code, str(self.root)],
                                capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertEqual((report["http_attempts"], report["known_tokens"]), (1, 42))

    def test_concurrent_processes_share_one_reservation(self):
        """不同 Python 进程共用磁盘锁，只能产生一个未决实际发送许可。"""
        self.initialize()
        gate = Path(self.temporary.name) / "start"
        code = """import json, sys, time
from pathlib import Path
from backend.app.runtime import task_budget as budget
while not Path(sys.argv[2]).exists():
    time.sleep(0.005)
try:
    result = budget.reserve(Path(sys.argv[1]), request_id=sys.argv[3], provider="deepseek", input_estimate=10)
except budget.TaskBudgetError as error:
    result = error.code
print(json.dumps(result))
"""
        processes = []
        try:
            for index in range(6):
                processes.append(subprocess.Popen(
                    [sys.executable, "-c", code, str(self.root), str(gate), f"process-{index}"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            gate.touch()
            results = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stderr)
                results.append(json.loads(stdout))
            self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
            self.assertEqual(results.count("task_budget_usage_unresolved"), 5)
            self.assertEqual(budget.load(self.root)["http_attempts"], 1)
            rejections = json.loads((self.root / budget.REJECTIONS_PATH).read_text())["rejections"]
            self.assertEqual([item["rejection"] for item in rejections], list(range(1, 6)))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def test_atomic_write_failure_does_not_issue_send_permission(self):
        """原子替换失败不返回预留许可，磁盘仍保存上一次完整账本。"""
        self.initialize()
        before = self.contents()
        with patch.object(budget.os, "replace", side_effect=OSError("synthetic disk failure")):
            with self.assertRaisesRegex(budget.TaskBudgetError, "storage_error"):
                self.reserve()
        self.assertEqual(before, self.contents())
        self.assertEqual(budget.load(self.root)["http_attempts"], 0)

    def test_failure_after_replace_retains_uncertain_reservation(self):
        """重命名后同步失败可能已落盘，不能把异常当成可退还预算。"""
        self.initialize()
        with patch.object(budget, "_sync_directory", side_effect=OSError("synthetic fsync failure")):
            with self.assertRaisesRegex(budget.TaskBudgetError, "storage_error"):
                self.reserve()
        self.assertEqual(budget.load(self.root)["http_attempts"], 1)
        with self.assertRaisesRegex(budget.TaskBudgetError, "usage_unresolved"):
            self.reserve()

    def test_interrupted_initialization_is_not_resumable_as_empty(self):
        """只写完启用标记的中断初始化必须显式处理，不能重新造零计数账本。"""
        original = budget._write

        def fail_ledger(path, data):
            """在创建账本前注入故障，保留已持久化的启用标记和锁。"""
            if path.name == Path(budget.STATE_PATH).name:
                raise OSError("synthetic initialization crash")
            return original(path, data)

        with patch.object(budget, "_write", side_effect=fail_ledger):
            with self.assertRaises(OSError):
                self.initialize()
        with self.assertRaisesRegex(budget.TaskBudgetError, "recovery_missing"):
            budget.load(self.root)
        with self.assertRaisesRegex(budget.TaskBudgetError, "new_empty_task_required"):
            self.initialize()

    def test_invalid_attempt_and_status_cannot_change_ledger(self):
        """错误请求身份与非法结束状态不能结算其他任务的用量。"""
        self.initialize()
        attempt = self.reserve()
        before = self.contents()
        for wrong in (0, 1, -1, True, 2, {**attempt, "budget_id": "different"},
                      {**attempt, "request_id": "wrong-logical-request"}):
            with self.assertRaisesRegex(budget.TaskBudgetError, "attempt_invalid"):
                budget.finish(self.root, wrong, status="responded", usage={"total_tokens": 1})
        for status in ("", "send_unknown", None):
            with self.assertRaisesRegex(budget.TaskBudgetError, "status_invalid"):
                budget.finish(self.root, attempt, status=status, usage={"total_tokens": 1})
        self.assertEqual(before, self.contents())

    def test_symlink_budget_file_rejected(self):
        """账本符号链接即使指向有效 JSON，也不能扩大恢复读取范围。"""
        self.initialize()
        state = self.root / budget.STATE_PATH
        moved = self.root / "original.json"
        state.rename(moved)
        state.symlink_to(moved)
        with self.assertRaisesRegex(budget.TaskBudgetError, "unsafe_path"):
            budget.load(self.root)

    def test_corrupt_marker_and_lock_fail_closed(self):
        """启用标记和锁内容损坏同样阻断恢复，不能仅凭账本存在继续发送。"""
        self.initialize()
        for name, content in ((budget.MARKER_PATH, b"{}"), (budget.LOCK_PATH, b"")):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(content)
                with self.assertRaisesRegex(budget.TaskBudgetError, "corrupt"):
                    budget.load(self.root)
                path.write_bytes(original)


if __name__ == "__main__":
    main()
