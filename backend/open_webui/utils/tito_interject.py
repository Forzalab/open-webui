"""Hidden admin notes ("interject") for Tito, delivered once on a user's next turn.

Pure helpers: no FastAPI, no DB. The store is a JSON file under DATA_DIR:

    {user_id: [{"text": str, "ts": epoch_float}, ...]}

Reads/writes go through a module lock and an atomic tmp-file + os.replace.
``pop_notes`` is called on the chat hot path, so it never raises.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import unicodedata

from open_webui.env import DATA_DIR

log = logging.getLogger(__name__)

STORE_FILENAME = 'tito-interject.json'
DEFAULT_PATH = os.path.join(DATA_DIR, STORE_FILENAME)
NOTE_TTL_SECONDS = 86400
MAX_NOTE_CHARS = 1000
MAX_PENDING_PER_USER = 5

_lock = threading.Lock()


def _resolve(path: str | None) -> str:
    return path or DEFAULT_PATH


def _clean_entries(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = item.get('text')
        ts = item.get('ts')
        if isinstance(text, str) and isinstance(ts, (int, float)) and not isinstance(ts, bool):
            out.append({'text': text, 'ts': float(ts)})
    return out


def _load(path: str) -> dict:
    """Read the whole store. Any error means an empty store (logged, never raised)."""
    try:
        if not os.path.exists(path):
            return {}
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            log.warning('[TITO] interject store is not an object; treating as empty')
            return {}
        return {str(uid): _clean_entries(entries) for uid, entries in data.items()}
    except Exception as e:
        log.warning('[TITO] interject store unreadable; treating as empty (%s)', type(e).__name__)
        return {}


def _save(path: str, data: dict) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _fresh(notes: list[dict], now: float) -> list[dict]:
    return [n for n in notes if now - n['ts'] <= NOTE_TTL_SECONDS]


def add_note(user_id: str, text: str, now: float | None = None, path: str | None = None) -> list[str]:
    """Store a note for ``user_id``. Returns that user's pending note texts, oldest first."""
    cleaned = (text or '').strip()
    if not cleaned:
        raise ValueError('note text is empty')
    if len(cleaned) > MAX_NOTE_CHARS:
        raise ValueError(f'note text exceeds {MAX_NOTE_CHARS} characters')
    ts = time.time() if now is None else now
    p = _resolve(path)
    with _lock:
        data = _load(p)
        notes = _fresh(data.get(user_id, []), ts)
        notes.append({'text': cleaned, 'ts': ts})
        notes = notes[-MAX_PENDING_PER_USER:]
        data[user_id] = notes
        _save(p, data)
        return [n['text'] for n in notes]


def pending(path: str | None = None, now: float | None = None) -> dict:
    """Non-expired notes per user: ``{user_id: [{"text", "ts"}, ...]}``. Users with none are omitted."""
    ts = time.time() if now is None else now
    with _lock:
        data = _load(_resolve(path))
    out = {}
    for uid, notes in data.items():
        fresh = _fresh(notes, ts)
        if fresh:
            out[uid] = fresh
    return out


def pop_notes(user_id: str, now: float | None = None, path: str | None = None) -> list[str]:
    """Return non-expired note texts (oldest first) for ``user_id`` and remove them. Never raises."""
    try:
        ts = time.time() if now is None else now
        p = _resolve(path)
        with _lock:
            data = _load(p)
            if user_id not in data:
                return []
            notes = _fresh(data.pop(user_id), ts)
            _save(p, data)
        return [n['text'] for n in notes]
    except Exception as e:
        log.warning('[TITO] interject pop failed (%s)', type(e).__name__)
        return []


def clear(user_id: str, path: str | None = None) -> int:
    """Remove every note for ``user_id``. Returns how many were removed."""
    p = _resolve(path)
    with _lock:
        data = _load(p)
        if user_id not in data:
            return 0
        removed = len(data.pop(user_id))
        _save(p, data)
    return removed


def format_notes(texts: list[str]) -> str:
    """One line per note for the per-turn status block; '' when there are none."""
    if not texts:
        return ''
    return '\n'.join(f'Tùng dặn (nói lại tự nhiên trong câu trả lời, một lần thôi): {t}' for t in texts)


def _fold(value: str) -> str:
    """Lowercase and strip accents (incl. Vietnamese đ/Đ, which NFD does not decompose)."""
    value = (value or '').replace('đ', 'd').replace('Đ', 'D')
    decomposed = unicodedata.normalize('NFD', value)
    stripped = ''.join(ch for ch in decomposed if unicodedata.category(ch) != 'Mn')
    return ' '.join(stripped.casefold().split())


def match_user(users: list[tuple[str, str]], query: str) -> tuple[str, str] | None:
    """Resolve ``query`` to one ``(user_id, name)`` pair, or None.

    Order: exact user id; then exact name (accent/case-insensitive); then a unique
    substring of the name. Any ambiguity returns None.
    """
    q = (query or '').strip()
    if not q:
        return None
    for uid, name in users:
        if uid == q:
            return uid, name
    folded = _fold(q)
    exact = [(uid, name) for uid, name in users if _fold(name) == folded]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    partial = [(uid, name) for uid, name in users if folded and folded in _fold(name)]
    if len(partial) == 1:
        return partial[0]
    return None
