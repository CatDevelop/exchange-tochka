from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles


def get_custom_docs(
    app: FastAPI,
    path_to_static_dirs: str = '',
    docs_url: str | None = '/docs',
    swagger_js_url: str = 'https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js',
    swagger_css_url: str = 'https://unpkg.com/swagger-ui-dist@5/swagger-ui.css',
    redoc_url: str | None = '/redoc',
    redoc_js_url: str = 'https://unpkg.com/redoc@next/bundles/redoc.standalone.js',
) -> None:
    """Функция для подмены путей к js и css статике, если долго загружается swagger.

    Обязательно нужно отключить документацию swagger и redoc в `app = FastAPI(
    docs_url=None, redoc_url=None)` если хотите переопределить их с помощью функции
    get_custom_docs.

    Если нужно чтобы статика для документаций хранилась локально. Необходимо
    определить переменную `path_to_static_dirs`, (если у Вас в приложении еще не
    определена папка статики, если папка со статикой уже определена, этот параметр не
    нужно указывать) и положить статику для документации в папку со статикой приложения.


    ### Пример удаленной статики:

        get_custom_docs(
            app,
            docs_url='/docs',
            redoc_url='/redoc',
        )

    Здесь я не указываю ссылки на статику, потому что хочу использовать стандартные.

    ### Пример локальной статики:

        get_custom_docs(
            app,
            path_to_static_dirs='./static',
            docs_url='/docs',
            swagger_js_url='/static/swagger-ui-bundle.js',
            swagger_css_url='/static/swagger-ui.css',
            redoc_url='/redoc',
            redoc_js_url='/static/redoc.standalone.js',
        )



    Args:
        app (FastAPI): Экземпляр приложения FastAPI
        path_to_static_dirs (str): Путь к папке со статикой. По умолчанию '' - отключено
        docs_url (str | None, optional): Ссылка на документацию swagger.
            По умолчанию '/docs'. None - отключить документацию swagger.
        swagger_js_url (_type_, optional): Ссылка на js файл для swagger.
            По умолчанию 'https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js'.
        swagger_css_url (_type_, optional): Ссылка на css файл для swagger.
            По умолчанию 'https://unpkg.com/swagger-ui-dist@5/swagger-ui.css'.
        redoc_url (str | None, optional): Ссылка на документацию redoc.
            По умолчанию '/redoc'. None - отключить документацию redoc.
        redoc_js_url (_type_, optional): Ссылка на js файл для redoc.
            По умолчанию 'https://unpkg.com/redoc@next/bundles/redoc.standalone.js'.
    """

    if path_to_static_dirs:
        static = Path(path_to_static_dirs)
        static.mkdir(parents=True, exist_ok=True)
        app.mount('/static', StaticFiles(directory=static), name='static')

    if docs_url:

        @app.get(docs_url, include_in_schema=False)
        async def custom_swagger_ui_html() -> HTMLResponse:
            if app.openapi_url is None:
                raise ValueError('Openapi_url is None')
            return get_swagger_ui_html(
                openapi_url=app.openapi_url,
                title=app.title + ' - Swagger UI',
                oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
                swagger_js_url=swagger_js_url,
                swagger_css_url=swagger_css_url,
            )

    @app.get(
        app.swagger_ui_oauth2_redirect_url or '/docs/oauth2-redirect',
        include_in_schema=False,
    )
    async def swagger_ui_redirect() -> HTMLResponse:
        return get_swagger_ui_oauth2_redirect_html()

    if redoc_url:

        @app.get(redoc_url, include_in_schema=False)
        async def redoc_html() -> HTMLResponse:
            if app.openapi_url is None:
                raise ValueError('Openapi_url is None')
            return get_redoc_html(
                openapi_url=app.openapi_url,
                title=app.title + ' - ReDoc',
                redoc_js_url=redoc_js_url,
            )
