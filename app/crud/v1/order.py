# Реэкспортируем order_crud из модуля, чтобы сохранить совместимость
from app.crud.v1.order.crud_order import order_crud

# Реэкспортируем order_crud из нового модуля
__all__ = ["order_crud"]
