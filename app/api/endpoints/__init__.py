'''Импорты всех роутеров.'''

from .health import router as health_router  # noqa: F401
from .user import router as user_router  # noqa: F401
from .instrument import router as instrument_router  # noqa: F401
from .admin.instrument import router as admin_instrument_router  # noqa: F401

__all__ = [
    'health_router',
    'user_router',
    'instrument_router',
    'admin_instrument_router',
]
