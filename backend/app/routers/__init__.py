"""HTTP 路由层。只做参数校验与序列化，业务逻辑在 services/。"""

from . import (  # noqa: F401
    ai,
    auth,
    books,
    home,
    homework,
    knowledge,
    practice,
    tags,
    tutor,
    wrong_questions,
)

ALL_ROUTERS = (
    auth.router,
    home.router,
    homework.router,
    knowledge.router,
    wrong_questions.router,
    tutor.router,
    practice.router,
    tags.router,
    books.router,
    books.entitlements_router,
    ai.router,
)
