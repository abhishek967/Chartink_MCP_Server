"""Map domain errors to HTTP responses (avoid opaque 500s on Render)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from auth.session_manager import AuthenticationError
from clients.atlas_client import AtlasClientError
from clients.chartink_client import ChartinkClientError


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthenticationError)
    async def authentication_error_handler(
        _request: Request, exc: AuthenticationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": str(exc), "authenticated": False},
        )

    @app.exception_handler(ChartinkClientError)
    async def chartink_client_error_handler(
        _request: Request, exc: ChartinkClientError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"detail": str(exc)},
        )

    @app.exception_handler(AtlasClientError)
    async def atlas_client_error_handler(
        _request: Request, exc: AtlasClientError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"detail": str(exc)},
        )
