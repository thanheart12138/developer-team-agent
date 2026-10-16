"""未来请求的安全响应保全；本模块不发送请求或执行生成代码。"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import quote

MAX_BYTES = 4 * 1024 * 1024
# SSE每个token附带事件字段，wire上限与重组语义正文上限分开，均为有限硬界。
MAX_WIRE_BYTES = 32 * 1024 * 1024
REDACTED = '[REDACTED_CREDENTIAL]'


def encode(value):
    # 使用确定性序列化，哈希覆盖实际保存字节。
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()


def usage_numbers(value):
    # reasoning属于completion，附加字段不重复累计或写入。
    if not isinstance(value, dict):
        return None
    keys = ('prompt_tokens', 'completion_tokens', 'total_tokens')
    if any(type(value.get(k)) is not int or value[k] < 0 for k in keys):
        return None
    if value['prompt_tokens'] + value['completion_tokens'] != value['total_tokens']:
        return None
    return {k: value[k] for k in keys}


def _pairs(pairs):
    # 重复键不能被JSON解析静默覆盖。
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_json_key')
        result[key] = value
    return result


def parse(raw):
    # 严格JSON拒绝NaN和重复字段；异常正文永不记日志。
    return json.loads(raw, object_pairs_hook=_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))


def sanitize(value, secrets):
    # 检测已知凭据原文、JSON嵌套转义、URL及base64形态和显式认证字段。
    variants = set()
    for secret in secrets:
        if not isinstance(secret, str) or not secret:
            raise ValueError('invalid_scan_secret')
        variants.update((secret, quote(secret, safe=''), base64.b64encode(secret.encode()).decode()))
        escaped = secret
        for _ in range(4):
            escaped = json.dumps(escaped, ensure_ascii=True)[1:-1]
            variants.add(escaped)
    variants = sorted(variants, key=len, reverse=True)
    changed = False
    locations = []
    if not secrets:
        raise ValueError('scan_secrets_required')

    def clean(item, depth=0, location='$'):
        # 限制递归，过深返回安全失败，不能将未扫描尾部写出。
        nonlocal changed
        if depth > 64:
            raise ValueError('response_nesting_limit')
        if isinstance(item, str):
            result = item
            for secret in variants:
                if secret in result:
                    changed = True
                    result = result.replace(secret, REDACTED)
                    locations.append({'location':location,'type':'known_credential_variant'})
            return result
        if isinstance(item, list):
            return [clean(v, depth + 1, f'{location}/array[{i}]') for i,v in enumerate(item)]
        if isinstance(item, dict):
            result = {}
            for index, (key, child) in enumerate(item.items()):
                safe_key = clean(key, depth + 1, f'{location}/object[{index}]/key')
                if re.fullmatch(r'(?i)(authorization|api[_-]?key|access[_-]?token|password|secret)', key):
                    changed = True
                    safe_child = REDACTED
                    locations.append({'location':f'{location}/object[{index}]/value','type':'authentication_field'})
                else:
                    safe_child = clean(child, depth + 1, f'{location}/object[{index}]/value')
                if safe_key in result:
                    # 键脱敏后碰撞也不能覆盖证据。
                    raise ValueError('redacted_key_collision')
                result[safe_key] = safe_child
            return result
        return item

    result = clean(value)
    return result, changed, locations


class _Directory:
    # 从根开始逐段O_NOFOLLOW打开，并始终以同一目录FD操作，防路径替换。
    def __init__(self, path=None, *, descriptor=None):
        if descriptor is not None:
            self.fd = descriptor
            return
        path = Path(path).absolute()
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in path.parts[1:]:
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = new
            self.fd = fd
        except BaseException:
            os.close(fd)
            raise

    def close(self):
        # 仅关闭本次拥有的FD，不根据当前路径删除目录。
        os.close(self.fd)

    def __truediv__(self, name):
        return _Member(self, name)

    def child(self, name):
        # 成员名必须固定单层路径；打开后不再重走字符串路径。
        _name(name)
        return _Directory(descriptor=os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd))


class _Member:
    # 内部固定成员，只供有界FD读写；不暴露任意路径穿越能力。
    def __init__(self, parent, name):
        _name(name)
        self.parent, self.name = parent, name


def _name(name):
    # 文件名不含斜杠、点段或空值。
    if not isinstance(name, str) or not name or '/' in name or name in {'.','..'}:
        raise ValueError('unsafe_member')


def _read(member, limit):
    # 检查与读取均基于同一O_NOFOLLOW FD，额外一字节检测超限。
    import stat
    fd = os.open(member.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=member.parent.fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('not_regular_file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('evidence_read_oversize')
        return data
    finally:
        os.close(fd)


def _write(member, data):
    # 固定目录FD内独占临时文件，fsync后原子替换并同步目录。
    import uuid
    tmp = '.writing-' + uuid.uuid4().hex
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=member.parent.fd)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, member.name, src_dir_fd=member.parent.fd, dst_dir_fd=member.parent.fd)
        os.fsync(member.parent.fd)
    finally:
        try:
            os.unlink(tmp, dir_fd=member.parent.fd)
        except FileNotFoundError:
            pass


def recover(root):
    # 恢复只核同一FD读取的字节；缺证、大小异常或篡改均不允许执行。
    directory = target = None
    try:
        directory = _Directory(root)
        target = directory.child('response')
        manifest_bytes = _read(target/'manifest.json', 65536)
        manifest = parse(manifest_bytes)
        try:
            receipt = parse(_read(directory/'capture-status.json', 65536))
            if receipt.get('manifest_sha256') != hashlib.sha256(manifest_bytes).hexdigest():
                raise ValueError('manifest_hash')
        except FileNotFoundError:
            pass
        if manifest['schema'] != 'safe-response-evidence-v1':
            raise ValueError('schema')
        wire_format = manifest.get('received_format', 'json')
        if wire_format not in {'json','sse'}:
            raise ValueError('received_format')
        received_name = 'response-received.json' if wire_format == 'json' else 'response-received.sse'
        expected = ({'response.json','tool-actions.json'} if not manifest.get('received_entity_saved',not manifest['credentials_redacted']) else
                    {'response.json','tool-actions.json',received_name})
        if set(manifest['files']) != expected:
            raise ValueError('missing_member')
        for name, digest in manifest['files'].items():
            if hashlib.sha256(_read(target/name, MAX_WIRE_BYTES if name == 'response-received.sse' else MAX_BYTES)).hexdigest() != digest:
                raise ValueError('hash')
        return {'evidence_status': manifest['evidence_status'], 'execution_allowed':False,
                'requires_current_execution_gate':True,'manifest':manifest}
    except (OSError, ValueError, KeyError, TypeError):
        return {'evidence_status':'missing_or_corrupt','execution_allowed':False}
    finally:
        if target is not None:
            target.close()
        if directory is not None:
            directory.close()


def _status(root, value):
    # 只写安全状态/数字，写失败也不得放行执行。
    try:
        _write(root/'capture-status.json', encode(value))
        return value
    except OSError:
        return {**value, 'execution_allowed':False, 'status_record_saved':False}


def capture_stream(root, stream, secrets, usage_sink, **options):
    # HTTP层先有自己的单次尝试账；只读有界响应，多读一字节检测超限。
    limit = options.get('max_bytes', MAX_BYTES)
    if type(limit) is not int or not 1 <= limit <= MAX_BYTES:
        raise ValueError('evidence_size_limit')
    raw = stream.read(limit + 1)
    return capture(root, raw, secrets, usage_sink, **options)


def _capture(root, raw, secrets, usage_sink, *, observed_usage=None, http_status=200, max_bytes=MAX_BYTES, received_entity=None, received_entity_complete=True, received_entity_scan='safe', received_entity_format='sse'):
    # 每次请求使用独占证据根；usage先独立结算，随后才允许保存或审查动作。
    if received_entity_format not in {'json','sse'}:
        raise ValueError('received_format_invalid')
    if received_entity_scan not in {'safe','redacted','unscannable'}:
        raise ValueError('received_scan_invalid')
    if type(received_entity_complete) is not bool:
        raise ValueError('received_completeness_invalid')
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES:
        raise ValueError('evidence_size_limit')
    descriptor = os.open('capture.claim', os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=root.fd)
    os.fsync(descriptor)
    os.close(descriptor)
    body = None
    failure = None
    if received_entity is not None and (not isinstance(received_entity,bytes) or len(received_entity)>MAX_WIRE_BYTES):
        failure = 'received_entity_oversize_or_missing'
    if not isinstance(raw, bytes) or len(raw) > max_bytes:
        failure = 'response_oversize_or_missing'
    else:
        try:
            body = parse(raw)
            if not isinstance(body, dict):
                raise ValueError('response_object_required')
        except (ValueError, UnicodeError, RecursionError):
            failure = 'response_invalid_json'
    usage = usage_numbers(body.get('usage')) if isinstance(body, dict) else None
    observed = usage_numbers(observed_usage)
    if observed_usage is not None:
        if observed is None or (usage is not None and usage != observed):
            usage = None
            failure = 'usage_conflict_or_invalid'
        elif usage is None:
            usage = observed
    settlement_succeeded = False
    try:
        usage_sink(usage)
        settlement_succeeded = True
    except Exception:
        failure = 'usage_settlement_failed'
    try:
        _write(root/'usage-receipt.json', encode({'usage':usage, 'actual_known':usage is not None,
                                                'settlement_succeeded':settlement_succeeded}))
    except OSError:
        failure = 'usage_receipt_write_failed'
    if failure:
        return _status(root, {'evidence_status':failure, 'execution_allowed':False, 'usage':usage, 'settlement_succeeded':settlement_succeeded})
    staging = None
    staging_name = None
    try:
        safe, redacted, locations = sanitize(body, secrets)
        redacted = redacted or received_entity_scan == 'redacted'
        received_format = 'json' if received_entity is None else received_entity_format
        received = raw if received_entity is None else received_entity
        if received_entity is not None:
            _, entity_redacted, entity_locations = sanitize(received_entity.decode('utf-8'), secrets)
            redacted = redacted or entity_redacted
            locations.extend({'location':'$/received_entity','type':item['type']} for item in entity_locations)
        choices = safe.get('choices')
        complete = (received_entity_scan == 'safe' and received_entity_complete and http_status == 200 and isinstance(choices, list) and len(choices) == 1
                    and choices[0].get('finish_reason') in {'stop','tool_calls'})
        actions = [c.get('message', {}).get('tool_calls', []) for c in (choices or [])]
        files = {'response.json':encode(safe), 'tool-actions.json':encode(actions)}
        if not redacted and received_entity_scan == 'safe':
            files['response-received.json' if received_format == 'json' else 'response-received.sse'] = received
        if sum(len(data) for name,data in files.items() if name!='response-received.sse') > max_bytes:
            raise ValueError('sanitized_evidence_oversize')
        status = 'redacted_unsafe' if redacted else 'complete' if complete else 'incomplete_response'
        manifest = {'schema':'safe-response-evidence-v1','evidence_status':status,
                    'source_body_complete':complete,'credentials_redacted':redacted,
                    'usage_known':usage is not None,'http_status':http_status,
                    'generated_code_executed':False,
                    'received_format':received_format,
                    'received_entity_complete':received_entity_complete,
                    'received_entity_saved':not redacted and received_entity_scan == 'safe',
                    'received_entity_scan':received_entity_scan,
                    'representation':{'response.json':'reencoded_sanitized_json',
                                      'tool-actions.json':'derived_sanitized_tool_calls',
                                      ('response-received.json' if received_format == 'json' else 'response-received.sse'):'omitted_due_to_redaction_or_scan_failure' if redacted or received_entity_scan != 'safe' else 'exact_received_entity_bytes'},
                    'redaction_locations':locations,
                    'files':{name:hashlib.sha256(data).hexdigest() for name,data in files.items()}}
        import uuid
        staging_name = '.response-staging-' + uuid.uuid4().hex
        os.mkdir(staging_name, 0o700, dir_fd=root.fd)
        staging = root.child(staging_name)
        for name, data in files.items():
            _write(staging/name, data)
        _write(staging/'manifest.json', encode(manifest))
        try:
            os.stat('response', dir_fd=root.fd, follow_symlinks=False)
            raise ValueError('response_already_exists')
        except FileNotFoundError:
            pass
        # 私有独占根不允许其他写入者；claim防本程序重复capture。
        os.rename(staging_name, 'response', src_dir_fd=root.fd, dst_dir_fd=root.fd)
        staging_name = None
        os.fsync(root.fd)
        return _status(root, {'evidence_status':status,'execution_allowed':complete and not redacted and usage is not None,
                'usage':usage,'settlement_succeeded':settlement_succeeded,'manifest_sha256':hashlib.sha256(encode(manifest)).hexdigest()})
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        return _status(root, {'evidence_status':'safe_preservation_failed','execution_allowed':False,'usage':usage,'settlement_succeeded':settlement_succeeded})
    finally:
        if staging is not None:
            if staging_name is not None:
                for name in ('response.json','tool-actions.json','response-received.json','response-received.sse','manifest.json'):
                    try:
                        os.unlink(name, dir_fd=staging.fd)
                    except FileNotFoundError:
                        pass
                os.rmdir(staging_name, dir_fd=root.fd)
            staging.close()


def _settle_without_storage(raw, usage_sink, options, reason):
    # 根不可用不能把已知usage丢成零；只回传安全数字，不访问替换后的文件。
    usage = None
    if isinstance(raw,bytes) and len(raw)<=MAX_BYTES:
        try:
            body=parse(raw)
            usage=usage_numbers(body.get('usage')) if isinstance(body,dict) else None
        except (ValueError,UnicodeError,RecursionError):
            pass
    observed=usage_numbers(options.get('observed_usage'))
    if options.get('observed_usage') is not None:
        usage = None if observed is None or (usage is not None and usage != observed) else observed
    settled=False
    try:
        usage_sink(usage)
        settled=True
    except Exception:
        pass
    return {'evidence_status':reason,'execution_allowed':False,'usage':usage,
            'settlement_succeeded':settled}


def capture(root, raw, secrets, usage_sink, *, expected_identity=None, **options):
    # 调用者必须分配当前请求独占私有根；绑定FD直到整个保全事务结束。
    try:
        directory = _Directory(root)
    except (OSError,ValueError):
        return _settle_without_storage(raw,usage_sink,options,'root_unavailable')
    try:
        stat = os.fstat(directory.fd)
        if expected_identity is not None and (stat.st_dev,stat.st_ino) != expected_identity:
            return _settle_without_storage(raw,usage_sink,options,'root_identity_changed')
        result = _capture(directory, raw, secrets, usage_sink, **options)
        check = None
        try:
            check = _Directory(root)
            old, current = os.fstat(directory.fd), os.fstat(check.fd)
            if (old.st_dev, old.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError('root_identity_changed')
        except (OSError, ValueError):
            result = _status(directory, {**result, 'execution_allowed':False,
                                        'root_identity_changed':True})
        finally:
            if check is not None:
                check.close()
        return result
    finally:
        directory.close()
