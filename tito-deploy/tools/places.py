"""
title: Places
author: tito
version: 0.1.0
description: Tìm địa điểm gần Fresno/Clovis qua Google Places API (New).
"""

import asyncio
import json
import os
import urllib.error
import urllib.request

from pydantic import BaseModel

SEARCH_URL = 'https://places.googleapis.com/v1/places:searchText'
# Pro tier (cheap): default field mask.
FIELDS_BASE = 'places.displayName,places.formattedAddress,places.location'
# Enterprise tier: only added when details=True.
FIELDS_DETAILS = ',places.rating,places.currentOpeningHours.weekdayDescriptions'
TIMEOUT_SECONDS = 10
MAX_RESULTS = 5

NO_KEY = 'Chưa có khóa Places API nên chưa tìm được địa điểm.'
HTTP_ERROR = 'Chưa tìm được địa điểm (mã {code}).'
NONE_FOUND = 'Không tìm thấy địa điểm nào.'


def _post_search(key: str, body: dict, field_mask: str) -> dict:
    """POST one Places searchText request. Raises on HTTP/network/JSON errors."""
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        SEARCH_URL,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'X-Goog-Api-Key': key,
            'X-Goog-FieldMask': field_mask,
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _format(places: list, details: bool) -> str:
    lines = []
    for place in (places or [])[:MAX_RESULTS]:
        if not isinstance(place, dict):
            continue
        name = (place.get('displayName') or {}).get('text') or '?'
        address = place.get('formattedAddress') or '?'
        line = f'{name} — {address}'
        if details:
            extras = []
            if place.get('rating') is not None:
                extras.append(f'{place["rating"]} sao')
            hours = (place.get('currentOpeningHours') or {}).get('weekdayDescriptions')
            if hours:
                extras.append('; '.join(hours))
            if extras:
                line += ' — ' + ' | '.join(extras)
        lines.append(line)
    return '\n'.join(lines) if lines else NONE_FOUND


class Tools:
    class Valves(BaseModel):
        pass

    def __init__(self):
        self.valves = self.Valves()

    async def search_places(self, query: str, near: str = 'Fresno, CA', details: bool = False) -> str:
        """
        Tìm địa điểm (tiệm, siêu thị, nhà thuốc, nhà hàng...) gần Fresno/Clovis.

        ``details=True`` thêm đánh giá và giờ mở cửa (gói đắt hơn): chỉ bật khi người dùng
        hỏi về giờ mở cửa hoặc đánh giá. Mặc định chỉ trả tên và địa chỉ.
        """
        # Read at call time; the key is never stored, logged or returned.
        key = os.getenv('TITO_PLACES_API_KEY', '').strip()
        if not key:
            return NO_KEY

        field_mask = FIELDS_BASE + (FIELDS_DETAILS if details else '')
        body = {'textQuery': f'{query} near {near}', 'maxResultCount': MAX_RESULTS}
        try:
            data = await asyncio.to_thread(_post_search, key, body, field_mask)
        except urllib.error.HTTPError as e:
            return HTTP_ERROR.format(code=e.code)
        except TimeoutError:
            return HTTP_ERROR.format(code='timeout')
        except Exception as e:
            if isinstance(getattr(e, 'reason', None), TimeoutError):
                return HTTP_ERROR.format(code='timeout')
            return HTTP_ERROR.format(code='mạng')

        return _format(data.get('places') if isinstance(data, dict) else None, details)
