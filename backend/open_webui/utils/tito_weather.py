"""Fresno weather for the Tito status line (Open-Meteo, no API key).

Kept out of ``tito.py`` so that module stays pure.  ``fetch_fresno_weather`` never
raises: on any failure it logs one ``TITO-ERR`` line (no URL, no response body) and
returns ``None``, so the status simply omits the weather line.
"""

import asyncio
import logging
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

WEATHER_URL = (
    'https://api.open-meteo.com/v1/forecast?latitude=36.7378&longitude=-119.7871'
    '&current=temperature_2m,weather_code&daily=temperature_2m_max,temperature_2m_min'
    '&temperature_unit=fahrenheit&timezone=America%2FLos_Angeles&forecast_days=1'
)
WEATHER_TIMEOUT_SECONDS = 3
_FRESNO_TZ = ZoneInfo('America/Los_Angeles')


class _WeatherHTTPError(Exception):
    def __init__(self, status: int):
        super().__init__(status)
        self.status = status


def weather_word(code: int) -> str:
    """Short Vietnamese word for an Open-Meteo WMO weather code."""
    if code == 0:
        return 'trời quang'
    if 1 <= code <= 3:
        return 'có mây'
    if code in (45, 48):
        return 'sương mù'
    if 51 <= code <= 67:
        return 'mưa'
    if 71 <= code <= 77:
        return 'tuyết'
    if 80 <= code <= 82:
        return 'mưa rào'
    if 95 <= code <= 99:
        return 'giông'
    return 'không rõ'


def format_weather(data: dict) -> str:
    """e.g. ``mưa, 58°F (thấp 50 cao 61)``. Raises on a malformed payload."""
    current = data['current']
    daily = data['daily']
    word = weather_word(int(current['weather_code']))
    now_f = round(current['temperature_2m'])
    low = round(daily['temperature_2m_min'][0])
    high = round(daily['temperature_2m_max'][0])
    return f'{word}, {now_f}°F (thấp {low} cao {high})'


def _log_error(detail: str) -> None:
    stamp = datetime.now(_FRESNO_TZ).strftime('%H%M')
    log.warning('TITO-ERR T%s PST-%s weather %s', stamp, secrets.token_hex(2), detail)


async def _fetch(session_factory) -> str:
    if session_factory is None:
        import aiohttp  # lazy: keeps this module importable without aiohttp

        timeout = aiohttp.ClientTimeout(total=WEATHER_TIMEOUT_SECONDS)

        def session_factory():
            return aiohttp.ClientSession(timeout=timeout)

    async with session_factory() as session:
        async with session.get(WEATHER_URL) as resp:
            if resp.status != 200:
                raise _WeatherHTTPError(resp.status)
            data = await resp.json(content_type=None)
    return format_weather(data)


async def fetch_fresno_weather(session_factory=None) -> str | None:
    """Return the Fresno weather text, or ``None`` on any failure (never raises).

    ``session_factory`` is injectable for tests; production callers omit it.
    """
    try:
        return await asyncio.wait_for(_fetch(session_factory), WEATHER_TIMEOUT_SECONDS)
    except _WeatherHTTPError as e:
        _log_error(str(e.status))
    except Exception as e:
        _log_error(type(e).__name__)
    return None
