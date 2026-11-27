"""RED tests for the ``mimi_image`` Open WebUI Tool (MIMI-CAN B2).

The tool does not exist yet; it will live at ``tito-deploy/tools/mimi_image.py``.
Loading is guarded so this module always collects. Every test starts with
``_require()``, which fails (never errors at import) while the tool is missing.
``urllib.request.urlopen`` is patched, so no network is touched; ``_save_image``
is monkeypatched, so no DB or files router is needed.
"""

import asyncio
import base64
import importlib.util
import io
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

# Repo root is 4 parents up from backend/open_webui/test/tito/test_mimi_image.py.
_TOOL_PATH = Path(__file__).resolve().parents[4] / 'tito-deploy' / 'tools' / 'mimi_image.py'


def _load():
    if not _TOOL_PATH.is_file():
        return None, 'file does not exist'
    try:
        spec = importlib.util.spec_from_file_location('mimi_image', _TOOL_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod, None
    except Exception as exc:  # collection must survive a broken tool too
        return None, f'{type(exc).__name__}: {exc}'


module, _LOAD_ERROR = _load()

KEY = 'TEST-KEY-do-not-leak-7f3a'
ENV_KEY = 'ENV-KEY-do-not-leak-9c2b'
USER = {'id': 'u1'}
META = {'chat_id': 'c1', 'message_id': 'm1'}
REQ = object()
SAVED_URL = '/api/v1/files/abc/content'
PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'P' * 92  # 100 bytes: output size is easy to spot
B64 = base64.b64encode(PNG_BYTES).decode()
OFF_TEXT = 'Tính năng sửa ảnh đang tắt.'
NO_KEY = 'Chưa có khóa để sửa ảnh.'
NOT_ALLOWED = 'Tính năng này chưa mở cho tài khoản của bạn.'
CAP_TEXT = 'Hôm nay đã sửa đủ số ảnh rồi, mai mình làm tiếp nhé.'
NO_PHOTO = 'Mình chưa thấy ảnh nào, bạn gửi ảnh lên giúp mình nhé.'
DONE_TEXT = 'Xong rồi, ảnh đã sửa ở trên nè.'
DONE_GEN_TEXT = 'Xong rồi, ảnh ở trên nè.'


def _require():
    if module is None:
        pytest.fail(f'mimi_image tool not loadable at {_TOOL_PATH}: {_LOAD_ERROR}')
    return module


def _spend_key():
    return f'u1|{datetime.now(ZoneInfo("America/Los_Angeles")):%Y-%m-%d}'


def _jpeg(size=(40, 20), orientation=None, mode='RGB'):
    color = (120, 30, 30) if mode == 'RGB' else (10, 200, 10, 128)
    img = Image.new(mode, size, color)
    kwargs = {}
    if orientation is not None:
        exif = Image.Exif()
        exif[274] = orientation  # Orientation=6: rotate 90 CW
        kwargs['exif'] = exif
    buf = io.BytesIO()
    img.save(buf, format='JPEG' if mode == 'RGB' else 'PNG', **kwargs)
    return buf.getvalue()


def _url(raw, mime='image/jpeg'):
    return f'data:{mime};base64,' + base64.b64encode(raw).decode()


def _jpeg_url(size=(40, 20), orientation=None, mode='RGB'):
    return _url(_jpeg(size, orientation, mode), 'image/jpeg' if mode == 'RGB' else 'image/png')


def _msg(role, url=None):
    urls = url if isinstance(url, list) else ([url] if url else [])
    return {'role': role, 'content': [{'type': 'text', 'text': 'hi'}] + [
        {'type': 'image_url', 'image_url': {'url': u}} for u in urls]}


class _FakeResponse(io.BytesIO):
    __enter__ = lambda self: self
    __exit__ = lambda self, *exc: False


def _patch_http(monkeypatch, payload=None, error=None, trace=None):
    captured = {'calls': 0}
    def fake_urlopen(req, timeout=None):
        captured.update(calls=captured['calls'] + 1, req=req, timeout=timeout,
                        thread=threading.get_ident())
        if trace is not None:
            trace.append('http')
        if error is not None:
            raise error
        data = {'data': [{'b64_json': B64}], 'usage': {'cost': 0.018}} if payload is None else payload
        body = json.dumps(data).encode('utf-8')
        return _FakeResponse(body)
    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)
    return captured


def _no_http(monkeypatch):
    def must_not_call(req, timeout=None):
        raise AssertionError('HTTP must not be called on this path')
    monkeypatch.setattr(urllib.request, 'urlopen', must_not_call)


def _patch_save(monkeypatch):
    calls = []
    async def fake(request=None, png_bytes=None, user=None, metadata=None):
        calls.append({'request': request, 'png_bytes': png_bytes, 'user': user, 'metadata': metadata})
        return SAVED_URL
    _require()
    monkeypatch.setattr(module, '_save_image', fake, raising=False)
    return calls


def _emitter(events, trace=None):
    async def emit(event):
        events.append(event)
        if trace is not None:
            trace.append(event)
    return emit


def _tools(tmp_path, **over):
    _require()
    vals = {'ENABLED': True, 'MODEL': 'bytedance-seed/seedream-5-0-flash-20261001',
            'RESOLUTION': '2K', 'OPENROUTER_API_KEY': KEY, 'PRICE_PER_IMAGE_USD': 0.02,
            'DAILY_CAP_USD': 1.0, 'ALLOWED_USER_IDS': '', 'SPEND_FILE': str(tmp_path / 'spend.json'),
            'TIMEOUT_SECONDS': 120}
    vals.update(over)
    tools = module.Tools()
    tools.valves = module.Tools.Valves(**vals)
    return tools


def _edit(tools, change='sửa nhẹ', **kw):
    kw.setdefault('__user__', dict(USER))
    kw.setdefault('__messages__', [_msg('user', _jpeg_url())])
    return tools.edit_image(change, **kw)


def _gen(tools, text='a red bicycle', **kw):
    kw.setdefault('__user__', dict(USER))
    return tools.generate_image(text, **kw)


def _headers(req):
    return {k.lower(): v for k, v in req.header_items()}


def _body(captured):
    return json.loads(captured['req'].data.decode('utf-8'))


def _sent_image(captured):
    url = _body(captured)['input_references'][0]['image_url']['url']
    assert url.startswith('data:image/jpeg;base64,')
    raw = base64.b64decode(url.split(',', 1)[1])
    return raw, Image.open(io.BytesIO(raw))


def _user_id(user):
    return user.get('id') if isinstance(user, dict) else getattr(user, 'id', None)


def _spend(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def test_valve_defaults_are_exact():
    # SOURCE: AC valves - names and literal defaults (v3 GPT flare model/price).
    _require()
    v = module.Tools().Valves()
    assert (v.ENABLED, v.MODEL, v.QUALITY, v.COMPLEXITY, v.RESOLUTION, v.OPENROUTER_API_KEY,
            v.PRICE_PER_IMAGE_USD, v.DAILY_CAP_USD, v.ALLOWED_USER_IDS, v.SPEND_FILE,
            v.TIMEOUT_SECONDS) == (
        False, 'openai/gpt-image-2.6-flare', 'medium', 'low', '2K', '', 0.06, 1.0, '', '', 120)


def test_disabled_and_missing_key_make_no_http_call(monkeypatch, tmp_path):
    # SOURCE: AC1 + AC2 - OFF_TEXT for both methods; both keys empty -> NO_KEY.
    _require()
    _no_http(monkeypatch)
    t = _tools(tmp_path, ENABLED=False)
    assert asyncio.run(_edit(t)) == OFF_TEXT
    assert asyncio.run(_gen(t)) == OFF_TEXT
    monkeypatch.delenv('TITO_DECIDE_KEY', raising=False)
    t = _tools(tmp_path, OPENROUTER_API_KEY='')
    assert asyncio.run(_edit(t)) == NO_KEY
    assert asyncio.run(_gen(t)) == NO_KEY


def test_key_choice_and_key_never_leaks(monkeypatch, tmp_path, caplog):
    # SOURCE: AC2 - valve key > env TITO_DECIDE_KEY; key never in logs or returns.
    _require()
    caplog.set_level(logging.INFO)
    monkeypatch.setenv('TITO_DECIDE_KEY', ENV_KEY)
    captured = _patch_http(monkeypatch)
    _patch_save(monkeypatch)
    assert asyncio.run(_gen(_tools(tmp_path, OPENROUTER_API_KEY=''))) == DONE_GEN_TEXT
    assert _headers(captured['req'])['authorization'] == f'Bearer {ENV_KEY}'
    captured = _patch_http(monkeypatch)
    assert asyncio.run(_gen(_tools(tmp_path))) == DONE_GEN_TEXT
    assert _headers(captured['req'])['authorization'] == f'Bearer {KEY}'
    assert KEY not in asyncio.run(_gen(_tools(tmp_path)))
    err = urllib.error.HTTPError(module.API_URL, 500, 'Boom', {}, io.BytesIO(KEY.encode()))
    _patch_http(monkeypatch, error=err)
    out = asyncio.run(_gen(_tools(tmp_path)))
    assert KEY not in out and KEY not in caplog.text


def test_allowlist_blocks_u3_and_lets_u1_through(monkeypatch, tmp_path):
    # SOURCE: AC3 - ALLOWED_USER_IDS="u1,u2": u3 -> NOT_ALLOWED, u1 passes.
    _require()
    _no_http(monkeypatch)
    t = _tools(tmp_path, ALLOWED_USER_IDS='u1,u2')
    assert asyncio.run(_edit(t, __user__={'id': 'u3'})) == NOT_ALLOWED
    assert asyncio.run(_edit(t, __user__={'id': 'u1'}, __messages__=[])) == NO_PHOTO
    captured = _patch_http(monkeypatch)
    _patch_save(monkeypatch)
    assert asyncio.run(_edit(t)) == DONE_TEXT
    assert captured['calls'] == 1


def test_cap_charges_only_success_and_fails_open(monkeypatch, tmp_path):
    # SOURCE: AC4 - cap .05/price .02: two succeed, third refused; corrupt file = 0;
    # failure never charges; a later success overwrites the corrupt file cleanly.
    _require()
    spend_file = tmp_path / 'spend.json'
    spend_file.write_text('{not json', encoding='utf-8')
    captured = _patch_http(monkeypatch)
    _patch_save(monkeypatch)
    t = _tools(tmp_path, DAILY_CAP_USD=0.05)
    assert asyncio.run(_edit(t)) == DONE_TEXT
    assert _spend(spend_file) == pytest.approx({_spend_key(): 0.02})
    assert asyncio.run(_edit(t)) == DONE_TEXT
    assert _spend(spend_file) == pytest.approx({_spend_key(): 0.04})
    assert asyncio.run(_edit(t)) == CAP_TEXT
    assert captured['calls'] == 2
    err = urllib.error.HTTPError(module.API_URL, 500, 'Boom', {}, io.BytesIO(b''))
    _patch_http(monkeypatch, error=err)
    t2 = _tools(tmp_path)  # cap 1.0, so this reaches HTTP and must not charge
    assert asyncio.run(_edit(t2)).startswith('Chưa sửa được ảnh (mã 500).')
    assert _spend(spend_file) == pytest.approx({_spend_key(): 0.04})
    # SOURCE: AC4 - SPEND_FILE empty -> <DATA_DIR>/mimi_image_spend.json.
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    monkeypatch.setenv('DATA_DIR', str(data_dir))
    _patch_http(monkeypatch)
    assert asyncio.run(_edit(_tools(tmp_path, SPEND_FILE=''))) == DONE_TEXT
    assert _spend(data_dir / 'mimi_image_spend.json') == pytest.approx({_spend_key(): 0.02})


def test_last_user_image_wins_and_missing_photo_refused(monkeypatch, tmp_path):
    # SOURCE: AC5 - search from the end for the last user image; assistant image ignored.
    _require()
    captured = _patch_http(monkeypatch)
    _patch_save(monkeypatch)
    msgs = [_msg('user', _jpeg_url((40, 20))), _msg('assistant', None),
            _msg('user', [_jpeg_url((60, 30)), _jpeg_url((80, 40))]),
            _msg('assistant', _jpeg_url((10, 10)))]
    assert asyncio.run(_edit(_tools(tmp_path), __messages__=msgs)) == DONE_TEXT
    _, img = _sent_image(captured)
    assert img.size == (80, 40)
    _no_http(monkeypatch)
    for msgs in ([_msg('user', None), _msg('assistant', _jpeg_url())], []):
        assert asyncio.run(_edit(_tools(tmp_path), __messages__=msgs)) == NO_PHOTO


def test_exif_transposed_and_rgb_jpeg_reencoded(monkeypatch, tmp_path):
    # SOURCE: AC6 - 40x20 with Orientation=6 sent as 20x40 RGB JPEG.
    _require()
    captured = _patch_http(monkeypatch)
    _patch_save(monkeypatch)
    raw = _jpeg((40, 20), orientation=6)
    assert asyncio.run(_edit(_tools(tmp_path), __messages__=[_msg('user', _url(raw))])) == DONE_TEXT
    sent, img = _sent_image(captured)
    assert (img.width, img.height) == (20, 40) and img.mode == 'RGB' and sent != raw


def test_requests_are_exact_and_run_off_the_loop_thread(monkeypatch, tmp_path):
    # SOURCE: AC7 + AC13 - one POST, URL/headers/body/timeout from valves, worker thread.
    _require()
    main_tid = threading.get_ident()
    captured = _patch_http(monkeypatch)
    _patch_save(monkeypatch)
    t = _tools(tmp_path, TIMEOUT_SECONDS=7)
    assert asyncio.run(_edit(t, 'replace the sky with sunset', kind='other', __request__=REQ)) == DONE_TEXT
    assert captured['calls'] == 1 and captured['timeout'] == 7
    assert captured['thread'] != main_tid
    req = captured['req']
    assert module.API_URL == 'https://openrouter.ai/api/v1/images'
    assert req.full_url == module.API_URL and req.get_method() == 'POST'
    assert (_headers(req)['authorization'], _headers(req)['content-type']) == (f'Bearer {KEY}', 'application/json')
    body = _body(captured)
    assert set(body) == {'model', 'prompt', 'n', 'output_format', 'aspect_ratio',
                         'resolution', 'input_references'}
    assert body['model'] == 'bytedance-seed/seedream-5-0-flash-20261001'
    assert body['prompt'] == module.build_neutral_prompt([], 'replace the sky with sunset')
    assert (body['n'], body['output_format'], body['aspect_ratio'], body['resolution']) == (1, 'png', 'auto', '2K')
    ref = body['input_references'][0]
    assert set(ref) == {'type', 'image_url'} and ref['type'] == 'image_url'
    assert ref['image_url']['url'].startswith('data:image/jpeg;base64,')
    captured = _patch_http(monkeypatch)
    assert asyncio.run(_gen(t, 'a cat on a roof')) == DONE_GEN_TEXT
    body = _body(captured)
    assert set(body) == {'model', 'prompt', 'n', 'output_format', 'aspect_ratio', 'resolution'}
    assert body['prompt'] == module.build_generate_prompt('a cat on a roof')


def test_prompt_builders_are_locked():
    # SOURCE: AC8 v3 - short positive edit template; empty change drops the Change line.
    _require()
    change = 'replace the background with a beach'
    p = module.build_edit_prompt(change)
    assert p.startswith('Edit this real photo so it still looks like an unedited camera photo.')
    assert p.endswith('OUTPUT: a realistic photograph, true-to-life phone-camera look.')
    assert p.count('Change only: ' + change) == 1
    for fact in ('Keep everything else exactly as photographed', 'same person, same face',
                 'same background, same framing', 'same colors and light'):
        assert fact in p
    for empty in ('', '   '):
        q = module.build_edit_prompt(empty)
        assert 'Change only:' not in q
        for bad in ('do not', "don't", 'never', ' no ', 'not ', 'avoid', 'without'):
            assert bad not in q.lower(), bad
    assert module.build_generate_prompt('a cat') == (
        'a cat\nPhotorealistic, natural colors, like a good modern phone photo.')


def test_gpt_default_and_body(monkeypatch, tmp_path):
    # SOURCE: v0.3 - default MODEL is the GPT flare; GPT bodies carry quality/size/aspect
    # plus provider complexity from the valves; generate has no input and is 1:1/1024.
    _require()
    v = module.Tools.Valves()
    assert (v.MODEL, v.QUALITY, v.COMPLEXITY) == ('openai/gpt-image-2.6-flare', 'medium', 'low')
    captured = _patch_http(monkeypatch)
    _patch_save(monkeypatch)
    t = _tools(tmp_path, MODEL='openai/gpt-image-2.6-flare')
    assert asyncio.run(_edit(t, __messages__=[_msg('user', _jpeg_url((60, 40)))])) == DONE_TEXT
    body = _body(captured)
    assert set(body) == {'model', 'prompt', 'n', 'output_format', 'aspect_ratio',
                         'size', 'quality', 'provider', 'input_references'}
    assert (body['model'], body['n'], body['output_format']) == ('openai/gpt-image-2.6-flare', 1, 'png')
    assert (body['aspect_ratio'], body['size']) == ('3:2', '1536x1024')
    assert (body['quality'], body['provider']) == (
        'medium', {'options': {'openai': {'complexity': 'low'}}})
    assert body['prompt'] == module.build_beauty_prompt('', 'sửa nhẹ')
    captured = _patch_http(monkeypatch)
    t = _tools(tmp_path, MODEL='openai/gpt-image-2.6-flare', QUALITY='high', COMPLEXITY='high')
    assert asyncio.run(_gen(t, 'a cat')) == DONE_GEN_TEXT
    body = _body(captured)
    assert set(body) == {'model', 'prompt', 'n', 'output_format', 'aspect_ratio', 'size',
                         'quality', 'provider'}
    assert (body['aspect_ratio'], body['size']) == ('1:1', '1024x1024')
    assert (body['quality'], body['provider']['options']['openai']['complexity']) == ('high', 'high')
    assert body['prompt'] == module.build_generate_prompt('a cat')


def test_gpt_size_picks_closest_ratio():
    # SOURCE: v0.3 - square, 9:16 portrait and 16:9 landscape map to the GPT sizes.
    _require()
    assert module._gpt_size(1024, 1024) == ('1:1', '1024x1024')
    assert module._gpt_size(1080, 1920) == ('2:3', '1024x1536')
    assert module._gpt_size(1920, 1080) == ('3:2', '1536x1024')


def test_beauty_prompt_has_face_and_locked_base():
    # SOURCE: v0.3 - face text lands literally after the label; empty face drops the
    # whole HER FACE paragraph and its blank line; locked base text remains intact.
    _require()
    face = 'an oval face, wide cheekbones, a low nose bridge, full lips'
    p = module.build_beauty_prompt(face, '')
    assert p.startswith('You are a senior studio portrait retoucher')
    assert 'HER FACE, AS PHOTOGRAPHED (the reference for the locked base): ' + face + '\n\n' in p
    assert 'THE LOCKED BASE (everything here stays as photographed' in p
    assert p.endswith('OUTPUT: a realistic photograph with the original colors, contrast and '
                      'sharpness, a true-to-life phone-camera look.\n')
    assert '\n\n\n' not in p
    q = module.build_beauty_prompt('', '')
    assert 'HER FACE' not in q and 'oval, softly square face' not in q
    assert 'THE LOCKED BASE' in q and '\n\n\n' not in q


def test_beauty_prompt_change_before_output_braces_literal():
    # SOURCE: v0.3 - change paragraph goes right before OUTPUT; braces/% survive
    # (str.replace, never .format); blank change adds no request paragraph.
    _require()
    face = 'face with {braces} and %s'
    change = 'make {the} eyes brighter, keep %(x)s'
    p = module.build_beauty_prompt(face, change)
    assert p.count(face) == 1 and p.count(change) == 1
    ask = ('HER OWN REQUEST, done in full on top of the retouch; for the parts it names '
           'it takes priority over the locked base, everything else as above: ') + change
    assert ask + '\n\nOUTPUT: ' in p
    assert p.index('THE RETOUCH') < p.index(ask) < p.index('OUTPUT:')
    q = module.build_beauty_prompt(face, '   ')
    assert 'HER OWN REQUEST' not in q and face in q


def test_edit_image_kind_and_face_dispatch(monkeypatch, tmp_path):
    # SOURCE: v0.3 - kind 'other' -> short template (face ignored); unknown/blank -> beauty;
    # default kind is beauty; the docstring tells Mimi the new contract.
    _require()
    captured = _patch_http(monkeypatch)
    _patch_save(monkeypatch)
    t = _tools(tmp_path)  # non-openai on purpose: prompt dispatch is model-independent
    msgs = [_msg('user', _jpeg_url())]
    assert asyncio.run(t.edit_image('swap the shirt color', kind='other', face='ignored',
                                    __user__=dict(USER), __messages__=msgs)) == DONE_TEXT
    assert _body(captured)['prompt'] == module.build_neutral_prompt([], 'swap the shirt color')
    for kind in (' xyz ', ''):
        captured = _patch_http(monkeypatch)
        assert asyncio.run(t.edit_image('smooth the skin', kind=kind, face='her face',
                                        __user__=dict(USER), __messages__=msgs)) == DONE_TEXT
        assert _body(captured)['prompt'] == module.build_beauty_prompt('her face', 'smooth the skin')
    captured = _patch_http(monkeypatch)
    assert asyncio.run(t.edit_image(face='her face', __user__=dict(USER),
                                    __messages__=msgs)) == DONE_TEXT
    assert _body(captured)['prompt'] == module.build_beauty_prompt('her face', '')
    doc = module.Tools.edit_image.__doc__
    for fact in ('Dùng cho MỌI yêu cầu sửa ảnh đã gửi', 'một hoặc hai mã', 'Mặc định "beauty"',
                 'other = ảnh KHÔNG cần làm đẹp người', 'clothes/object/arm',
                 'Nếu họ NÓI muốn ốm hơn', 'chỉ khi làm đẹp người',
                 'the black bag strap across her chest'):
        assert fact in doc, fact
    assert len(doc.strip().splitlines()) <= 25
    assert 'không bao giờ mô tả khuôn mặt' not in doc


def test_non_openai_model_keeps_old_body(monkeypatch, tmp_path):
    # SOURCE: v0.3 - MODEL valve without the openai/ prefix keeps the v2 body exactly
    # (aspect 'auto' + resolution), so rollback is a one-valve change.
    _require()
    captured = _patch_http(monkeypatch)
    _patch_save(monkeypatch)
    t = _tools(tmp_path, MODEL='bytedance-seed/seedream-5-0-flash-20261001')
    assert asyncio.run(_edit(t, 'change it')) == DONE_TEXT
    body = _body(captured)
    assert set(body) == {'model', 'prompt', 'n', 'output_format', 'aspect_ratio',
                         'resolution', 'input_references'}
    assert (body['model'], body['aspect_ratio'], body['resolution']) == (
        'bytedance-seed/seedream-5-0-flash-20261001', 'auto', '2K')
    for absent in ('size', 'quality', 'provider'):
        assert absent not in body


def test_success_saves_png_emits_file_and_returns_done(monkeypatch, tmp_path):
    # SOURCE: AC9 - decode b64, call _save_image seam, emit files event, no b64 anywhere.
    _require()
    _patch_http(monkeypatch)
    saves = _patch_save(monkeypatch)
    events = []
    out = asyncio.run(_edit(_tools(tmp_path), __request__=REQ,
                            __event_emitter__=_emitter(events), __metadata__=dict(META)))
    assert out == DONE_TEXT and len(saves) == 1
    assert saves[0]['request'] is REQ and saves[0]['png_bytes'] == PNG_BYTES
    assert saves[0]['metadata'] == META and _user_id(saves[0]['user']) == 'u1'
    files_event = {'type': 'files', 'data': {'files': [{'type': 'image', 'url': SAVED_URL}]}}
    assert [e for e in events if e['type'] == 'files'] == [files_event]
    assert B64 not in out and B64 not in json.dumps(events)
    saves, events = _patch_save(monkeypatch), []
    out = asyncio.run(_gen(_tools(tmp_path), __request__=REQ, __event_emitter__=_emitter(events)))
    assert out == DONE_GEN_TEXT and saves[0]['png_bytes'] == PNG_BYTES
    assert [e for e in events if e['type'] == 'files'] == [files_event]
    assert B64 not in out and B64 not in json.dumps(events)


def test_status_events_bookend_http_and_done_on_failure(monkeypatch, tmp_path):
    # SOURCE: AC10 - done=False before HTTP, done=True after success/failure; None emitter safe.
    _require()
    trace, events = [], []
    _patch_http(monkeypatch, trace=trace)
    _patch_save(monkeypatch)
    assert asyncio.run(_edit(_tools(tmp_path), __event_emitter__=_emitter(events, trace))) == DONE_TEXT
    statuses = [e for e in events if e['type'] == 'status']
    first = {'type': 'status', 'data': {'description': 'Mimi đang sửa hình…', 'done': False}}
    last = {'type': 'status', 'data': {'description': 'Mimi đang sửa hình…', 'done': True}}
    assert statuses[0] == first and statuses[-1] == last
    assert trace.index(first) < trace.index('http') < trace.index(last)
    trace, events = [], []
    _patch_http(monkeypatch, trace=trace)
    assert asyncio.run(_gen(_tools(tmp_path), __event_emitter__=_emitter(events, trace))) == DONE_GEN_TEXT
    gen = [e for e in events if e['type'] == 'status']
    assert gen[0]['data'] == {'description': 'Mimi đang vẽ hình…', 'done': False}
    assert gen[-1]['data'] == {'description': 'Mimi đang vẽ hình…', 'done': True}
    err = urllib.error.HTTPError(module.API_URL, 500, 'Boom', {}, io.BytesIO(b''))
    _patch_http(monkeypatch, error=err)
    events = []
    asyncio.run(_edit(_tools(tmp_path), __event_emitter__=_emitter(events)))
    assert [e for e in events if e['type'] == 'status'][-1]['data']['done'] is True
    _patch_http(monkeypatch)
    assert asyncio.run(_edit(_tools(tmp_path), __event_emitter__=None)) == DONE_TEXT


def test_errors_use_status_codes_and_incident_logs_body_never_shows_it(monkeypatch, tmp_path, caplog):
    # SOURCE: AC11 + v0.4.1 SPEC 4 - 403 -> code+incident; timeout; empty; the body is
    # logged for debugging but never shown to the user.
    _require()
    _patch_save(monkeypatch)
    err = urllib.error.HTTPError(module.API_URL, 403, 'Forbidden', {},
                                 io.BytesIO(b'PROVIDER-ERR-BODY'))
    _patch_http(monkeypatch, error=err)
    with caplog.at_level(logging.INFO):
        out = asyncio.run(_edit(_tools(tmp_path)))
    assert re.fullmatch(r'Chưa sửa được ảnh \(mã 403\)\. \(mã lỗi T\d{4}-[0-9a-f]{4}\)', out)
    assert re.search(r'TITO-ERR T\d{4}-[0-9a-f]{4} mimi_image 403', caplog.text)
    assert 'PROVIDER-ERR-BODY' not in out and 'PROVIDER-ERR-BODY' in caplog.text
    _patch_http(monkeypatch, error=TimeoutError())
    with caplog.at_level(logging.INFO):
        out = asyncio.run(_edit(_tools(tmp_path)))
    assert re.fullmatch(r'Chưa sửa được ảnh \(mã timeout\)\. \(mã lỗi T\d{4}-[0-9a-f]{4}\)', out)
    assert re.search(r'TITO-ERR T\d{4}-[0-9a-f]{4} mimi_image timeout', caplog.text)
    _patch_http(monkeypatch, payload={'data': [], 'usage': {'cost': 0.0}})
    with caplog.at_level(logging.INFO):
        out = asyncio.run(_gen(_tools(tmp_path)))
    assert re.fullmatch(r'Chưa sửa được ảnh \(mã empty\)\. \(mã lỗi T\d{4}-[0-9a-f]{4}\)', out)
    assert re.search(r'TITO-ERR T\d{4}-[0-9a-f]{4} mimi_image empty', caplog.text)


def test_log_lines_have_cost_sizes_and_no_private_text(monkeypatch, tmp_path, caplog):
    # SOURCE: AC12 - one line: op/ok/secs/cost + byte sizes; never change/prompt/key/base64.
    _require()
    _patch_http(monkeypatch)
    _patch_save(monkeypatch)
    with caplog.at_level(logging.INFO):
        assert asyncio.run(_edit(_tools(tmp_path), 'PRIVCHANGE-xyz')) == DONE_TEXT
    lines = [r.getMessage() for r in caplog.records if '[TITO] mimi_image' in r.getMessage()]
    assert len(lines) == 1
    assert re.match(r'^\[TITO\] mimi_image op=edit ok=1 secs=\d+\.\d cost=0\.018(?:\s|$)', lines[0])
    assert re.search(r'\b[a-z_]*in[a-z_]*=\d+', lines[0])
    assert re.search(r'\b[a-z_]*out[a-z_]*=100(?:\s|$)', lines[0])
    assert 'PRIVCHANGE' not in caplog.text and B64 not in caplog.text
    caplog.clear()
    err = urllib.error.HTTPError(module.API_URL, 500, 'Boom', {}, io.BytesIO(b''))
    _patch_http(monkeypatch, error=err)
    with caplog.at_level(logging.INFO):
        asyncio.run(_edit(_tools(tmp_path)))
    lines = [r.getMessage() for r in caplog.records if '[TITO] mimi_image' in r.getMessage()]
    assert len(lines) == 1
    assert re.match(r'^\[TITO\] mimi_image op=edit ok=0 secs=\d+\.\d cost=-(?:\s|$)', lines[0])
    caplog.clear()
    _patch_http(monkeypatch)
    with caplog.at_level(logging.INFO):
        asyncio.run(_gen(_tools(tmp_path)))
    lines = [r.getMessage() for r in caplog.records if '[TITO] mimi_image' in r.getMessage()]
    assert len(lines) == 1
    assert re.match(r'^\[TITO\] mimi_image op=generate ok=1 secs=\d+\.\d cost=0\.018(?:\s|$)',
                    lines[0])


def _png_with_cabx():
    """Small RGB PNG with a fake 'caBX' chunk (payload 'openai c2pa') spliced after IHDR."""
    buf = io.BytesIO()
    Image.new('RGB', (8, 6), (10, 20, 30)).save(buf, format='PNG')
    png = buf.getvalue()
    payload = b'openai c2pa'
    crc = zlib.crc32(b'caBX' + payload) & 0xFFFFFFFF
    chunk = len(payload).to_bytes(4, 'big') + b'caBX' + payload + crc.to_bytes(4, 'big')
    ihdr_end = 8 + 4 + 4 + 13 + 4  # signature + IHDR length/type/13-byte data/CRC
    return png[:ihdr_end] + chunk + png[ihdr_end:]


def test_strip_metadata_drops_cabx_chunk_and_keeps_size():
    # SOURCE: SPEC 1+3 - the spliced caBX chunk (with 'openai') is gone after strip;
    # the output still decodes as a PNG of the same size.
    _require()
    raw = _png_with_cabx()
    assert b'caBX' in raw and b'openai' in raw
    out = module._strip_metadata(raw)
    assert b'caBX' not in out and b'openai' not in out
    with Image.open(io.BytesIO(raw)) as before, Image.open(io.BytesIO(out)) as after:
        assert after.size == before.size


def test_strip_metadata_garbage_returns_original_and_warns(caplog):
    # SOURCE: SPEC 1+3 - unreadable bytes come back unchanged; one warning names the
    # exception type and never the image bytes.
    _require()
    junk = b'not a png openai c2pa'
    with caplog.at_level(logging.WARNING):
        assert module._strip_metadata(junk) == junk
    assert 'mimi_image strip failed ' in caplog.text
    assert 'openai' not in caplog.text


# --- v0.4.0: locked edit recipes -------------------------------------------------


def _prompt(monkeypatch, tmp_path, **kw):
    """Run one edit_image call and return the prompt the provider would receive."""
    t = _tools(tmp_path)
    captured = _patch_http(monkeypatch)
    _patch_save(monkeypatch)
    assert asyncio.run(_edit(t, **kw)) == DONE_TEXT
    return _body(captured)['prompt']


def test_kind_parse_keeps_order_dedupes_and_caps_recipes():
    # SOURCE: v0.4 SPEC 3 - comma string, strip/lower, drop empty and unknown keys,
    # keep order, dedupe, at most two recipe keys; no valid key -> beauty.
    _require()
    assert module.parse_kind('dim,clothes') == ['dim', 'clothes']
    assert module.parse_kind(' dim , zzz , HAZE , cast ') == ['dim', 'haze']
    assert module.parse_kind('dim,dim,haze') == ['dim', 'haze']
    assert module.parse_kind('other,dim,haze,cast') == ['other', 'dim', 'haze']
    assert module.parse_kind('beauty,other') == ['beauty', 'other']
    for blank in ('', '   ', 'zzz', None):
        assert module.parse_kind(blank) == ['beauty']


def test_beauty_with_recipes_inserts_6b_before_final_check(monkeypatch, tmp_path):
    # SOURCE: v0.4 SPEC 3 - kind="dim,clothes" stays on prompt S; block 6b sits right
    # before step 7, one bullet per recipe in order, THE LOCKED BASE untouched.
    _require()
    p = _prompt(monkeypatch, tmp_path, change='', kind='dim,clothes', face='her face')
    assert 'THE LOCKED BASE' in p
    assert '6b.' in p
    assert module.RECIPES['dim'] in p and module.RECIPES['clothes'] in p
    block = ('6b. Also, as part of this same retouch (for this item only, it takes priority '
             'over the locked base):\n- ' + module.RECIPES['dim'] + '\n- '
             + module.RECIPES['clothes'] + '\n')
    assert block in p
    assert p.index(block) < p.index('7. Final check')
    assert p.count('7. Final check') == 1
    assert p.index(module.RECIPES['dim']) < p.index(module.RECIPES['clothes'])
    assert 'HER FACE, AS PHOTOGRAPHED (the reference for the locked base): her face' in p


def test_other_recipe_uses_neutral_frame(monkeypatch, tmp_path):
    # SOURCE: v0.4 SPEC 3+4 - "other,haze" -> wrapper frame with a numbered fix and the
    # KEEP, edge for edge list; prompt S and its locked base must not appear.
    _require()
    p = _prompt(monkeypatch, tmp_path, change='', kind='other,haze')
    assert p.startswith('You are a senior photo retoucher working on a real family photo.')
    assert 'THE FIX:\n1. ' + module.RECIPES['haze'] + '\n\nKEEP, edge for edge' in p
    assert 'THE LOCKED BASE' not in p and '6b.' not in p and 'HER OWN REQUEST' not in p
    assert p.endswith('OUTPUT: a realistic photograph with real texture and true-to-life '
                      'phone-camera colors, no glamorization.\n')
    q = _prompt(monkeypatch, tmp_path, change='', kind='other')
    assert ('THE FIX:\nKeep the photo as it is, with a light natural clean-up of exposure '
            'and color.\n\nKEEP, edge for edge') in q
    assert 'THEIR OWN REQUEST' not in q


def test_unknown_extra_kind_keys_use_only_the_first_two_recipes(monkeypatch, tmp_path):
    # SOURCE: v0.4 SPEC 3 - "dim,zzz,haze,cast": the unknown key is dropped and cast is a
    # third recipe, so only dim and haze survive, in that order.
    _require()
    p = _prompt(monkeypatch, tmp_path, change='', kind='dim,zzz,haze,cast')
    assert module.RECIPES['dim'] in p and module.RECIPES['haze'] in p
    assert module.RECIPES['cast'] not in p
    assert p.index(module.RECIPES['dim']) < p.index(module.RECIPES['haze'])


def test_change_text_with_braces_and_percent_survives_on_both_paths(monkeypatch, tmp_path):
    # SOURCE: v0.4 SPEC 3 - str.replace only, never .format: {braces}, %(x)s, 100% and
    # bracket placeholders must reach the prompt untouched on beauty and neutral paths.
    _require()
    change = 'remove {the} strap, keep %(x)s 100% and [the] wall'
    p = _prompt(monkeypatch, tmp_path, change=change, kind='beauty,object', face='a face with {curly}')
    assert 'a face with {curly}' in p
    assert ('HER OWN REQUEST, done in full on top of the retouch; for the parts it names '
            'it takes priority over the locked base, everything else as above: ') + change in p
    assert module.RECIPES['object'] in p
    q = _prompt(monkeypatch, tmp_path, change=change, kind='other,object')
    assert ('THEIR OWN REQUEST, done in full; for the parts it names it takes priority over '
            'the KEEP list: ') + change in q
    assert module.RECIPES['object'] in q


def test_default_kind_is_v03_beauty_output_without_recipe_block(monkeypatch, tmp_path):
    # SOURCE: v0.4 SPEC 3 - no kind, or only beauty/unknown keys, is exactly the v0.3
    # beauty prompt with no 6b block.
    _require()
    expected = module.build_beauty_prompt('her face', 'smooth the skin')
    for kind in ('beauty', 'beauty,zzz', '', 'nope'):
        p = _prompt(monkeypatch, tmp_path, change='smooth the skin', face='her face', kind=kind)
        assert p == expected
        assert '6b.' not in p


def test_explicit_ask_beats_locked_base_on_beauty_path(monkeypatch, tmp_path):
    # SOURCE: v0.4.0 follow-up "their photo, their choice" - an explicit ask is written
    # through verbatim; the request paragraph says it outranks the locked base. No recipes,
    # so the phrase can only come from that paragraph, not the 6b block.
    _require()
    change = 'slim the waist a little'
    p = _prompt(monkeypatch, tmp_path, change=change, kind='beauty', face='her face')
    assert '6b.' not in p
    assert 'takes priority over the locked base' in p
    assert change in p
    assert ('HER OWN REQUEST, done in full on top of the retouch; for the parts it names '
            'it takes priority over the locked base, everything else as above: ') + change in p


# --- v0.4.1: wait ticks + error body log ------------------------------------------


def test_wait_ticker_emits_working_statuses_then_done(monkeypatch, tmp_path):
    # SOURCE: v0.4.1 SPEC 1+2 - while the slow HTTP call runs, a ticker emits
    # done=False wait statuses every TICK_SECONDS; the last status is done=True.
    _require()
    assert 'version: 0.4.1' in (module.__doc__ or '')
    assert '"- ' not in (module.Tools.edit_image.__doc__ or '')
    _patch_save(monkeypatch)

    def slow_post(key, body, timeout):
        time.sleep(0.25)
        return {'data': [{'b64_json': B64}], 'usage': {'cost': 0.018}}

    monkeypatch.setattr(module, '_post_image', slow_post)
    monkeypatch.setattr(module, 'TICK_SECONDS', 0.05)
    t = _tools(tmp_path)
    cases = (
        (lambda em: _edit(t, __event_emitter__=em),
         'Mimi vẫn đang sửa hình, chờ Mimi chút nha…'),
        (lambda em: _gen(t, __event_emitter__=em),
         'Mimi vẫn đang vẽ hình, chờ Mimi chút nha…'),
    )
    for run, phrase in cases:
        events = []
        assert asyncio.run(run(_emitter(events))) in (DONE_TEXT, DONE_GEN_TEXT)
        statuses = [e for e in events if e['type'] == 'status']
        waits = [e for e in statuses if 'vẫn đang' in e['data']['description']]
        assert len(waits) >= 2
        assert all(e['data']['done'] is False for e in waits)
        assert all(re.fullmatch(re.escape(phrase) + r' \(\d+ giây\)', e['data']['description'])
                   for e in waits)
        assert statuses[0]['data']['done'] is False
        assert statuses[-1]['data']['done'] is True
        assert statuses[-1]['data']['description'] != phrase
        assert len(waits) == len(statuses) - 2  # start, wait ticks, done


def test_http_error_logs_json_message_or_raw_body_never_user_text(monkeypatch, tmp_path, caplog):
    # SOURCE: v0.4.1 SPEC 4 - HTTPError logs the first 200 chars of error.message
    # (JSON) or of the raw body; the user text is unchanged and never carries it.
    _require()
    msg = 'quota exceeded for openai/gpt-image; retry later'
    err = urllib.error.HTTPError(
        module.API_URL, 429, 'Too Many Requests', {},
        io.BytesIO(json.dumps({'error': {'message': msg}}).encode()),
    )
    _patch_http(monkeypatch, error=err)
    with caplog.at_level(logging.ERROR):
        out = asyncio.run(_edit(_tools(tmp_path)))
    assert msg in caplog.text and msg not in out
    assert re.fullmatch(r'Chưa sửa được ảnh \(mã 429\)\. \(mã lỗi T\d{4}-[0-9a-f]{4}\)', out)
    assert KEY not in caplog.text
    caplog.clear()
    raw = b'UPSTREAM-RAW-ERROR ' + b'x' * 400
    err = urllib.error.HTTPError(module.API_URL, 502, 'Bad Gateway', {}, io.BytesIO(raw))
    _patch_http(monkeypatch, error=err)
    with caplog.at_level(logging.ERROR):
        out = asyncio.run(_gen(_tools(tmp_path)))
    assert raw[:200].decode() in caplog.text
    assert 'x' * 201 not in caplog.text
    assert 'UPSTREAM-RAW-ERROR' not in out

