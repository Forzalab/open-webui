"""
title: Mimi Image
author: tito
version: 0.1.0
description: Sửa ảnh đã gửi hoặc vẽ ảnh mới cho Mimi qua OpenRouter.
"""

import asyncio
import base64
import io
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps
from pydantic import BaseModel

API_URL = 'https://openrouter.ai/api/v1/images'

logger = logging.getLogger(__name__)

OFF_TEXT = 'Tính năng sửa ảnh đang tắt.'
NO_KEY = 'Chưa có khóa để sửa ảnh.'
NOT_ALLOWED = 'Tính năng này chưa mở cho tài khoản của bạn.'
CAP_TEXT = 'Hôm nay đã sửa đủ số ảnh rồi, mai mình làm tiếp nhé.'
NO_PHOTO = 'Mình chưa thấy ảnh nào, bạn gửi ảnh lên giúp mình nhé.'
DONE_TEXT = 'Xong rồi, ảnh đã sửa ở trên nè.'
DONE_GEN_TEXT = 'Xong rồi, ảnh ở trên nè.'
HTTP_ERROR = 'Chưa sửa được ảnh (mã {code}).'

EDIT_TEMPLATE = (
    "Edit the attached photo. This is a real personal photo of a Vietnamese woman; the result must still look like an untouched, real camera photo, ready to post on Facebook.\n"
    "Change only, all subtle and natural:\n"
    "{change}\n"
    "Also, very subtly and barely noticeably: soften only the deepest wrinkles a little and gently even out the skin.\n"
    "Keep exactly the same: her identity, ethnicity, face shape, eye shape and eyelids, eye size, nose, lips, brows, natural asymmetry, expression, clothing and accessories, the whole background, the framing and the crop. Do not add or remove anything. Keep visible pores and natural skin texture; she should look like herself on a good day, like great skincare, not a filter.\n"
    "Photo look: fix exposure the way a good modern phone would: if any part is overexposed or washed out, recover the highlights and bring exposure down only very slightly, keeping the photo bright, airy and sunny; give any sky a deeper natural blue; and make the colors vivid but true, like a good modern phone photo. Keep her skin tone warm and healthy; do not lighten, whiten or pinken her skin. No yellow cast, no haze, no beauty-filter look.\n"
    "Do not add text, logos or watermarks."
)

GEN_SUFFIX = 'Photorealistic, natural colors, like a good modern phone photo. Do not add text, logos or watermarks.'


def build_edit_prompt(change: str) -> str:
    """Locked edit prompt; the change text is inserted literally (str.replace, never .format)."""
    c = (change or '').strip()
    if not c:
        return EDIT_TEMPLATE.replace('{change}\n', '')
    return EDIT_TEMPLATE.replace('{change}\n', c + '\n')


def build_generate_prompt(description: str) -> str:
    """Locked generate prompt: the description plus a fixed photo-look suffix."""
    return (description or '').strip() + '\n' + GEN_SUFFIX


def _incident(detail: str) -> str:
    """Log one TITO-ERR line and return its code (detail: status, 'timeout', 'empty' or exception type)."""
    code = f'T{datetime.now(ZoneInfo("America/Los_Angeles")):%H%M}-{secrets.token_hex(2)}'
    logger.error('TITO-ERR %s mimi_image %s', code, detail)
    return code


def _error(shown: object, code: str) -> str:
    """User-facing error text; appends the TITO-ERR code so a parent's report can be matched to the log."""
    return HTTP_ERROR.format(code=shown) + f' (mã lỗi {code})'


def _log_call(op: str, ok: int, started: float, cost, in_bytes: int, out_bytes: int) -> None:
    """One line per finished call: op/ok/secs/cost/sizes only, never prompt, text, key or base64."""
    secs = time.monotonic() - started
    logger.info(
        '[TITO] mimi_image op=%s ok=%d secs=%.1f cost=%s in_bytes=%d out_bytes=%d',
        op, ok, secs, '-' if cost is None else cost, in_bytes, out_bytes,
    )


def _user_id(user) -> str:
    if isinstance(user, dict):
        return str(user.get('id') or '')
    return str(getattr(user, 'id', '') or '')


def _spend_key(user) -> str:
    day = datetime.now(ZoneInfo('America/Los_Angeles')).strftime('%Y-%m-%d')
    return f'{_user_id(user)}|{day}'


def _spend_path(valve_path: str) -> str:
    if valve_path and valve_path.strip():
        return valve_path.strip()
    return os.path.join(os.getenv('DATA_DIR') or '/app/backend/data', 'mimi_image_spend.json')


def _read_spend(path: str) -> dict:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _spent_for(spend: dict, key: str) -> float:
    try:
        return float(spend.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _charge(path: str, key: str, price: float) -> None:
    spend = _read_spend(path)
    spend[key] = round(_spent_for(spend, key) + price, 6)
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(spend, f)


def _decode_data_url(url) -> bytes | None:
    if not isinstance(url, str) or not url.startswith('data:') or ';base64,' not in url:
        return None
    try:
        return base64.b64decode(url.split(',', 1)[1])
    except Exception:
        return None


def _last_user_image(messages) -> bytes | None:
    """The last image part of the last user message that has one, searching from the end."""
    for msg in reversed(messages or []):
        if not isinstance(msg, dict) or msg.get('role') != 'user':
            continue
        content = msg.get('content')
        if not isinstance(content, list):
            continue
        for part in reversed(content):
            if not isinstance(part, dict) or part.get('type') != 'image_url':
                continue
            image = part.get('image_url')
            raw = _decode_data_url(image.get('url') if isinstance(image, dict) else None)
            if raw is not None:
                return raw
    return None


def _to_jpeg(raw: bytes) -> bytes:
    """EXIF-transpose, RGB, JPEG q92: what the provider receives."""
    with Image.open(io.BytesIO(raw)) as img:
        rgb = ImageOps.exif_transpose(img).convert('RGB')
        out = io.BytesIO()
        rgb.save(out, format='JPEG', quality=92)
        return out.getvalue()


def _data_url(jpeg: bytes) -> str:
    return 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode('ascii')


def _post_image(key: str, body: dict, timeout: int) -> dict:
    """POST one OpenRouter image request. Raises on HTTP/network/JSON errors."""
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            'Authorization': f'Bearer {key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _first_b64(data) -> str | None:
    try:
        item = (data.get('data') or [])[0]
        return item.get('b64_json') if isinstance(item, dict) else None
    except (AttributeError, IndexError, TypeError):
        return None


async def _emit(emitter, event: dict) -> None:
    if emitter is None:
        return
    try:
        await emitter(event)
    except Exception:
        pass


def _status(description: str, done: bool) -> dict:
    return {'type': 'status', 'data': {'description': description, 'done': done}}


async def _save_image(request, png_bytes: bytes, user, metadata) -> str:
    """Module seam: upload the PNG through Open WebUI and return its file URL."""
    from open_webui.models.users import Users
    from open_webui.routers.images import upload_image

    if isinstance(user, dict):
        user = await Users.get_user_by_id(user.get('id'))
    _file, info = await upload_image(request, png_bytes, 'image/png', metadata or {}, user)
    return info['url']


class Tools:
    class Valves(BaseModel):
        ENABLED: bool = False
        MODEL: str = 'bytedance-seed/seedream-5-0-flash-20261001'
        RESOLUTION: str = '2K'
        OPENROUTER_API_KEY: str = ''
        PRICE_PER_IMAGE_USD: float = 0.02
        DAILY_CAP_USD: float = 1.0
        ALLOWED_USER_IDS: str = ''
        SPEND_FILE: str = ''
        TIMEOUT_SECONDS: int = 120

    def __init__(self):
        self.valves = self.Valves()

    def _gate(self, op: str, user, started: float):
        if not self.valves.ENABLED:
            _log_call(op, 0, started, None, 0, 0)
            return None, OFF_TEXT
        key = (self.valves.OPENROUTER_API_KEY or '').strip() or os.getenv('TITO_DECIDE_KEY', '').strip()
        if not key:
            _log_call(op, 0, started, None, 0, 0)
            return None, NO_KEY
        allowed = [x.strip() for x in (self.valves.ALLOWED_USER_IDS or '').split(',') if x.strip()]
        if allowed and _user_id(user) not in allowed:
            _log_call(op, 0, started, None, 0, 0)
            return None, NOT_ALLOWED
        return key, None

    async def _run_http(self, op, key, prompt, input_ref, in_bytes, user, request, emitter, metadata, started):
        spend_path = _spend_path(self.valves.SPEND_FILE)
        sk = _spend_key(user)
        price = float(self.valves.PRICE_PER_IMAGE_USD)
        cap = float(self.valves.DAILY_CAP_USD)
        if _spent_for(_read_spend(spend_path), sk) + price > cap + 1e-9:
            _log_call(op, 0, started, None, in_bytes, 0)
            return CAP_TEXT

        desc = 'Mimi đang sửa hình…' if op == 'edit' else 'Mimi đang vẽ hình…'
        await _emit(emitter, _status(desc, False))
        ok, cost, out_bytes = 0, None, 0
        try:
            body = {'model': self.valves.MODEL, 'prompt': prompt, 'n': 1, 'output_format': 'png',
                    'aspect_ratio': 'auto', 'resolution': self.valves.RESOLUTION}
            if input_ref is not None:
                body['input_references'] = [{'type': 'image_url', 'image_url': {'url': input_ref}}]
            data = await asyncio.to_thread(_post_image, key, body, self.valves.TIMEOUT_SECONDS)
            usage = data.get('usage') if isinstance(data, dict) else None
            cost = usage.get('cost') if isinstance(usage, dict) else None
            b64 = _first_b64(data)
            if not b64:
                text = _error('empty', _incident('empty'))
            else:
                png = base64.b64decode(b64)
                out_bytes = len(png)
                url = await _save_image(request, png, user, metadata or {})
                _charge(spend_path, sk, price)
                ok = 1
                text = DONE_TEXT if op == 'edit' else DONE_GEN_TEXT
                await _emit(emitter, {'type': 'files', 'data': {'files': [{'type': 'image', 'url': url}]}})
        except urllib.error.HTTPError as e:
            text = _error(e.code, _incident(str(e.code)))
        except TimeoutError:
            text = _error('timeout', _incident('timeout'))
        except Exception as e:
            if isinstance(getattr(e, 'reason', None), TimeoutError):
                text = _error('timeout', _incident('timeout'))
            else:
                text = _error('mạng', _incident(type(e).__name__))
        finally:
            await _emit(emitter, _status(desc, True))
        _log_call(op, ok, started, cost, in_bytes, out_bytes)
        return text

    async def edit_image(self, change: str, __user__=None, __request__=None, __event_emitter__=None,
                         __messages__=None, __files__=None, __metadata__=None) -> str:
        """
        Sửa hoặc chỉnh ảnh mà người dùng vừa gửi kèm trong chat.

        Dùng cho MỌI yêu cầu sửa, chỉnh, làm đẹp, đổi nền hay retouch ảnh đã gửi.
        ``change`` viết bằng tiếng Anh, CHỈ nêu phần cần đổi, ngắn và cụ thể;
        không bao giờ mô tả khuôn mặt hay ngoại hình của người trong ảnh.
        """
        started = time.monotonic()
        key, refused = self._gate('edit', __user__, started)
        if refused:
            return refused
        raw = _last_user_image(__messages__)
        if raw is None:
            _log_call('edit', 0, started, None, 0, 0)
            return NO_PHOTO
        try:
            jpeg = _to_jpeg(raw)
        except Exception as e:
            _log_call('edit', 0, started, None, len(raw), 0)
            return _error('mạng', _incident(type(e).__name__))
        return await self._run_http(
            'edit', key, build_edit_prompt(change), _data_url(jpeg), len(jpeg),
            __user__, __request__, __event_emitter__, __metadata__, started,
        )

    async def generate_image(self, description: str, __user__=None, __request__=None, __event_emitter__=None,
                             __messages__=None, __files__=None, __metadata__=None) -> str:
        """
        Vẽ một ảnh mới từ mô tả của người dùng (không cần ảnh đính kèm).

        ``description`` viết bằng tiếng Anh, ngắn và cụ thể về ảnh muốn vẽ.
        """
        started = time.monotonic()
        key, refused = self._gate('generate', __user__, started)
        if refused:
            return refused
        return await self._run_http(
            'generate', key, build_generate_prompt(description), None, 0,
            __user__, __request__, __event_emitter__, __metadata__, started,
        )
