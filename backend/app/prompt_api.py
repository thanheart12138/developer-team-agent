"""提示词管理接口，统一复用文件校验与评测门禁。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .runtime.prompt_management import PromptStore
from .runtime.prompt_real_evaluation import RealEvaluation

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


class VersionRequest(BaseModel):
    """创建候选版本时提交预期注册表身份。"""
    text: str = Field(min_length=1, max_length=100_000)
    expected_hash: str


class CasesRequest(BaseModel):
    """案例编辑携带旧内容身份，拒绝覆盖并发更新。"""
    document: dict
    expected_hash: str


class EvaluationRequest(BaseModel):
    """导入离线输出进行检查，不接受客户端指定真实来源。"""
    version: str
    observations: dict


class JudgmentRequest(BaseModel):
    """明确记录人工语义判断和理由。"""
    case_id: str
    passed: bool
    reason: str = Field(min_length=1)


class ActivationRequest(BaseModel):
    """激活明确绑定候选、评测和当前注册表。"""
    version: str
    report_id: str
    expected_hash: str
    confirmed: bool


def store() -> PromptStore:
    """创建项目文件存储；测试可注入隔离目录。"""
    return PromptStore()


def invoke(action):
    """将明确文件及契约错误映射到可操作接口状态。"""
    try:
        return action()
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(404, detail={"code": str(exc)}) from exc
    except (ValueError, FileExistsError) as exc:
        raise HTTPException(409, detail={"code": str(exc)}) from exc


@router.get("")
def list_prompts():
    """展示注册身份与当前版本，不将旧角色标为新返修必需角色。"""
    current = store()
    registry, digest = current.registry()
    return {"registry_hash": digest, "prompts": [{"name": name, **entry} for name, entry in registry["prompts"].items()]}


@router.get("/evaluations/{report_id}")
def get_report(report_id: str):
    """加载服务器生成的评测及逐例检查结果。"""
    return invoke(lambda: store().report(report_id))


@router.post("/evaluations/{report_id}/judgments")
def judge_report(report_id: str, payload: JudgmentRequest):
    """人工判断只补充语义检查，不放宽程序断言。"""
    return invoke(lambda: store().judge(report_id, payload.case_id, payload.passed, payload.reason))


@router.get("/{name}")
def prompt_detail(name: str):
    """返回候选、历史版本、变量、案例和并发身份。"""
    return invoke(lambda: store().detail(name))


@router.get('/{name}/real-runs')
def list_real_runs(name: str):
    """展示由受控CLI准备的固定案例，页面不能生成批准文件。"""
    return invoke(lambda: {'runs': RealEvaluation(store()).runs(name)})


@router.post('/real-runs/{run_id}/execute')
def execute_real_run(run_id: str):
    """只执行已有明确授权的输入身份，重复点击返回原结果。"""
    return invoke(lambda: RealEvaluation(store()).run(run_id))


@router.post("/{name}/versions", status_code=201)
def create_version(name: str, payload: VersionRequest):
    """创建新候选，保持原激活版本不变。"""
    return invoke(lambda: store().create_version(name, payload.text, payload.expected_hash))


@router.put("/{name}/cases")
def update_cases(name: str, payload: CasesRequest):
    """受控更新案例，旧报告不得继续证明新预期。"""
    return invoke(lambda: store().save_cases(name, payload.document, payload.expected_hash))


@router.post("/{name}/evaluations", status_code=201)
def evaluate_prompt(name: str, payload: EvaluationRequest):
    """执行离线评测并持久化结果，未知Token不记作零。"""
    return invoke(lambda: store().run_offline(name, payload.version, payload.observations))


@router.get("/{name}/evaluations")
def list_evaluations(name: str):
    """提供可再次打开的历史评测摘要。"""
    return invoke(lambda: {"reports": store().list_reports(name)})


@router.post("/{name}/activate")
def activate_prompt(name: str, payload: ActivationRequest):
    """服务端重新检查预期和版本证据，明确确认后切换激活。"""
    return invoke(lambda: store().activate(name, payload.version, payload.report_id,
                                         payload.expected_hash, payload.confirmed))
