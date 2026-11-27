"""
title: Mimi Image
author: tito
version: 0.3.0
description: Sửa ảnh đã gửi hoặc vẽ ảnh mới qua OpenRouter (Mimi + Tito).
"""

import asyncio
import base64
import io
import json
import logging
import math
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
    "Edit this real photo so it still looks like an unedited camera photo.\n"
    "Change only: {change}\n"
    "Keep everything else exactly as photographed: same person, same face, same expression, "
    "same pose, same clothes, same background, same framing, same colors and light.\n"
    "OUTPUT: a realistic photograph, true-to-life phone-camera look."
)

GEN_SUFFIX = 'Photorealistic, natural colors, like a good modern phone photo.'

_BEAUTY_FACE_LABEL = "HER FACE, AS PHOTOGRAPHED (the reference for the locked base): "

BEAUTY_FACE = (
    "an oval, softly square face with wide cheekbones and a soft jaw; a high smooth forehead with a center-parted hairline; medium-thick dark eyebrows in a low soft arch, sitting close to the eyes; almond-shaped eyes with partly hooded upper lids, a low crease and dark-brown irises; a low-to-medium nose bridge with a wide base and a rounded tip; full cheeks that rise with her smile, with clear smile lines from nose to mouth corners; medium-full lips with a thinner upper lip in a warm coral-rose; medium warm golden-olive skin with scattered sunspots on cheeks and nose and visible pores."
)

BEAUTY_TEMPLATE = (
    "You are a senior studio portrait retoucher working on a real family photo of a Vietnamese woman. The job is a light, invisible retouch, the kind a magazine retoucher finishes in fifteen minutes on a good photo: the result reads as the same camera photo, taken on a day when she slept well and wore a little everyday makeup. Her own family will look at it, so she stays exactly the woman they know.\n"
    "\n"
    + _BEAUTY_FACE_LABEL
    + BEAUTY_FACE
    + "\n"
    "\n"
    "THE LOCKED BASE (everything here stays as photographed, lined up edge for edge with the original):\n"
    "- Face geometry: the outline of her face; the width of her cheekbones and of her jaw; the length of her face; her chin; the width, bridge, tip and nostrils of her nose; the shape of her eyes; her eyelids and their creases; the distance between her eyes; the shape and fullness of her lips, her cupid's bow and the width of her mouth; her smile and teeth; her ears; every proportion between these features; and the natural asymmetry of her face, one side slightly different from the other, exactly as it is.\n"
    "- Character: her real age; her expression; the smile lines that come with her smile and the small lines at the corners of her eyes, present and a little softer; her moles, freckles, freckle clusters, sunspots, scars and beauty marks, the same count, each in its own place and size relative to her eyes and nose.\n"
    "- Eyebrows: dark, full and bold, in their own shape, thickness and position.\n"
    "- Surface and color: her own warm golden-olive skin tone, a touch more luminous and within half a shade of the photo, matching across face, neck, arms and hands; visible pores; fine natural texture; her own eye color; her own eyebrow color; the natural color of her cheeks.\n"
    "- Everything else: hair length, parting, volume and loose strands; pose and hands; clothing; everything she wears on her face or head, exactly as it is; the whole background with its people, signs and objects; framing, crop, camera angle, light direction, focus and grain.\n"
    "\n"
    "THE RETOUCH, step by step, as thin layers on top of the locked base:\n"
    "1. Frequency separation. On the color-and-tone layer, calm the shine on forehead and nose and the passing redness beside the nose. Her sunspots, freckle clusters and permanent color patches stay in their places and shapes, each one a little lighter and softer. The texture layer stays as it is, so every pore and fine hair remains.\n"
    "2. Dodge and burn at low opacity. Lift the shadow in the hollow under each eye and under each eye bag by about a third. Lift the shadows that sagging casts: along each smile line, at the corners of the mouth and under the jawline, by about a third, while every contour stays where it is. Soften the deepest part of each forehead line by about a third; the lines remain, shallower.\n"
    "3. Spot healing for temporary marks only: a pimple, a scratch, a stray hair lying across the skin.\n"
    "4. Eyes. Brighten the whites slightly, place one small soft catchlight in each iris, lift the shadow on the upper lids a little, and give the lash line a touch more definition. Her eyes are a touch more open, about five percent, as when she is rested and alert; eye shape, lid shape and the distance between her eyes stay as photographed.\n"
    "5. A light makeup layer. A soft, broad, healthy glow on the top of the cheekbones and the bridge of the nose, smooth like moisturised skin; a whisper of peach blush; a sheer tint on the lips close to their own color.\n"
    "6. Hair color. Grey and white strands blend into her own soft natural black with a cool undertone and a gentle sheen. The hair keeps its shape, volume and movement.\n"
    "7. Final check, as the retoucher: flip between before and after. Tone, glow and hair color differ; every edge of her face lines up with the original.\n"
    "\n"
    "OUTPUT: a realistic photograph with the original colors, contrast and sharpness, a true-to-life phone-camera look.\n"
)


def build_edit_prompt(change: str) -> str:
    """Locked short edit prompt; the change text is inserted literally (str.replace, never .format)."""
    c = (change or '').strip()
    if not c:
        return EDIT_TEMPLATE.replace('Change only: {change}\n', '')
    return EDIT_TEMPLATE.replace('Change only: {change}\n', 'Change only: ' + c + '\n')


def build_beauty_prompt(face: str, change: str) -> str:
    """Locked retouch prompt; face and change are inserted literally (str.replace, never .format)."""
    f = (face or '').strip()
    c = (change or '').strip()
    prompt = BEAUTY_TEMPLATE
    if f:
        prompt = prompt.replace(_BEAUTY_FACE_LABEL + BEAUTY_FACE, _BEAUTY_FACE_LABEL + f)
    else:
        prompt = prompt.replace(_BEAUTY_FACE_LABEL + BEAUTY_FACE + '\n\n', '')
    if c:
        prompt = prompt.replace(
            'OUTPUT: ',
            'HER OWN REQUEST, done on top of the retouch, everything else as above: '
            + c + '\n\nOUTPUT: ',
        )
    return prompt


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


def _to_jpeg(raw: bytes) -> tuple[bytes, int, int]:
    """EXIF-transpose, RGB, JPEG q92: what the provider receives, plus its pixel size."""
    with Image.open(io.BytesIO(raw)) as img:
        rgb = ImageOps.exif_transpose(img).convert('RGB')
        out = io.BytesIO()
        rgb.save(out, format='JPEG', quality=92)
        return out.getvalue(), rgb.width, rgb.height


def _strip_metadata(png: bytes) -> bytes:
    """Re-encode a PNG without metadata (C2PA caBX, EXIF, ICC); on failure return it unchanged."""
    try:
        with Image.open(io.BytesIO(png)) as img:
            plain = img if img.mode in ('RGB', 'RGBA') else img.convert('RGB')
            out = io.BytesIO()
            plain.save(out, format='PNG')
            return out.getvalue()
    except Exception as e:
        logger.warning('mimi_image strip failed %s', type(e).__name__)
        return png


_GPT_SIZES = ((1 / 1, '1:1', '1024x1024'), (3 / 2, '3:2', '1536x1024'), (2 / 3, '2:3', '1024x1536'))


def _gpt_size(w: int, h: int) -> tuple[str, str]:
    """Closest GPT image aspect/size for a w x h photo, by |log(w/h) - log(ratio)|."""
    try:
        target = math.log(float(w) / float(h))
    except (TypeError, ValueError, ZeroDivisionError):
        return '1:1', '1024x1024'
    _, aspect_ratio, size = min(_GPT_SIZES, key=lambda item: abs(target - math.log(item[0])))
    return aspect_ratio, size


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
        MODEL: str = 'openai/gpt-image-2.6-flare'
        RESOLUTION: str = '2K'
        QUALITY: str = 'medium'
        COMPLEXITY: str = 'low'
        OPENROUTER_API_KEY: str = ''
        PRICE_PER_IMAGE_USD: float = 0.06
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

    async def _run_http(self, op, key, prompt, input_ref, in_bytes, user, request, emitter, metadata,
                        started, dims=None):
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
            model = str(self.valves.MODEL)
            if model.startswith('openai/'):
                aspect_ratio, size = _gpt_size(*dims) if dims else ('1:1', '1024x1024')
                body = {'model': model, 'prompt': prompt, 'n': 1, 'output_format': 'png',
                        'aspect_ratio': aspect_ratio, 'size': size,
                        'quality': self.valves.QUALITY,
                        'provider': {'options': {'openai': {'complexity': self.valves.COMPLEXITY}}}}
            else:
                body = {'model': model, 'prompt': prompt, 'n': 1, 'output_format': 'png',
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
                png = _strip_metadata(png)
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

    async def edit_image(self, change: str = '', kind: str = 'beauty', face: str = '',
                         __user__=None, __request__=None, __event_emitter__=None,
                         __messages__=None, __files__=None, __metadata__=None) -> str:
        """
        Sửa ảnh mà người dùng vừa gửi kèm trong chat.

        Dùng cho MỌI yêu cầu sửa ảnh đã gửi.
        ``kind``: dùng kind="beauty" khi yêu cầu là làm đẹp chính người trong ảnh
        (da, mắt, tóc, trông tươi tắn, đỡ mệt, trẻ hơn); kind="other" cho sửa khác
        (đổi nền, xóa vật, đổi màu áo...). Không chắc -> "beauty".
        ``face``: CHỈ khi kind="beauty". Tiếng Anh, một đoạn, tả khuôn mặt ĐÚNG như
        trong ảnh: dáng mặt, gò má, cằm, trán và đường chân tóc, lông mày, mắt và mí,
        mũi, môi, màu da, đốm nắng/nốt ruồi. Chỉ tả, không khen chê, không đề xuất
        thay đổi.
        ``change``: tiếng Anh, CHỈ phần người dùng muốn đổi; với beauty có thể để trống.
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
            jpeg, w, h = _to_jpeg(raw)
        except Exception as e:
            _log_call('edit', 0, started, None, len(raw), 0)
            return _error('mạng', _incident(type(e).__name__))
        k = (kind or '').strip().lower()
        prompt = build_edit_prompt(change) if k == 'other' else build_beauty_prompt(face, change)
        return await self._run_http(
            'edit', key, prompt, _data_url(jpeg), len(jpeg),
            __user__, __request__, __event_emitter__, __metadata__, started, (w, h),
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
