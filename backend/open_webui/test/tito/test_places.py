"""Smoke tests for the ``places`` Open WebUI Tool (T6).

The tool lives at ``tito-deploy/tools/places.py`` and is installed later via the
admin API, so these tests load it by file path (importlib). They patch
``urllib.request.urlopen``, so no network is touched and the real Places API is
never called.
"""

import asyncio
import importlib.util
import io
import json
import urllib.error
import urllib.request
from pathlib import Path

# Repo root is 4 parents up from backend/open_webui/test/tito/test_places.py.
_TOOL_PATH = Path(__file__).resolve().parents[4] / 'tito-deploy' / 'tools' / 'places.py'

_spec = importlib.util.spec_from_file_location('places', _TOOL_PATH)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)

PRO_MASK = 'places.displayName,places.formattedAddress,places.location'
ENTERPRISE_FIELDS = ('places.rating', 'places.currentOpeningHours.weekdayDescriptions')
KEY = 'TEST-KEY-do-not-leak-7f3a'
PLACES = {
    'places': [
        {
            'displayName': {'text': 'Grocery Outlet'},
            'formattedAddress': '1 Main St, Fresno, CA',
            'rating': 4.4,
            'currentOpeningHours': {'weekdayDescriptions': ['Monday: 8 AM – 9 PM']},
        }
    ]
}


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_http(monkeypatch, payload=PLACES, error=None):
    """Replace urlopen; capture the request. Returns the capture dict."""
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured['req'] = req
        captured['timeout'] = timeout
        if error is not None:
            raise error
        return _FakeResponse(json.dumps(payload).encode('utf-8'))

    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)
    return captured


def _headers(req):
    return {k.lower(): v for k, v in req.header_items()}


def test_default_mask_is_pro_only(monkeypatch):
    # SOURCE: brief T6 spec 1 - default FieldMask is exactly the Pro tier mask.
    monkeypatch.setenv('TITO_PLACES_API_KEY', KEY)
    captured = _patch_http(monkeypatch)
    out = asyncio.run(module.Tools().search_places('tiệm tạp hóa'))

    headers = _headers(captured['req'])
    assert headers['x-goog-fieldmask'] == PRO_MASK
    assert headers['x-goog-api-key'] == KEY
    assert captured['req'].full_url == module.SEARCH_URL
    body = json.loads(captured['req'].data.decode('utf-8'))
    assert body == {'textQuery': 'tiệm tạp hóa near Fresno, CA', 'maxResultCount': 5}
    assert out == 'Grocery Outlet — 1 Main St, Fresno, CA'


def test_details_adds_enterprise_fields(monkeypatch):
    # SOURCE: brief T6 spec 1 - details=True adds rating and hours to the mask.
    monkeypatch.setenv('TITO_PLACES_API_KEY', KEY)
    captured = _patch_http(monkeypatch)
    out = asyncio.run(module.Tools().search_places('siêu thị', details=True))

    mask = _headers(captured['req'])['x-goog-fieldmask']
    assert mask == PRO_MASK + ',' + ','.join(ENTERPRISE_FIELDS)
    assert 'Monday: 8 AM' in out
    assert '4.4 sao' in out


def test_missing_key_returns_error_without_http(monkeypatch):
    # SOURCE: brief T6 spec 1 - missing key -> short error string, no HTTP call, never raises.
    monkeypatch.delenv('TITO_PLACES_API_KEY', raising=False)

    def must_not_call(req, timeout=None):
        raise AssertionError('HTTP must not be called without a key')

    monkeypatch.setattr(urllib.request, 'urlopen', must_not_call)
    out = asyncio.run(module.Tools().search_places('chợ'))
    assert out == module.NO_KEY


def test_key_never_appears_in_returned_text(monkeypatch):
    # SOURCE: brief T6 spec 1 - the key is never logged or returned, including on HTTP errors.
    monkeypatch.setenv('TITO_PLACES_API_KEY', KEY)
    _patch_http(monkeypatch)
    ok = asyncio.run(module.Tools().search_places('chợ', details=True))
    assert KEY not in ok

    err = urllib.error.HTTPError(module.SEARCH_URL, 403, 'Forbidden', {}, io.BytesIO(KEY.encode()))
    _patch_http(monkeypatch, error=err)
    out = asyncio.run(module.Tools().search_places('chợ'))
    assert out == 'Chưa tìm được địa điểm (mã 403).'
    assert KEY not in out
