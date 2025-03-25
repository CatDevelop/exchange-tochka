import json
import time
import traceback
from typing import Any, Callable
from uuid import uuid4

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.logs.logs import error_logger, info_logger


class TraceLogger:
    def __init__(self, request_id: int | str, logger: Callable[[str], None]) -> None:
        self.request_id = request_id
        self.logger = logger

    def __call__(self, string: str) -> None:
        self.logger(self.__create_string(string))

    def __create_string(self, string: str) -> str:
        return f'[request_id={self.request_id}] {string}'

    @staticmethod
    def get_request_id(request: Request) -> str:
        if 'X-Request-ID' in request.headers:
            return request.headers['X-Request-ID']
        return str(uuid4())


class LoggingMiddleware(BaseHTTPMiddleware):
    async def __ignore_request(self, request: Request, call_next: Any) -> bool | str:
        matched_route = None
        for route in request.app.routes:
            if isinstance(route, APIRoute) and route.path == request.url.path:
                matched_route = route
                break
        if matched_route and getattr(matched_route.endpoint, '_no_password', False):
            return 'no_password'
        if matched_route and getattr(matched_route.endpoint, '_no_log', False):
            return True
        return False

    async def delete_password(
        self, body: bytes, trace_error_logger: Callable[[str], None]
    ) -> bytes:
        body_str = body.decode('utf-8')
        try:
            request_body = json.loads(body_str)
        except json.JSONDecodeError:
            trace_error_logger('Failed to decode request body as JSON.')
            request_body = {}
        if 'password' in request_body:
            request_body.pop('password')
        json_bytes = json.dumps(request_body).encode('utf-8')
        return json_bytes

    async def __general_response(
        self,
        request: Request,
        call_next: Any,
        trace_info_logger: TraceLogger,
        trace_error_logger: TraceLogger,
        body: str,
    ) -> Response:
        response = await call_next(request)

        trace_info_logger(f'Request completed: {request.method} {request.url}')
        trace_info_logger(f'Status code: {response.status_code}')

        response_body = b''
        async for chunk in response.body_iterator:
            response_body += chunk

        if response.status_code != 200 and response.status_code != 201:
            trace_error_logger(f'Request body: {body}')
            trace_error_logger(f'Response body: {response_body.decode()}')

        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )

    async def __handle_http_exception(
        self, e: HTTPException, trace_error_logger: TraceLogger
    ) -> Response:
        trace_error_logger(f"HTTPException occurred: {str(e.detail)}")
        trace_error_logger(f"Traceback: {traceback.format_exc()}")
        return JSONResponse(status_code=e.status_code, content={'detail': e.detail})

    async def __handle_general_exception(
        self,
        e: Exception,
        request: Request,
        trace_error_logger: TraceLogger,
    ) -> Response:
        trace_error_logger(f'Exception occurred: {str(e)}')
        trace_error_logger(f'Traceback: {traceback.format_exc()}')
        trace_error_logger(f'Request failed: {request.method} {request.url}')

        return JSONResponse(
            status_code=500, content={'detail': 'Internal Server Error'}
        )

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        ignore_result = await self.__ignore_request(request, call_next)
        if ignore_result and ignore_result != 'no_password':
            response: Response = await call_next(request)
            return response

        request_id = TraceLogger.get_request_id(request=request)
        trace_info_logger = TraceLogger(request_id=request_id, logger=info_logger.info)
        trace_error_logger = TraceLogger(
            request_id=request_id, logger=error_logger.error
        )
        start_time = time.time()
        trace_info_logger(f'Incoming request: {request.method} {request.url}')
        body = await request.body()
        if ignore_result == 'no_password':
            body = await self.delete_password(body, trace_error_logger)

        decoded_body = ''
        if body:
            try:
                decoded_body = body.decode('utf-8')
                trace_info_logger(f'Request body: {decoded_body}')
            except UnicodeDecodeError:
                trace_info_logger("Request body: {\n  'body': Объект в base64\n}")

        try:
            return await self.__general_response(
                request=request,
                call_next=call_next,
                trace_info_logger=trace_info_logger,
                trace_error_logger=trace_error_logger,
                body=decoded_body,
            )
        except HTTPException as e:
            return await self.__handle_http_exception(
                e=e, trace_error_logger=trace_error_logger
            )

        except Exception as e:
            return await self.__handle_general_exception(
                e=e, request=request, trace_error_logger=trace_error_logger
            )
        finally:
            process_time = time.time() - start_time
            trace_info_logger(f'Process time: {process_time:.4f} seconds')
