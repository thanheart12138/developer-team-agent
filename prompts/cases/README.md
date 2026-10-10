# 提示词案例目录

每个提示词一份`<name>.json`，保存contract、cases。案例输入只含可提交的非敏感数据，包含等级（important／normal／light）、类型（normal／boundary／counterexample）、预期与禁止行为、依据和受控checks。示例响应仅用于判定器回归，不能作为真实模型通过证据。

cases的ID在同一提示词中唯一。更新需匹配文件哈希，变更后旧报告不能用于激活。check只支持预定义的字段、结构、轨迹和人工判定，不执行脚本。无法自动判断的语义使用manual，未经人工判定保持pending。

结果与真实输入留在workspace/prompt-evaluations或workspace/experiments，不把密钥、个人数据或完整私有历史提交到本目录。页面后端负责校验与写入，历史提示词版本不可覆盖。
