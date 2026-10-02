"""标签计分与基于标签的练习推荐。

规则（按需求，刻意做得简单，后续可能改）：

  1. 每个用户的每个标签初始分数为 0。
  2. 每答一道题：**全对则该题的所有标签 +1，否则 -1**（不做部分给分）。
  3. 推荐习题时：把所有标签从小到大排序，返回「包含分数最低的那个标签」的题目。

第 3 条面对的是多对多关系（一道题有多个标签，一个标签属于多道题），
所以除了"必须包含最弱标签"这条硬规则，还需要一个二级排序。这里的设计是：

  二级：**该题所有标签的分数之和**升序。
        一道题覆盖了两个都很弱的标签（-3 和 -3，和 = -6）会比只覆盖一个
        （-3）排得更前 —— 练一道题补两个薄弱点，性价比更高。
        反之，如果它另一个标签已经很强（+10），和会变大，自然排到后面。
  三级：最近做过的题降权（避免连着出同一道）。
  四级：题号，保证结果可复现（同样的输入永远给同样的推荐）。

整套逻辑是纯算术 + 排序，不调用任何模型，单次推荐是微秒级。
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .. import db, repositories, tags as tag_vocab
from ..question_bank import get_bank

# 最近做过多少天内的题，在推荐里降权（不是硬排除，保证总有题可推荐）
RECENT_COOLDOWN_DAYS = 5


# ---------------------------------------------------------------------------
# 标签宇宙
# ---------------------------------------------------------------------------

def bank_tags_by_question() -> dict[str, tuple[str, ...]]:
    """题库里每道题的标签。"""
    return {q.id: tuple(q.tags) for q in get_bank().all()}


def question_tags(question_id: str) -> tuple[str, ...]:
    """取一道题的标签。题库优先，题库里没有的（OCR 上传的）查数据库。"""
    question = get_bank().get(question_id)
    if question is not None:
        return tuple(question.tags)
    doc = db.get_doc("questions", "question_id", question_id)
    if not doc:
        return ()
    raw = doc.get("tags") or []
    if not isinstance(raw, list):
        return ()
    return tuple(tag_vocab.normalize(t) for t in raw if tag_vocab.normalize(t))


def tag_universe() -> tuple[str, ...]:
    """全部标签种类。

    = 配置表里的标签 ∪ 题库里出现的标签。
    这样配置表没补全时，题库里的标签也不会被漏掉。
    """
    seen: dict[str, None] = {}
    for tag in tag_vocab.declared_tags():
        if tag_vocab.is_valid(tag):
            seen.setdefault(tag, None)
    for tags in bank_tags_by_question().values():
        for tag in tags:
            if tag_vocab.is_valid(tag):
                seen.setdefault(tag, None)
    return tuple(seen)


# ---------------------------------------------------------------------------
# 计分
# ---------------------------------------------------------------------------

def initialize_scores(user_id: str) -> int:
    """把所有尚未出现过的标签以 0 分建档。"""
    tags = tag_universe()
    existing = set(repositories.all_tag_scores(user_id))
    missing = [t for t in tags if t not in existing]
    if not missing:
        return 0
    return repositories.ensure_tag_scores(user_id, missing)


def scores(user_id: str) -> dict[str, int]:
    """全部标签的分数（没记录过的按 0）。"""
    stored = repositories.all_tag_scores(user_id)
    return {tag: stored.get(tag, 0) for tag in tag_universe()}


def ranked_tags(user_id: str) -> list[dict[str, Any]]:
    """标签按分数升序（同分按名称，保证稳定）。"""
    current = scores(user_id)
    ordered = sorted(current.items(), key=lambda kv: (kv[1], kv[0]))
    return [{"tag": tag, "score": score} for tag, score in ordered]


def apply_answer(user_id: str, question_id: str, is_correct: bool) -> dict[str, Any]:
    """按答题结果给该题的所有标签计分。返回本次变动（便于回显与测试）。"""
    question_tag_list = question_tags(question_id)
    delta = 1 if is_correct else -1
    if question_tag_list:
        repositories.bump_tag_scores(user_id, question_tag_list, delta)
    return {
        "question_id": question_id,
        "is_correct": is_correct,
        "delta": delta,
        "tags": list(question_tag_list),
    }


def apply_answers(
    user_id: str, results: Iterable[tuple[str, bool]]
) -> list[dict[str, Any]]:
    """批量计分（一次作业里有多道题时用）。"""
    return [apply_answer(user_id, qid, ok) for qid, ok in results]


def tags_for_knowledge_point(kp_id: str) -> tuple[str, ...]:
    """知识点对应的标签。

    Tutor 的题目来自教学脚本而不是题库，没有题目 id，但有关联知识点。
    当前题库的 tags 与知识点同名，所以按名字反查；
    等标签体系与知识点彻底解耦后，这里会返回空，Tutor 自然就不参与标签计分。
    """
    from .. import knowledge

    point = knowledge.get_point(kp_id)
    if point is None:
        return ()
    return (point.name,) if point.name in set(tag_universe()) else ()


def apply_for_knowledge_point(
    user_id: str, kp_id: str, is_correct: bool
) -> dict[str, Any] | None:
    """按知识点给对应标签计分（Tutor 用）。"""
    tag_list = tags_for_knowledge_point(kp_id)
    if not tag_list:
        return None
    delta = 1 if is_correct else -1
    repositories.bump_tag_scores(user_id, tag_list, delta)
    return {
        "knowledge_point_id": kp_id,
        "is_correct": is_correct,
        "delta": delta,
        "tags": list(tag_list),
    }


# ---------------------------------------------------------------------------
# 推荐
# ---------------------------------------------------------------------------

def _recent_question_ids(user_id: str, days: int = RECENT_COOLDOWN_DAYS) -> set[str]:
    from datetime import timedelta

    since = db.to_iso(db.utcnow() - timedelta(days=days))
    rows = db.query_all(
        "SELECT DISTINCT question_id FROM evidence "
        "WHERE user_id = ? AND created_at >= ? AND question_id IS NOT NULL",
        [user_id, since],
    )
    return {str(row["question_id"]) for row in rows if row["question_id"]}


def _candidate_key(
    question_tags_of: dict[str, tuple[str, ...]],
    scores_map: dict[str, int],
    recent: set[str],
):
    def key(question_id: str) -> tuple[int, int, str]:
        question_tag_list = question_tags_of.get(question_id, ())
        total = sum(scores_map.get(t, 0) for t in question_tag_list)
        # 最近做过的排到后面（不是排除，保证一定有题）
        penalty = 1 if question_id in recent else 0
        return (penalty, total, question_id)

    return key


def pick_questions(
    user_id: str,
    limit: int = 1,
    exclude_question_ids: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """挑练习题。

    返回 `[{tag, tag_score, question_id}]`，按「最弱标签优先」的顺序。
    一道题只会被选中一次。
    """
    current = scores(user_id)
    if not current:
        return []

    ordered = sorted(current.items(), key=lambda kv: (kv[1], kv[0]))
    by_question = bank_tags_by_question()
    recent = _recent_question_ids(user_id)
    key = _candidate_key(by_question, current, recent)

    used: set[str] = set(exclude_question_ids)
    picked: list[dict[str, Any]] = []

    for tag, tag_score in ordered:
        if len(picked) >= limit:
            break
        candidates = [
            qid
            for qid, q_tags in by_question.items()
            if tag in q_tags and qid not in used
        ]
        if not candidates:
            continue
        candidates.sort(key=key)
        chosen = candidates[0]
        used.add(chosen)
        picked.append(
            {
                "tag": tag,
                "tag_score": tag_score,
                "question_id": chosen,
                "question_tags": list(by_question.get(chosen, ())),
            }
        )

    return picked


def explain(user_id: str) -> dict[str, Any]:
    """给调试与文档用的一份快照。"""
    ordered = ranked_tags(user_id)
    return {
        "tag_count": len(ordered),
        "weakest": ordered[0] if ordered else None,
        "strongest": ordered[-1] if ordered else None,
        "tags": ordered,
    }
