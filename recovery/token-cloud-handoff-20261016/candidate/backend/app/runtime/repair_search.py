"""在任务授权文件内执行有界字面搜索，不运行 shell 或正则。"""
import hashlib
import json
from pathlib import Path

from .tools import MAX_BYTES


def search(tools, query: str, cursor: int = 0, version: str | None = None, path: str | None = None) -> dict:
    """绑定当前文件集合版本，分页返回真实命中及可继续查询位置。"""
    if not isinstance(query, str) or not 1 <= len(query) <= 200 or type(cursor) is not int or cursor < 0:
        raise ValueError('repair_search_parameters_invalid')
    tools._refresh_files()
    # 范围只过滤已有授权集合，不将目录下未授权文件加入搜索。
    selected = None
    if path is not None:
        if (not isinstance(path, str) or not path or Path(path).is_absolute()
                or '..' in Path(path).parts or Path(path).as_posix() in ('.', '')):
            raise ValueError('repair_search_scope_invalid')
        current = tools.workspace
        for part in Path(path).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError('repair_search_scope_invalid')
        selected = tools._safe_path(path)
        if selected.is_symlink() or not selected.exists():
            raise ValueError('repair_search_scope_invalid')
    files = []
    for target in sorted(tools.readable):
        relative = str(target.relative_to(tools.workspace))
        if not target.is_file() or tools._safe_path(relative) != target or target.is_symlink():
            continue
        if selected is not None and target != selected and selected not in target.parents:
            continue
        raw = target.read_bytes()
        files.append((relative, hashlib.sha256(raw).hexdigest(), raw))
    if selected is not None and not files:
        raise ValueError('repair_search_scope_invalid')
    identity = [query, [(p, h) for p, h, _ in files]]
    if selected is not None:
        identity.append(str(selected.relative_to(tools.workspace)))
    fingerprint = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    if cursor and version != fingerprint:
        raise ValueError('repair_search_version_changed')
    matches, skipped = [], []
    index, next_cursor = 0, None
    for path, digest, raw in files:
        try:
            if b'\x00' in raw:
                raise UnicodeError()
            lines = raw.decode('utf-8').splitlines()
        except UnicodeError:
            skipped.append(path)
            continue
        for number, line in enumerate(lines, 1):
            position = line.find(query)
            if position < 0:
                continue
            if index < cursor:
                index += 1
                continue
            # 只返回命中附近片段，搜索不能冒充全文读取或完整行覆盖。
            first = max(0, position - 100)
            snippet = line[first:first + 400]
            item = {'path': path, 'line': number, 'snippet': snippet, 'sha256': digest,
                    'snippet_truncated': first > 0 or first + len(snippet) < len(line)}
            if len(matches) == 50 or len(json.dumps(matches + [item], ensure_ascii=False).encode()) > MAX_BYTES - 4096:
                next_cursor = index
                break
            matches.append(item)
            index += 1
        if next_cursor is not None:
            break
    result = {'query': query, 'matches': matches, 'version': fingerprint, 'next_cursor': next_cursor,
            'truncated': next_cursor is not None, 'skipped_non_text_files': skipped,
            'scope': 'authorized_task_files', 'content_is_full_file': False}
    if selected is not None:
        result['path'] = str(selected.relative_to(tools.workspace))
    # 二进制路径清单也受整体输出上限约束，不让元数据绕过字节限制。
    while len(json.dumps(result, ensure_ascii=False).encode()) > MAX_BYTES and skipped:
        skipped.pop()
        result['skipped_list_truncated'] = True
    return result
