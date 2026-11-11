"""Make ``open_webui`` importable when pytest runs from the source tree.

SOURCE of path layout: the package lives at ``backend/open_webui``; this file sits
at ``backend/open_webui/test/tito/conftest.py``, so ``../..`` reaches ``backend/``.
No-op when ``open_webui`` is already installed (build env).
"""

import os
import sys

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))

if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# Importing open_webui.env exits when this is unset (SystemExit is not an Exception).
os.environ.setdefault('WEBUI_SECRET_KEY', 'test-secret-key-not-for-prod')
