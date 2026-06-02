"""FastAPI and MCP dependency injection helpers."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from analysis.market_analysis import ChartinkAnalysisService
from auth.session_manager import SessionManager
from clients.atlas_client import AtlasClient
from clients.chartink_client import ChartinkClient
from storage.database import get_session_factory
from storage.repository import ChartinkRepository


@lru_cache
def get_session_manager() -> SessionManager:
    return SessionManager(repository=get_repository())


@lru_cache
def get_repository() -> ChartinkRepository:
    return ChartinkRepository(get_session_factory())


@lru_cache
def get_chartink_client() -> ChartinkClient:
    return ChartinkClient(
        session_manager=get_session_manager(),
        repository=get_repository(),
    )


@lru_cache
def get_analysis_service() -> ChartinkAnalysisService:
    return ChartinkAnalysisService(
        client=get_chartink_client(),
        repository=get_repository(),
    )


@lru_cache
def get_atlas_client() -> AtlasClient:
    return AtlasClient(
        session_manager=get_session_manager(),
        repository=get_repository(),
    )


ChartinkClientDep = Annotated[ChartinkClient, Depends(get_chartink_client)]
AtlasClientDep = Annotated[AtlasClient, Depends(get_atlas_client)]
RepositoryDep = Annotated[ChartinkRepository, Depends(get_repository)]
AnalysisDep = Annotated[ChartinkAnalysisService, Depends(get_analysis_service)]
SessionManagerDep = Annotated[SessionManager, Depends(get_session_manager)]
