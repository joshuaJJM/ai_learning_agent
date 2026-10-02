"""好学 / Personal Learning Agent —— 后端入口。

启动：
    cd backend
    .venv\\Scripts\\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 17283
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import __version__, db, knowledge
from .config import get_settings
from .errors import install_error_handlers
from .question_bank import get_bank
from .routers import ALL_ROUTERS
from .routers import demo as demo_router
from .schemas import HealthResponse
from .services import book_service, tag_service
from .services.llm import get_llm, shutdown_llm

logger = logging.getLogger("haoxue")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

STARTED_AT = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db.init_db()
    books = book_service.seed_books()
    bank = get_bank()
    stats = bank.stats()
    settings = get_settings()

    logger.info(
        "存储: %s (%s)", db.storage_label(), "MySQL" if settings.use_mysql else "SQLite"
    )
    logger.info("图书: %d 本", books)
    logger.info("题库: %d 个 bank / %d 道题", stats["bank_count"], stats["question_count"])
    logger.info(
        "知识点: %d 个 | 标签: %d 个",
        len(knowledge.all_points()),
        len(tag_service.tag_universe()),
    )
    for warning in bank.report.warnings:
        logger.warning("题库告警: %s", warning)
    for error in bank.report.errors:
        logger.error("题库错误: %s", error)

    # 清单漂移检查：代码里的知识点、seed/knowledge_points.json、题库的 tags，
    # 三边必须一致。题库换代时吃过这个亏（题库 17 个、代码 7 个，46 道题挂不上）。
    for problem in knowledge.validate_against_seed_file():
        logger.warning("知识点清单不一致: %s", problem)
    seed_extra = set(tag_service.tag_universe()) - {
        kp.name for kp in knowledge.all_points()
    }
    if seed_extra:
        logger.warning(
            "有 %d 个标签不对应任何知识点名称（按设计 tags 应是知识点 name 的镜像）: %s",
            len(seed_extra),
            ", ".join(sorted(seed_extra)[:5]),
        )
    logger.info(
        "模型: %s (%s) | VLM: %s",
        settings.llm_model,
        "已配置" if get_llm().configured else "Mock 模式",
        settings.vlm_model,
    )
    yield
    await shutdown_llm()


app = FastAPI(
    title="好学 · Personal Learning Agent API",
    description=(
        "Observe → Understand → Decide → Teach → Practice → Evaluate → Update → Re-plan\n\n"
        "后端是整个系统的 Source of Truth：用户、Knowledge State、Mastery、Evidence、"
        "错题库、Tutor Session、练习记录都存在服务端。iOS 不自行计算掌握度。"
    ),
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def attach_request_id(request: Request, call_next: Any) -> Any:
    request.state.request_id = (
        request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    )
    started = time.time()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Response-Time-Ms"] = str(int((time.time() - started) * 1000))
    return response


install_error_handlers(app)

for router in ALL_ROUTERS:
    app.include_router(router)
app.include_router(demo_router.router)

# 题目/作业图片。注意：图片属于学习数据，演示环境用固定目录，
# 生产环境应改为带鉴权的对象存储 + 生命周期策略。
MEDIA_DIR = db.BACKEND_ROOT / "data" / "uploads"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")


@app.get("/health", response_model=HealthResponse, tags=["meta"])
@app.get("/api/v1/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    settings = get_settings()
    bank = get_bank()
    stats = bank.stats()
    llm = get_llm()
    degraded = bool(bank.report.errors) or not llm.configured
    return HealthResponse(
        status="degraded" if degraded else "ok",
        version=__version__,
        llm_mode=llm.mode,  # type: ignore[arg-type]
        llm_model=settings.llm_model,
        vlm_model=settings.vlm_model,
        database=db.storage_label(),
        bank_count=stats["bank_count"],
        question_count=stats["question_count"],
        uptime_seconds=round(time.time() - STARTED_AT, 2),
    )


@app.get("/", tags=["meta"])
async def root() -> dict[str, Any]:
    return {
        "name": "好学 · Personal Learning Agent API",
        "version": __version__,
        "docs": "/docs",
        "api_prefix": "/api/v1",
        "health": "/health",
        "hint": (
            "所有业务接口都在 /api/v1 下。不带 Authorization 头时会自动使用 "
            "Demo 用户，方便前端联调。"
        ),
    }
