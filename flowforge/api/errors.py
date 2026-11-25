"""Exception handlers producing the structured error envelope (``ErrorResponse``).

Responses carry only safe, client-facing information; never exception internals.
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from flowforge.core.errors import FlowForgeError
from flowforge.schemas.errors import ErrorBody, ErrorResponse

_HTTP_ERROR_CODES = {status.HTTP_404_NOT_FOUND: "not_found", status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed"}


def _error(status_code: int, code: str, message: str, details: list[dict[str, Any]] | None = None) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


async def _flowforge_error(request: Request, exc: FlowForgeError) -> JSONResponse:
    return _error(exc.status_code, exc.code, exc.message)


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Only location, message and type: the submitted input is not echoed back.
    details = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]
    return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", "Request validation failed", details)


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_ERROR_CODES.get(exc.status_code, "http_error")
    response = _error(exc.status_code, code, str(exc.detail))
    if exc.headers:
        response.headers.update(exc.headers)
    return response


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(FlowForgeError, _flowforge_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
