"""
title: Mimi Task First
author: tito
version: 0.1.1
description: Nhắc Mimi làm đúng việc người dùng nhờ, ngay sát câu hỏi mới nhất (chỉ inlet).
"""

import logging

from pydantic import BaseModel

DEFAULT_NOTE = "[Note to Mimi, not from the user: do what they asked, fully. For a photo change (slimmer, younger, anything), the first step is to call edit_image with exactly that ask; it is their photo and their choice. No opinion on whether they should, no advice to stay natural, no moral comment. Mention a limit only when a tool's own reply states one.]"

logger = logging.getLogger(__name__)


class Filter:
    class Valves(BaseModel):
        ENABLED: bool = True
        NOTE: str = DEFAULT_NOTE

    def __init__(self):
        self.valves = self.Valves()

    def inlet(self, body: dict, __user__: dict | None = None) -> dict:
        """Append the task-first note to the newest user message, once per message."""
        try:
            note = self.valves.NOTE
            if not self.valves.ENABLED or not note or not note.strip():
                return body

            messages = body.get('messages') or []
            message = None
            for candidate in reversed(messages):
                if isinstance(candidate, dict) and candidate.get('role') == 'user':
                    message = candidate
                    break
            if message is None:
                return body

            content = message.get('content')
            if isinstance(content, str):
                if note in content:
                    return body
                message['content'] = content + '\n\n' + note
            elif isinstance(content, list):
                text_parts = [
                    part
                    for part in content
                    if isinstance(part, dict) and part.get('type') == 'text'
                ]
                if any(note in (part.get('text') or '') for part in text_parts):
                    return body
                if text_parts:
                    text_parts[-1]['text'] = text_parts[-1]['text'] + '\n\n' + note
                else:
                    content.append({'type': 'text', 'text': note})
            return body
        except Exception as e:
            logger.warning('mimi_task_first inlet failed: %s', type(e).__name__)
            return body
