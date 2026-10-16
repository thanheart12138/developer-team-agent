"""新候选显式SSE保全门：完整缓冲后才允许生产解析器使用同一字节。"""
import json
import os
import re
import httpx
from .response_evidence import MAX_BYTES, MAX_WIRE_BYTES, _write, capture, encode, parse, usage_numbers, sanitize, _Directory


class ResponseEvidenceError(httpx.HTTPError):
    # 只携带固定错误类别，不携带未扫描模型正文或认证。
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def assemble(raw):
    # 严格单choices流；保留可独立核对的usage，错误不伪装完整模型回复。
    text, reasoning, tools = [], [], {}
    usage = None
    usage_full = None
    details = []
    providers = []
    models = []
    seen_usage = False
    done = False
    finish = None
    error = None
    try:
        def complete_lines():
            # 按顺序解码完整帧：无效或截断的尾部不得
            # 抹去此前已在完整帧中独立观察的用量。
            offset = 0
            for boundary in re.finditer(rb'\r?\n\r?\n', raw):
                frame = raw[offset:boundary.start()].decode('utf-8')
                offset = boundary.end()
                yield from frame.splitlines()
            if offset != len(raw):
                raise ValueError('incomplete_sse_frame')
        for line in complete_lines():
            if not line or line.startswith(':'):
                continue
            if not line.startswith('data:') or done:
                raise ValueError('unexpected_sse_line')
            data = line[5:].strip()
            if data == '[DONE]':
                done = True
                continue
            event = parse(data)
            if not isinstance(event,dict):
                raise ValueError('invalid_event')
            model=event.get('model')
            if isinstance(model,str) and model and model not in models:models.append(model)
            provider=event.get('provider')
            if isinstance(provider,str) and provider and provider not in providers:providers.append(provider)
            choices = event.get('choices') or []
            if not isinstance(choices,list) or len(choices)>1:
                raise ValueError('multiple_choices')
            candidates = [event['usage']] if event.get('usage') is not None else []
            if choices and choices[0].get('usage') is not None:
                candidates.append(choices[0]['usage'])
            for candidate in candidates:
                current = usage_numbers(candidate)
                if seen_usage or current is None:
                    usage = None
                    raise ValueError('repeated_or_invalid_usage')
                seen_usage = True
                usage = current
                usage_full = candidate
            if not choices:
                continue
            choice = choices[0]
            if type(choice.get('index',0)) is not int or choice.get('index',0)!=0:
                raise ValueError('choice_index')
            delta = choice.get('delta') or {}
            if not isinstance(delta,dict):
                raise ValueError('invalid_delta')
            if finish is not None and (delta or choice.get('finish_reason')):
                # OpenRouter最终usage帧可重述相同finish，且只带空正文/assistant角色。
                # 不接受新语义、冲突finish、未知delta字段或非usage重复终态。
                terminal_usage = (bool(candidates) and choice.get('finish_reason') == finish
                    and set(delta).issubset({'content', 'role'})
                    and delta.get('content') in (None, '')
                    and delta.get('role') in (None, 'assistant'))
                if not terminal_usage:
                    raise ValueError('data_after_finish')
            delta=dict(delta)
            if delta.get('reasoning_content') and delta.get('reasoning') and delta['reasoning_content']!=delta['reasoning']:
                raise ValueError('conflicting_reasoning_aliases')
            if not delta.get('reasoning_content') and delta.get('reasoning') is not None:
                delta['reasoning_content']=delta['reasoning']
            chunk_details=delta.get('reasoning_details') or []
            if not isinstance(chunk_details,list) or any(not isinstance(item,dict) for item in chunk_details):
                raise ValueError('invalid_reasoning_details')
            details.extend(chunk_details)
            for key, target in (('content',text),('reasoning_content',reasoning)):
                value = delta.get(key)
                if value is not None:
                    if not isinstance(value,str):
                        raise ValueError('invalid_text')
                    target.append(value)
            calls = delta.get('tool_calls') or []
            if not isinstance(calls,list):
                raise ValueError('invalid_tool_calls')
            for item in calls:
                index = item.get('index')
                if type(index) is not int or not 0<=index<128 or item.get('type','function')!='function':
                    raise ValueError('tool_index_or_type')
                target = tools.setdefault(index,{'id':'','type':'function','function':{'name':'','arguments':''}})
                function = item.get('function') or {}
                for key, dest in (('id',target),('name',target['function']),('arguments',target['function'])):
                    value = item.get(key) if key=='id' else function.get(key)
                    if value is not None:
                        if not isinstance(value,str):
                            raise ValueError('tool_fragment')
                        dest[key] += value
            if choice.get('finish_reason') is not None:
                finish = choice['finish_reason']
        if not done or finish not in {'stop','tool_calls'}:
            raise ValueError('missing_done_or_valid_finish')
        if sorted(tools)!=list(range(len(tools))):
            raise ValueError('noncontiguous_tool_index')
        ids=set()
        for item in tools.values():
            if not item['id'] or item['id'] in ids or not item['function']['name']:
                raise ValueError('tool_identity')
            ids.add(item['id'])
            if not isinstance(parse(item['function']['arguments']),dict):
                raise ValueError('tool_arguments')
        if bool(tools)!=(finish=='tool_calls'):
            raise ValueError('finish_tool_mismatch')
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,RecursionError):
        error = 'sse_protocol_incomplete_or_invalid'
    body={'usage':usage_full if usage is not None else None,
          'actual_provider':providers[0] if len(providers)==1 else None,
          'response_model':models[0] if len(models)==1 else None,
          'provider_evidence':'response_field' if len(providers)==1 else 'unknown_or_conflicting',
          'choices':[{'finish_reason':finish if error is None else None,
            'message':{'content':''.join(text),'reasoning_content':''.join(reasoning),
                       **({'reasoning_details':details} if details else {}),
                       'tool_calls':[tools[k] for k in sorted(tools)]}}]}
    return body, usage, error


def scan_events(raw, secret):
    # 扫描每个完整event全结构，包括聚合器未使用的metadata和认证字段。
    locations=[]; changed=False
    try:
        source=raw.decode('utf-8')
        if not source.endswith(('\n\n','\r\n\r\n')):
            raise ValueError('partial_frame')
        for index,line in enumerate(source.splitlines()):
            if not line or line.startswith(':'):
                continue
            if not line.startswith('data:'):
                raise ValueError('invalid_line')
            value=line[5:].strip()
            if value=='[DONE]':
                continue
            _,redacted,found=sanitize(parse(value),[secret])
            changed=changed or redacted
            locations.extend({'location':f'event-line[{index}]'+item['location'], 'type':item['type']} for item in found)
        return ('redacted' if changed else 'safe'), locations
    except (ValueError,TypeError,UnicodeError,RecursionError):
        return 'unscannable', []


class SSEEvidenceGate:
    def __init__(self, root, secret, usage_sink, *, request_id):
        # 根须由新候选为本请求私有创建；sink绑定该已登记请求预算。
        import re
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',request_id):
            raise ValueError('invalid_evidence_request_id')
        self.request_id=request_id
        self.root, self.secret, self.usage_sink = root, secret, usage_sink
        self.result = None
        directory=_Directory(root)
        try:
            import os
            stat=os.fstat(directory.fd)
            if stat.st_mode & 0o077:
                raise ValueError('response_evidence_root_not_private')
            self.identity=(stat.st_dev,stat.st_ino)
            fd=os.open('request-binding.json',os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600,dir_fd=directory.fd)
            with os.fdopen(fd,'wb') as file:
                file.write(encode({'request_id':request_id,'root_device':stat.st_dev,'root_inode':stat.st_ino}))
                file.flush();os.fsync(file.fileno())
            os.fsync(directory.fd)
        finally:
            directory.close()

    def consume(self, chunks, *, http_status):
        # wire最多32MiB，语义正文仍4MiB；这是实体限额，不是进程RSS上限。
        directory=_Directory(self.root)
        try:
            import os
            stat=os.fstat(directory.fd)
            if (stat.st_dev,stat.st_ino)!=self.identity:
                raise ResponseEvidenceError('response_evidence_root_changed')
        finally:
            directory.close()
        parts=[]; size=0; interrupted=False; cause='none'; exception_type=None
        try:
            for chunk in chunks:
                if not isinstance(chunk,bytes):
                    interrupted=True;cause='nonbytes_chunk';break
                size += len(chunk)
                if size>MAX_WIRE_BYTES:
                    interrupted=True;cause='wire_limit'
                    break
                parts.append(chunk)
        except Exception as error:
            interrupted=True;cause='stream_exception'
            allowed={'ReadTimeout','ReadError','RemoteProtocolError','LocalProtocolError','ConnectError',
                     'WriteError','WriteTimeout','PoolTimeout','ConnectTimeout','TimeoutError','ConnectionError',
                     'BrokenPipeError','ConnectionResetError','OSError','ResponseTruncatedError'}
            name=type(error).__name__
            exception_type=name if name in allowed else 'OtherException'
        raw=b''.join(parts)
        self.diagnostics={'schema':'safe-sse-stream-diagnostics-v1','received_bytes':size,
            'retained_bytes':len(raw),'wire_limit_bytes':MAX_WIRE_BYTES,
            'semantic_limit_bytes':MAX_BYTES,'wire_limit_hit':cause=='wire_limit',
            'interruption_kind':cause,'exception_type':exception_type,'http_status':http_status}
        if http_status != 200 and not interrupted:
            self.result=capture(self.root,raw,[self.secret],self.usage_sink,http_status=http_status,expected_identity=self.identity)
            self.save_diagnostics()
            raise ResponseEvidenceError('response_evidence_http_error')
        body, usage, error=assemble(raw)
        scan,locations=scan_events(raw,self.secret)
        self.diagnostics['sse_assembly_error']=error
        self.diagnostics['event_scan']=scan
        if locations:
            body['_evidence_redactions']=locations
        if interrupted:
            body['choices'][0]['finish_reason']=None
            scan='unscannable'
        # 合法JSON中的孤立代理字符也可能无法UTF-8重编码；不丢已观察的usage。
        try:
            body_bytes=encode(body)
            self.diagnostics['semantic_serialization_error']=None
        except (UnicodeError,ValueError,TypeError,RecursionError):
            self.diagnostics['semantic_serialization_error']='semantic_json_encoding_failed'
            body={'usage':usage,'choices':[{'finish_reason':None,'message':{'content':'','tool_calls':[]}}]}
            body_bytes=encode(body);scan='unscannable'
            error='semantic_json_encoding_failed'
        self.diagnostics['assembled_json_bytes']=len(body_bytes)
        self.diagnostics['event_scan']=scan
        # exact SSE实体字节与派生聚合JSON分开保存，不假装聚合JSON是原wire。
        self.result=capture(self.root,body_bytes,[self.secret],self.usage_sink,
                            observed_usage=usage,http_status=http_status,received_entity=raw,received_entity_complete=not interrupted,received_entity_scan=scan,expected_identity=self.identity)
        self.save_diagnostics()
        if interrupted or error or not self.result['execution_allowed']:
            raise ResponseEvidenceError('response_evidence_not_ready')
        return raw.decode('utf-8').splitlines()

    def save_diagnostics(self):
        # 只保存固定枚举/数字；usage已在capture独立结算，诊断写失败仍不得执行。
        directory=check=None
        try:
            directory=_Directory(self.root);stat=os.fstat(directory.fd)
            if (stat.st_dev,stat.st_ino)!=self.identity:
                raise ValueError('diagnostics_root_changed')
            safe,_,_=sanitize(self.diagnostics,[self.secret])
            _write(directory/'stream-diagnostics.json',encode(safe))
            check=_Directory(self.root);stat=os.fstat(check.fd)
            if (stat.st_dev,stat.st_ino)!=self.identity:
                raise ValueError('diagnostics_root_changed')
        except (OSError,ValueError):
            if self.result is not None:self.result['execution_allowed']=False
            raise ResponseEvidenceError('response_diagnostics_not_saved')
        finally:
            if check is not None:check.close()
            if directory is not None:directory.close()
