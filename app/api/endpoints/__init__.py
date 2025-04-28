'''Импорты всех роутеров.'''

from .health import router as health_router  # noqa: F401
from .user import router as user_router  # noqa: F401
from .admin.balance import router as balance_router  # noqa: F401
from .admin.user import router as admin_user_router  # noqa: F401

__all__ = ['health_router', 'user_router', 'balance_router', 'admin_user_router']
