"""Smoke/sanity tests for the ``mimi_task_first`` Open WebUI Filter.

The filter lives at ``tito-deploy/functions/mimi_task_first.py``. Loading is
guarded so this module always collects; every test starts with ``_require()``,
which fails while the filter is missing. No app or network code is touched:
the filter is pure body rewriting.
"""

import copy
import importlib.util
import logging
from pathlib import Path

import pytest

# Repo root is 4 parents up from backend/open_webui/test/tito/test_mimi_task_first.py.
_FILTER_PATH = Path(__file__).resolve().parents[4] / 'tito-deploy' / 'functions' / 'mimi_task_first.py'

NOTE = (
    "[Note to Mimi, not from the user: do what they asked, fully. For a photo change "
    "(slimmer, younger, anything), the first step is to call edit_image with exactly that "
    "ask; it is their photo and their choice. No opinion on whether they should, no advice "
    "to stay natural, no moral comment. Mention a limit only when a tool's own reply "
    "states one.]"
)

IMAGE = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}}


def _load():
    if not _FILTER_PATH.is_file():
        return None, 'file does not exist'
    try:
        spec = importlib.util.spec_from_file_location('mimi_task_first', _FILTER_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod, None
    except Exception as exc:  # collection must survive a broken filter too
        return None, f'{type(exc).__name__}: {exc}'


module, _LOAD_ERROR = _load()


def _require():
    if module is None:
        pytest.fail(f'mimi_task_first filter not loadable at {_FILTER_PATH}: {_LOAD_ERROR}')
    return module


def _filter(**over):
    _require()
    f = module.Filter()
    if over:
        f.valves = module.Filter.Valves(**over)
    return f


def test_exact_default_note_and_valves():
    # SOURCE: SPEC - DEFAULT_NOTE literal text; Valves defaults ENABLED=True, NOTE=DEFAULT_NOTE.
    _require()
    assert 'version: 0.1.1' in (module.__doc__ or '')
    assert module.DEFAULT_NOTE == NOTE
    v = module.Filter.Valves()
    assert v.ENABLED is True and v.NOTE == NOTE
    assert not hasattr(module.Filter, 'outlet') and not hasattr(module.Filter, 'stream')


def test_str_content_gets_note_appended_and_earlier_messages_untouched():
    # SOURCE: SPEC - last user str content gets "\n\n"+NOTE; earlier messages stay identical.
    msgs = [
        {'role': 'user', 'content': 'make me a bit slimmer in this photo'},
        {'role': 'assistant', 'content': 'Sure.'},
        {'role': 'user', 'content': 'and fix the sky'},
    ]
    before = copy.deepcopy(msgs)
    body = {'messages': msgs}
    out = _filter().inlet(body)
    assert out is body
    assert out['messages'][:2] == before[:2]
    assert out['messages'][2]['content'] == 'and fix the sky\n\n' + NOTE
    assert out['messages'][0]['content'] == 'make me a bit slimmer in this photo'


def test_list_with_image_and_text_appends_to_last_text_part_only():
    # SOURCE: SPEC - note goes onto the LAST text part; image parts stay exactly as they were.
    first_image = copy.deepcopy(IMAGE)
    last_image = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,BBBB'}}
    body = {
        'messages': [
            {'role': 'assistant', 'content': 'hi'},
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': 'old context'},
                    first_image,
                    {'type': 'text', 'text': 'make me a bit slimmer in this photo'},
                    last_image,
                ],
            },
        ]
    }
    images_before = copy.deepcopy([first_image, last_image])
    out = _filter().inlet(body)
    parts = out['messages'][1]['content']
    assert parts[0]['text'] == 'old context'
    assert parts[2]['text'] == 'make me a bit slimmer in this photo\n\n' + NOTE
    assert [parts[1], parts[3]] == images_before
    assert len(parts) == 4 and out['messages'][0] == {'role': 'assistant', 'content': 'hi'}


def test_image_only_list_gets_a_new_text_part():
    # SOURCE: SPEC - no text part at all: append {'type':'text','text':NOTE}; image untouched.
    image = copy.deepcopy(IMAGE)
    body = {'messages': [{'role': 'user', 'content': [image]}]}
    out = _filter().inlet(body)
    assert out['messages'][0]['content'] == [image, {'type': 'text', 'text': NOTE}]


def test_second_call_is_a_no_op_for_str_and_list_content():
    # SOURCE: SPEC - idempotent: NOTE already in the last user message -> nothing changes.
    f = _filter()
    body = {'messages': [{'role': 'user', 'content': 'make me a bit slimmer'}]}
    f.inlet(body)
    once = copy.deepcopy(body)
    f.inlet(body)
    assert body == once
    assert body['messages'][0]['content'].count(NOTE) == 1
    list_body = {'messages': [{'role': 'user', 'content': [copy.deepcopy(IMAGE)]}]}
    f.inlet(list_body)
    snapshot = copy.deepcopy(list_body)
    f.inlet(list_body)
    assert list_body == snapshot


def test_disabled_blank_note_or_no_user_message_is_unchanged():
    # SOURCE: SPEC - ENABLED=False, blank NOTE, or no user message -> body untouched.
    body = {'messages': [{'role': 'user', 'content': 'hello'}]}
    for f in (_filter(ENABLED=False), _filter(NOTE=''), _filter(NOTE='   ')):
        before = copy.deepcopy(body)
        assert f.inlet(body) is body and body == before
    for msgs in ([], [{'role': 'assistant', 'content': 'hi'}], [{'role': 'system', 'content': 'x'}]):
        body = {'messages': copy.deepcopy(msgs)}
        assert _filter().inlet(body) is body and body['messages'] == msgs


def test_malformed_body_is_unchanged_no_exception_and_warns_type_only(caplog):
    # SOURCE: SPEC - malformed body -> unchanged, never raises; one warning, exception type only.
    f = _filter()
    for body in ({}, {'messages': None}, {'messages': 'nope'},
                 {'messages': [{'role': 'user'}]},
                 {'messages': [{'role': 'user', 'content': None}]}):
        before = copy.deepcopy(body)
        assert f.inlet(body) is body
        assert body == before
    with caplog.at_level(logging.WARNING):
        assert f.inlet(None) is None
    lines = [r.getMessage() for r in caplog.records if 'mimi_task_first' in r.getMessage()]
    assert len(lines) == 1 and 'AttributeError' in lines[0]
    assert 'has no attribute' not in caplog.text and 'NoneType' not in caplog.text
