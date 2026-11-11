"""Admin-only Tito controls: hidden next-turn notes and chat refreeze."""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from open_webui.models.chats import Chats
from open_webui.models.users import Users
from open_webui.utils import tito, tito_interject
from open_webui.utils.auth import get_admin_user
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()


class InterjectForm(BaseModel):
    user: str
    text: str


async def _user_pairs() -> list[tuple[str, str]]:
    result = await Users.get_users()
    users = result.get('users', []) if isinstance(result, dict) else result
    return [(u.id, u.name or '') for u in users]


@router.post('/interject')
async def add_interject(form: InterjectForm, user=Depends(get_admin_user)):
    pairs = await _user_pairs()
    match = tito_interject.match_user(pairs, form.user)
    if match is None:
        raise HTTPException(status_code=404, detail='user not found or ambiguous')
    user_id, name = match
    try:
        pending = tito_interject.add_note(user_id, form.text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    log.info('[TITO] interject stored for user_id=%s', user_id)
    return {'user_id': user_id, 'name': name, 'pending': pending}


@router.get('/interject')
async def list_interject(user=Depends(get_admin_user)):
    names = dict(await _user_pairs())
    now = time.time()
    out = {}
    for uid, notes in tito_interject.pending(now=now).items():
        out[uid] = {
            'name': names.get(uid, ''),
            'notes': [{'text': n['text'], 'age_min': int((now - n['ts']) // 60)} for n in notes],
        }
    return out


@router.delete('/interject/{user_id}')
async def clear_interject(user_id: str, user=Depends(get_admin_user)):
    return {'cleared': tito_interject.clear(user_id)}


@router.post('/chats/{chat_id}/refreeze')
async def refreeze_chat(chat_id: str, user=Depends(get_admin_user)):
    chat = await Chats.get_chat_by_id(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail='chat not found')
    new_meta, had = tito.drop_frozen_system(chat.meta or {})
    if had:
        await Chats.replace_chat_meta_by_id(chat_id, new_meta)
    log.info('[TITO] refreeze chat_id=%s had_frozen=%s', chat_id, had)
    return {'chat_id': chat_id, 'had_frozen': had}
