"""
title: Mimi Image
author: tito
version: 0.4.1
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

TICK_SECONDS = 15
WAIT_EDIT = 'Mimi vẫn đang sửa hình, chờ Mimi chút nha… ({n} giây)'
WAIT_GENERATE = 'Mimi vẫn đang vẽ hình, chờ Mimi chút nha… ({n} giây)'

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


RECIPES = {
    'haze': (
        "Clear the haze the way a Lightroom dehaze with a small black-point adjustment does: the darkest tones a little deeper, natural midtone contrast and clear true colors back, while distant scenery keeps its soft natural depth."
    ),
    'dim': (
        "Lift the exposure on the people and the deep shadows by about one stop, as a local exposure lift, so faces and skin show true detail and natural color; the scene keeps its evening or indoor light, warm lamps and darker background mood, with clean low noise and a fine natural grain."
    ),
    'backlight': (
        "Add soft fill light to [whose] face, as a gentle dodge with lifted shadows, so eyes, nose and cheeks read evenly and clearly, while the original sun direction, the bright rim of light and the sky stay as they are, with highlights recovered."
    ),
    'cast': (
        "Correct the [orange/blue/green] light cast on the skin with a white-balance fix on the skin tones only, giving natural healthy skin within half a shade of the person's own tone; the scene's light, clothing colors and mood stay as photographed."
    ),
    'sharpen': (
        "Apply gentle capture sharpening, as a pro does right after the shot, so eyes, hair and clothing edges look crisp and natural at true phone-photo detail, with clean edges."
    ),
    'clothes': (
        "Tidy the clothing as a garment cleanup: relax the wrinkles and bunched folds at [area, e.g. the waist and belly of the orange dress] so the fabric drapes smoothly and evenly, with the same color, print, seams, hemline and fit; the folds are flattened in tone, as a light dodge and burn, while every outline stays where it is."
    ),
    'object': (
        "Remove [object + where, e.g. the black bag strap across her chest] and rebuild the clothing and background behind it naturally, continuing the fabric, print, wall and floor lines; where it pulled or pressed on the clothes, the fabric falls smooth again."
    ),
    'arm': (
        "Soften the shadow and the small fold where [whose] arm presses against the body, as a light dodge and burn, so the arm and side read clean; the arm stays in its exact position and outline."
    ),
    'stranger': (
        "Remove [who/what + where, e.g. the man in the blue shirt at the left edge] and fill the space with the surrounding background in matching perspective, light and grain; everyone else and the whole scene stay as they are."
    ),
}

NEUTRAL_TEMPLATE = (
    "You are a senior photo retoucher working on a real family photo. The job is a light, invisible fix, the kind a pro finishes in fifteen minutes: the result reads as the same unedited phone photo, taken on a better moment.\n"
    "\n"
    "THE FIX:\n"
    "{recipe lines, numbered, max 2}\n"
    "{optional: THEIR OWN REQUEST: <change>}\n"
    "\n"
    "KEEP, edge for edge with the original: every face and its features, expression and age; skin with its pores, fine lines and natural uneven tone; body shape and outline; pose, arms and hands; hair; clothing design, color, print and fit; every person and object in the background; camera angle, framing, crop and aspect ratio; focus and grain; and the color temperature of the photo, except where the fix itself names a change.\n"
    "\n"
    "OUTPUT: a realistic photograph with real texture and true-to-life phone-camera colors, no glamorization.\n"
)

_NEUTRAL_FIX_SLOT = '{recipe lines, numbered, max 2}\n'
_NEUTRAL_REQUEST_SLOT = '{optional: THEIR OWN REQUEST: <change>}\n'
_NEUTRAL_KEEP_SENTENCE = 'Keep the photo as it is, with a light natural clean-up of exposure and color.'


def parse_kind(kind: str) -> list[str]:
    """Comma-separated kind string -> ordered, deduped keys; at most two recipe keys; default beauty."""
    picked = []
    recipes = 0
    for raw in str(kind or '').split(','):
        key = raw.strip().lower()
        if not key or key in picked:
            continue
        if key in RECIPES:
            if recipes >= 2:
                continue
            recipes += 1
        elif key not in ('beauty', 'other'):
            continue
        picked.append(key)
    return picked or ['beauty']


def _recipe_keys(keys) -> list[str]:
    """Recipe keys only, in order, deduped, at most two."""
    out = []
    for key in keys or ():
        k = str(key).strip().lower()
        if k in RECIPES and k not in out:
            out.append(k)
    return out[:2]


def build_edit_prompt(change: str) -> str:
    """Locked short edit prompt; the change text is inserted literally (str.replace, never .format)."""
    c = (change or '').strip()
    if not c:
        return EDIT_TEMPLATE.replace('Change only: {change}\n', '')
    return EDIT_TEMPLATE.replace('Change only: {change}\n', 'Change only: ' + c + '\n')


def build_beauty_prompt(face: str, change: str, keys=()) -> str:
    """Locked retouch prompt; face, change and recipe lines are inserted literally (str.replace, never .format)."""
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
            'HER OWN REQUEST, done in full on top of the retouch; for the parts it names '
            'it takes priority over the locked base, everything else as above: '
            + c + '\n\nOUTPUT: ',
        )
    recipes = _recipe_keys(keys)
    if recipes:
        block = (
            '6b. Also, as part of this same retouch (for this item only, it takes priority over the locked base):\n'
            + ''.join('- ' + RECIPES[k] + '\n' for k in recipes)
        )
        prompt = prompt.replace('7. Final check', block + '7. Final check', 1)
    return prompt


def build_neutral_prompt(keys, change: str = '') -> str:
    """Locked neutral edit prompt; recipe lines and change are inserted literally (str.replace, never .format)."""
    c = (change or '').strip()
    recipes = _recipe_keys(keys)
    if recipes:
        fix = '\n'.join(f'{i}. {RECIPES[k]}' for i, k in enumerate(recipes, 1)) + '\n'
    elif c:
        fix = ''
    else:
        fix = _NEUTRAL_KEEP_SENTENCE + '\n'
    prompt = NEUTRAL_TEMPLATE.replace(_NEUTRAL_FIX_SLOT, fix)
    request = ('THEIR OWN REQUEST, done in full; for the parts it names it takes priority '
               'over the KEEP list: ' + c + '\n') if c else ''
    return prompt.replace(_NEUTRAL_REQUEST_SLOT, request)


def build_generate_prompt(description: str) -> str:
    """Locked generate prompt: the description plus a fixed photo-look suffix."""
    return (description or '').strip() + '\n' + GEN_SUFFIX


def _incident(detail: str) -> str:
    """Log one TITO-ERR line and return its code (detail: status, 'timeout', 'empty' or exception type)."""
    code = f'T{datetime.now(ZoneInfo("America/Los_Angeles")):%H%M}-{secrets.token_hex(2)}'
    logger.error('TITO-ERR %s mimi_image %s', code, detail)
    return code


def _http_error_detail(e, *secrets) -> str:
    """First 200 chars of the provider error.message, else of the raw body; never raises."""
    try:
        raw = e.read() or b''
    except Exception:
        return ''
    text = raw.decode('utf-8', 'replace') if isinstance(raw, (bytes, bytearray)) else str(raw)
    detail = ''
    try:
        payload = json.loads(text)
    except Exception:
        payload = None
    if isinstance(payload, dict):
        error = payload.get('error')
        message = error.get('message') if isinstance(error, dict) else None
        if isinstance(message, str):
            detail = message
    text = detail or text
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), '[redacted]')
    return text[:200].strip()


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
        ticker = None

        async def _tick():
            try:
                while True:
                    await asyncio.sleep(TICK_SECONDS)
                    n = max(1, int(time.monotonic() - tick_started))
                    text = (WAIT_EDIT if op == 'edit' else WAIT_GENERATE).replace('{n}', str(n))
                    await _emit(emitter, _status(text, False))
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

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
            tick_started = time.monotonic()
            if emitter is not None:
                ticker = asyncio.create_task(_tick())
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
            code = _incident(str(e.code))
            detail = _http_error_detail(e, key, prompt, input_ref)
            if detail:
                logger.error('TITO-ERR %s mimi_image body %s', code, detail)
            text = _error(e.code, code)
        except TimeoutError:
            text = _error('timeout', _incident('timeout'))
        except Exception as e:
            if isinstance(getattr(e, 'reason', None), TimeoutError):
                text = _error('timeout', _incident('timeout'))
            else:
                text = _error('mạng', _incident(type(e).__name__))
        finally:
            if ticker is not None:
                ticker.cancel()
                try:
                    await ticker
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            await _emit(emitter, _status(desc, True))
        _log_call(op, ok, started, cost, in_bytes, out_bytes)
        return text

    async def edit_image(self, change: str = '', kind: str = 'beauty', face: str = '',
                         __user__=None, __request__=None, __event_emitter__=None,
                         __messages__=None, __files__=None, __metadata__=None) -> str:
        """
        Sửa ảnh mà người dùng đã gửi trong chat.

        Dùng cho MỌI yêu cầu sửa ảnh đã gửi. Luôn sửa từ ảnh GỐC người dùng gửi.
        ``kind``: một hoặc hai mã, cách nhau dấu phẩy. Mặc định "beauty" (làm đẹp nhẹ
        người trong ảnh, luôn có).
        haze = ảnh mờ, nhạt màu, như có sương; dim = tối, thiếu sáng, ban đêm;
        backlight = ngược sáng, mặt tối; cast = da bị vàng/cam/xanh do đèn;
        sharpen = ảnh hơi nhòe; clothes = áo nhăn, nhúm ở bụng/eo; object = dây túi,
        túi, tay ai, cột làm người nhìn to ra; arm = tay ép sát người; stranger = người
        lạ, đồ lỉnh kỉnh.
        other = ảnh KHÔNG cần làm đẹp người (cảnh, đồ vật) hoặc sửa thứ khác hẳn.
        nhìn mập/bụng to/tay to" mà KHÔNG nói muốn ốm hơn: chọn nguyên nhân trong ảnh (clothes/object/arm). Nếu họ NÓI muốn ốm hơn, thon hơn, trẻ hơn hay đổi dáng: viết đúng điều đó vào change, làm đúng ý họ, không bình luận."
        ``face``: chỉ khi làm đẹp người: tiếng Anh, một đoạn, tả khuôn mặt đúng như
        trong ảnh, không khen chê.
        ``change``: tiếng Anh, chỉ chi tiết cho mã đã chọn: cái gì, ở đâu, của ai
        (ví dụ "the black bag strap across her chest").
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
        keys = parse_kind(kind)
        recipes = [k for k in keys if k in RECIPES]
        if 'other' in keys:
            prompt = build_neutral_prompt(recipes, change)
        else:
            prompt = build_beauty_prompt(face, change, recipes)
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
