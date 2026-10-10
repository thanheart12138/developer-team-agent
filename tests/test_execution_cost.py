"""成本分段边界回归，Token只能按真实请求完整归属。"""
from backend.app.runtime.execution_cost import classify


def request(index, tokens=10, status="responded", scope="repair-session:1"):
    """构造不触发模型的有序HTTP证据。"""
    return {"attempt":index,"request_id":str(index),"status":status,"scope":scope,
            "usage":{"total_tokens":tokens} if tokens is not None else None}


def action(index, name, before=None, after=None, passed=None, success=True):
    """生成版本与测试事实，保留外层成功和测试通过的区别。"""
    output={}
    if name=="run_unit_tests": output={"passed":passed,"file_hashes_before":before,"file_hashes_after":after,"command":"node --test"}
    if name=="submit_unit_for_test": output={"file_hashes":after}
    return {"model_request_id":str(index),"action":{"tool_name":name,"parameters":{"path":"product/a.js"}},
            "result":{"status":"succeeded" if success else "failed","output":output},
            "repair_versions_before":before or {},"repair_versions_after":after or {}}


def test_same_request_boundaries_and_other_overhead_are_not_double_counted():
    """修改、通过与提交同轮仅归修改前，规划Token单列。"""
    before={"product/a.js":"old"};after={"product/a.js":"new"}
    events=[action(1,"replace",before,after),action(1,"run_unit_tests",after,after,True),
            action(1,"submit_unit_for_test",after,after)]
    report=classify([request(1,30),request(2,20,scope="slice-plan:1")],events)
    assert report["phases"]["before_modify"]["known_tokens"]==30
    assert report["phases"]["after_green"]["http"]==0
    assert report["phases"]["other"]["known_tokens"]==20
    assert report["requests"][0]["boundaries"]==["first_effective_modify","first_current_self_test_passed","valid_explicit_submission"]
    assert report["known_tokens"]==50 and report["reconciled"]


def test_combined_verification_submission_counts_one_request():
    """收尾工具同HTTP通过测试并提交，Token仍按最早边界整笔归属。"""
    old = {"product/a.js": "old"}
    current = {"product/a.js": "new"}
    combined = action(2, "verify_and_submit", current, current)
    combined['result']['output'] = {'submitted': True, 'file_hashes': current,
        'self_test': {'passed': True, 'file_hashes_before': current, 'file_hashes_after': current}}
    report = classify([request(1), request(2)], [action(1, 'replace', old, current), combined])
    assert report['requests'][1]['boundaries'] == ['first_current_self_test_passed', 'valid_explicit_submission']
    assert report['requests'][1]['phase'] == 'before_self_test'
    assert report['http'] == 2 and report['reconciled']


def test_post_green_write_invalidates_test_and_retest_is_not_called_idle():
    """通过后修改消耗完整归属并标记重测，过期提交不能闭合。"""
    old={"product/a.js":"old"};one={"product/a.js":"one"};two={"product/a.js":"two"}
    events=[action(1,"replace",old,one),action(2,"run_unit_tests",one,one,True),
            action(3,"replace",one,two),action(3,"submit_unit_for_test",two,two),
            action(4,"run_unit_tests",two,two,True),action(5,"submit_unit_for_test",two,two)]
    report=classify([request(i) for i in range(1,6)],events)
    assert report["requests"][2]["post_green_rework"]
    assert "valid_explicit_submission" not in report["requests"][2]["boundaries"]
    assert report["requests"][3]["phase"]=="before_self_test"
    assert report["requests"][4]["phase"]=="after_green"


def test_unknown_usage_failed_retry_and_noop_write_preserve_uncertainty():
    """未知用量与失败尝试不记零成功，相同正文不当作有效修改。"""
    version={"product/a.js":"same"}
    report=classify([request(1,None,status="failed"),request(2,5)],
                    [action(2,"write",version,version),action(2,"run_unit_tests",version,version,False)])
    assert report["unknown_usage"]==1 and report["http"]==2
    assert report["known_tokens"]==5 and report["final_scopes"]["repair-session:1"]["first_modify"] is None
    assert report["final_scopes"]["repair-session:1"]["first_green"] is None


def test_legacy_unit_version_subset_can_prove_scoped_test_and_submission():
    """旧单元检查点只保存所有权范围，不能因全产品快照更大漏算绿灯。"""
    owned={"product/a.js":"new"};full={**owned,"product/b.js":"stable"}
    event=action(1,"run_unit_tests",full,full,True)
    event.pop("repair_versions_after");event.pop("repair_versions_before")
    event["unit_versions_after"]=owned
    submission=action(2,"submit_unit_for_test",owned,owned)
    report=classify([request(1,scope="slice:test:1"),request(2,scope="slice:test:1")],[event,submission])
    assert report["requests"][1]["phase"]=="after_green"
    assert "valid_explicit_submission" in report["requests"][1]["boundaries"]


def test_retry_with_same_logical_id_does_not_execute_boundaries_twice():
    """实际HTTP与逻辑ID分开，工具归最终响应，成本保留所有尝试。"""
    before={'product/a.js':'old'};after={'product/a.js':'new'}
    first=request(1);second=request(2);second['request_id']='1'
    result=classify([first,second],[action(1,'replace',before,after)])
    assert result['http']==2 and result['known_tokens']==20
    assert not result['requests'][0]['boundaries']
    assert result['requests'][1]['boundaries']==['first_effective_modify']
