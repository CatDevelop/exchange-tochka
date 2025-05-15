from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from app.api.routers import main_router
from app.core.docs.docs import get_custom_docs
from app.core.middleware.cors import add_cors_middleware
from app.core.middleware.global_ import LoggingMiddleware

app = FastAPI(
    default_response_class=ORJSONResponse,
    docs_url=None,
    redoc_url=None
)

add_cors_middleware(app)
app.add_middleware(LoggingMiddleware)

app.include_router(main_router)
get_custom_docs(
    app,
    path_to_static_dirs='./static',
    docs_url='/core/docs',
    swagger_js_url='/static/docs/swagger-ui-bundle.js',
    swagger_css_url='/static/docs/swagger-ui.css',
)
