"""好学 / Personal Learning Agent —— 后端入口。

启动：
    cd backend
    .venv\\Scripts\\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 17283
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager, suppress
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
from .services import book_service, homework_service, tag_service
from .services.llm import get_llm, shutdown_llm

logger = logging.getLogger("haoxue")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

STARTED_AT = time.time()

#: 超过这个毫秒数就在耗时日志里标 SLOW，方便直接 grep 出来看。
SLOW_REQUEST_MS = 3000


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
        "模型: %s (%s) | VLM: %s | 备用: %s",
        settings.llm_model,
        "已配置" if get_llm().configured else "Mock 模式",
        settings.vlm_model,
        (
            f"{settings.backup_llm_model} @ {settings.backup_llm_base_url}（已配置）"
            if get_llm().backup_configured
            else "未配置"
        ),
    )

    # 终止态对账：进程刚起来，不可能有分析在跑，所以遗留的非终态记录
    # 一定是上一次进程死掉时留下的孤儿。不清理的话它们会永久停在
    # processing，前端一直转圈（线上 batch 5 就是这样）。
    homework_service.recover_interrupted_analyses()

    # 看门狗：进程活着但任务卡死时兜底，保证不会永久 processing
    reaper = asyncio.create_task(_watchdog())
    logger.info(
        "看门狗已启动：每 %d 秒检查一次，超过 %d 分钟无进展的分析判为失败",
        WATCHDOG_INTERVAL_SECONDS,
        homework_service.STALE_ANALYSIS_SECONDS // 60,
    )

    try:
        yield
    finally:
        reaper.cancel()
        with suppress(asyncio.CancelledError):
            await reaper
        await shutdown_llm()


#: 看门狗扫描间隔。分析要几分钟才可能真的卡住，没必要查太勤。
WATCHDOG_INTERVAL_SECONDS = 60


async def _watchdog() -> None:
    """周期性把"太久没动静"的分析判为失败。

    只保证**一定进终态**，不尝试续跑 —— 分析无法从中途恢复，
    让学生对着转圈等，远不如给一个明确的 failed + 重试按钮。
    """
    while True:
        try:
            await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
            await asyncio.to_thread(homework_service.reap_stale_analyses)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 看门狗自己不能死
            logger.exception("看门狗扫描出错")


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
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Response-Time-Ms"] = str(elapsed_ms)

    # 每次请求都记一条耗时日志。
    #
    # uvicorn 自带的 access log 只有方法/路径/状态码，**没有耗时** ——
    # 排查"为什么这次上传这么久"时完全看不出时间花在哪，只能靠猜。
    # 这里补上毫秒数，并标出慢请求，方便直接 grep。
    #
    # 注意：流式（SSE）响应下这个耗时是**首字节时间**，不是整条流的总时长
    # （响应体在 call_next 返回之后才继续推）。
    slow = " SLOW" if elapsed_ms >= SLOW_REQUEST_MS else ""
    logger.info(
        "%s %s -> %s %dms%s rid=%s",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        slow,
        request.state.request_id,
    )
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
        backup_llm_model=settings.backup_llm_model,
        backup_llm_configured=llm.backup_configured,
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
