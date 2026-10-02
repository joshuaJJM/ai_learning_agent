"""针对性练习。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status

from .. import repositories
from ..dependencies import (
    current_user,
    idempotency_key_header,
    resolve_idempotency_key,
)
from ..errors import (
    IDEMPOTENCY_CONFLICT,
    NO_QUESTIONS_AVAILABLE,
    QUESTION_NOT_IN_SESSION,
    SESSION_COMPLETED,
    SESSION_NOT_FOUND,
    ApiError,
)
from ..schemas import (
    PracticeAnswerRequest,
    PracticeAnswerResponse,
    PracticeQuestion,
    PracticeSessionCreateRequest,
    PracticeSessionResponse,
)
from ..services import practice_service

router = APIRouter(prefix="/api/v1/practice", tags=["practice"])


@router.post(
    "/sessions",
    response_model=PracticeSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    payload: PracticeSessionCreateRequest,
    user: dict[str, Any] = Depends(current_user),
    header_key: str | None = Depends(idempotency_key_header),
) -> PracticeSessionResponse:
    endpoint = "POST /api/v1/practice/sessions"
    raw_key = resolve_idempotency_key(header_key, payload.client_request_id)
    idem_key = f"practice-create:{user['user_id']}:{raw_key}" if raw_key else None

    if idem_key and not repositories.reserve_idempotency(
        idem_key, user["user_id"], endpoint
    ):
        cached = repositories.get_idempotent_response(idem_key)
        if cached:
            return PracticeSessionResponse(**cached)
        raise ApiError(IDEMPOTENCY_CONFLICT, "同一个请求正在处理中，请稍后重试")

    # 不指定知识点时走**标签推荐**（把所有标签按分数升序，取最弱标签的题）。
    # 指定了知识点则沿用原来的知识点内选题逻辑。
    if payload.knowledge_point_id:
        session = practice_service.create_session(
            user["user_id"],
            knowledge_point_id=payload.knowledge_point_id,
            difficulty=payload.difficulty,
            book_id=payload.book_id,
            count=payload.count,
        )
    else:
        session = practice_service.create_tag_session(
            user["user_id"], count=payload.count, book_id=payload.book_id
        )

    body = practice_service.session_response(session)
    if idem_key:
        repositories.put_idempotent_response(idem_key, user["user_id"], endpoint, body)
    return PracticeSessionResponse(**body)


@router.get("/sessions/{session_id}", response_model=PracticeSessionResponse)
async def get_session(
    session_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> PracticeSessionResponse:
    session = repositories.get_practice_session(session_id)
    if session is None or session.get("user_id") != user["user_id"]:
        raise ApiError(SESSION_NOT_FOUND, "练习 Session 不存在")
    return PracticeSessionResponse(**practice_service.session_response(session))


@router.get(
    "/sessions/{session_id}/next",
    response_model=PracticeQuestion,
    summary="取下一题（响应中不含答案）",
)
async def next_question(
    session_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> PracticeQuestion:
    session = repositories.get_practice_session(session_id)
    if session is None or session.get("user_id") != user["user_id"]:
        raise ApiError(SESSION_NOT_FOUND, "练习 Session 不存在")
    question = practice_service.current_question(session)
    if question is None:
        raise ApiError(NO_QUESTIONS_AVAILABLE, "这一组题已经做完了")
    return PracticeQuestion(**question)


@router.post(
    "/sessions/{session_id}/answers",
    response_model=PracticeAnswerResponse,
    summary="提交答案，服务器判定并更新掌握度",
)
async def submit_answer(
    session_id: str,
    payload: PracticeAnswerRequest,
    user: dict[str, Any] = Depends(current_user),
    header_key: str | None = Depends(idempotency_key_header),
) -> PracticeAnswerResponse:
    endpoint = f"POST /api/v1/practice/sessions/{session_id}/answers"
    raw_key = resolve_idempotency_key(header_key, payload.client_request_id)
    idem_key = f"practice:{user['user_id']}:{session_id}:{raw_key}" if raw_key else None

    # **先占位再干活**。只「先查缓存」的话，两个并发请求会同时看到未命中，
    # 于是各写一次 Evidence、各动一次标签 —— 掌握度被算两遍。
    if idem_key and not repositories.reserve_idempotency(
        idem_key, user["user_id"], endpoint
    ):
        cached = repositories.get_idempotent_response(idem_key)
        if cached:
            # 缓存里存的是首次的响应（replayed=False），回放时必须标成 true，
            # 否则客户端无法区分「这是我刚提交的」和「这是重放的旧结果」。
            # 练习的另一条回放路径（按 question_id 命中）本来就是 true，
            # 两条路径的语义要一致。
            return PracticeAnswerResponse(**{**cached, "replayed": True})
        # 占位还在：另一个请求正在处理同一件事
        raise ApiError(
            IDEMPOTENCY_CONFLICT, "同一个请求正在处理中，请稍后重试"
        )

    try:
        result = practice_service.submit_answer(
            user["user_id"],
            session_id,
            question_id=payload.question_id,
            selected_key=payload.selected_key,
            answer_text=payload.answer_text,
        )
    except PermissionError as exc:
        # 题目不属于本 Session —— 拒绝，避免凭空写 Evidence / 动标签
        if idem_key:
            repositories.release_idempotency(idem_key)
        raise ApiError(
            QUESTION_NOT_IN_SESSION, "这道题不属于当前这次练习"
        ) from exc
    except LookupError as exc:
        if idem_key:
            repositories.release_idempotency(idem_key)
        if str(exc) == "'question'":
            raise ApiError("NOT_FOUND", "题目不存在") from exc
        raise ApiError(SESSION_NOT_FOUND, "练习 Session 不存在") from exc
    except RuntimeError as exc:
        if idem_key:
            repositories.release_idempotency(idem_key)
        raise ApiError(SESSION_COMPLETED, "这次练习已经结束了") from exc

    if idem_key:
        repositories.put_idempotent_response(
            idem_key, user["user_id"], endpoint, result
        )
    return PracticeAnswerResponse(**result)
