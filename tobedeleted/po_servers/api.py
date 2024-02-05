from fastapi import APIRouter
from ..po_servers.endpoints import analysis, analysis_info

api_router = APIRouter()

api_router.include_router(analysis.router, prefix="/analysisinfo", tags=["AnalysisInfo"])
api_router.include_router(analysis_info.router, prefix="/analysis", tags=["Analysis"])