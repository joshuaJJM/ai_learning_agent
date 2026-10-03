"""标签计分与基于标签的练习推荐。

**统计模型（v2）**

v1 是「答对 +1 / 答错 −1」的裸计数器，有个致命缺陷：

    一个标签 5 对 5 错 → 0
    一个标签从没练过   → 0        ← 两者无法区分

而推荐正是取「分数最低的标签」，于是"练得稀烂"和"完全没碰过"被同等对待。
除此之外还有：不同标签之间不可比、没有难度加权、没有时间衰减、没有不确定度。

v2 改成 **Beta 后验 + 悲观下界**：

    每个标签维护 Beta(α, β)，用与掌握度**完全相同**的一套权重更新
    （对错得分 × 难度 × 来源可信度 × 时间衰减），从 Evidence 现算。

    推荐分不取后验均值，而取「均值往下压一个标准差」：

        priority = mastery − sd        sd = sqrt(αβ / ((α+β)²(α+β+1)))

    一句话：**证据越少，压得越狠。**

    标签状态          均值    标准差   priority
    2 对 8 错         0.25    0.12     0.13    ← 最该练
    从没练过          0.50    0.29     0.21    ← 次之（探索）
    5 对 5 错         0.50    0.14     0.36    ← 不急
    9 对 1 错         0.83    0.10     0.73    ← 最后

这样 `5 对 5 错`(0.36) 和 `从没练过`(0.21) 终于分开了，
而且排序天然是经典的 explore/exploit：练得差的优先、没碰过的其次、
平衡的不急、掌握好的最后。

**对外仍然给 0–100 的整数 `score`（= priority × 100），升序 = 最弱在前**，
所以排序方向与 v1 一致，前端不必改。

推荐的多对多排序规则（二级/三级/四级）沿用 v1，只有"分数"换了定义。

整套逻辑是纯算术 + 排序，不调用任何模型，单次推荐是微秒级。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .. import db, repositories, tags as tag_vocab
from ..mastery import (
    CONFIDENCE_W0,
    OUTCOME_SCORES,
    PRIOR_ALPHA,
    PRIOR_BETA,
    evidence_weight,
    normalize_outcome,
)
from ..question_bank import get_bank

# 最近做过多少天内的题，在推荐里降权（不是硬排除，保证总有题可推荐）
RECENT_COOLDOWN_DAYS = 5

#: 悲观下界往下压几个标准差。
#: 1.0 时：没练过的标签 priority≈0.21、练了 10 次的一步就能拉开差距。
#: 调大 → 更偏向"探索没练过的"；调小 → 更偏向"专攻已知的弱项"。
PESSIMISM_Z = 1.0


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
# 统计
# ---------------------------------------------------------------------------

@dataclass
class TagStat:
    """一个标签的 Beta 后验。"""

    tag: str
    alpha: float = PRIOR_ALPHA
    beta: float = PRIOR_BETA
    attempts: int = 0
    total_weight: float = 0.0

    @property
    def mastery(self) -> float:
        """后验均值 —— 「这个标签大概掌握到什么程度」。"""
        return self.alpha / (self.alpha + self.beta)

    @property
    def sd(self) -> float:
        """后验标准差 —— 证据越少越大。"""
        total = self.alpha + self.beta
        return math.sqrt(
            (self.alpha * self.beta) / (total * total * (total + 1.0))
        )

    @property
    def priority(self) -> float:
        """推荐用的**悲观估计**：均值往下压一个标准差。

        没练过 → 均值 0.5 但 sd 大 → 压到 0.21（会被推荐去探索）
        练得差 → 均值低且已确定 → 0.13（优先推荐）
        掌握好 → 均值高且已确定 → 0.73（不急着练）
        """
        return max(0.0, min(1.0, self.mastery - PESSIMISM_Z * self.sd))

    @property
    def score(self) -> int:
        """对外契约：0–100 的整数，**升序 = 最弱在前**（与 v1 方向一致）。"""
        return int(round(self.priority * 100))

    @property
    def confidence(self) -> float:
        """对当前估计有多确定（证据总权重越大越高）。"""
        return round(1.0 - math.exp(-self.total_weight / CONFIDENCE_W0), 4)


def tags_of_evidence(record: Any) -> tuple[str, ...]:
    """一条 Evidence 应该记到**哪个**标签上。

    答案：**它自己那个知识点**对应的标签。

    为什么不是「该题的全部标签」—— 一道题有几个知识点就有几条 Evidence，
    若每条都去记该题的全部标签，一道 2 个知识点的题答一次，
    每个标签会被记 **2 次**（实测确认过：一次作答 attempts 直接变成 2）。

    v1 是「每道题调一次 bump，传该题的全部标签」，所以每题每标签恰好一次。
    按知识点映射天然就是每题每标签一次，而且顺带能用上
    **每个知识点自己的相关度**（`confidence`）当权重 —— 比 v1 更准。

    当前题库的 tags 与知识点 name 逐字一致，所以这个映射是精确的。
    """
    from .. import knowledge

    kp_id = getattr(record, "kp_id", "") or ""
    point = knowledge.get_point(kp_id)
    if point is None:
        return ()
    return (point.name,) if point.name in set(tag_universe()) else ()


def tag_stats(user_id: str) -> dict[str, TagStat]:
    """全部标签的后验统计（从 Evidence 现算，不落表）。

    为什么现算而不是维护计数器：与掌握度同源（"Evidence 是唯一事实来源"），
    少一张表，也就少一类「计数器与历史对不上」的 bug。
    证据量在几百条量级，聚合开销可忽略。
    """
    stats = {tag: TagStat(tag) for tag in tag_universe()}
    records = repositories.evidence_records(user_id)
    if not records:
        return stats

    now = db.utcnow()
    for record in records:
        tags = tags_of_evidence(record)
        if not tags:
            continue
        outcome = OUTCOME_SCORES.get(normalize_outcome(record.outcome), 0.5)
        weight = evidence_weight(record, now)
        if weight <= 0:
            continue
        for tag in tags:
            stat = stats.get(tag)
            if stat is None:
                continue
            stat.alpha += weight * outcome
            stat.beta += weight * (1.0 - outcome)
            stat.attempts += 1
            stat.total_weight += weight
    return stats


def initialize_scores(user_id: str) -> int:
    """兼容旧接口。

    标签统计现在从 Evidence 现算，不再需要「建档」。
    保留这个函数是为了不打断既有调用方，它现在什么都不做。
    """
    return 0


def scores(user_id: str) -> dict[str, int]:
    """全部标签的分数（0–100，升序 = 最弱在前）。"""
    return {tag: stat.score for tag, stat in tag_stats(user_id).items()}


def detailed_scores(user_id: str) -> list[dict[str, Any]]:
    """带完整统计的标签列表，按 score 升序（同分按名称，保证稳定）。"""
    stats = tag_stats(user_id)
    ordered = sorted(stats.values(), key=lambda s: (s.score, s.tag))
    return [
        {
            "tag": stat.tag,
            "score": stat.score,
            "mastery": round(stat.mastery, 4),
            "confidence": stat.confidence,
            "attempts": stat.attempts,
        }
        for stat in ordered
    ]


def ranked_tags(user_id: str) -> list[dict[str, Any]]:
    """标签按分数升序（同分按名称，保证稳定）。"""
    return detailed_scores(user_id)


def apply_answer(
    user_id: str,
    question_id: str,
    is_correct: bool,
    *,
    before: dict[str, TagStat] | None = None,
) -> dict[str, Any]:
    """回显本次作答对相关标签的影响。

    **不再写库** —— 标签统计从 Evidence 现算，而 Evidence 在
    `apply_evidence` 那一步已经写好了。这里只负责把"现在是什么样"
    和"相对作答前变了多少"算出来给前端。

    `before` 是作答前的快照（调用方在写 Evidence 之前取），
    不传就只有当前值、没有变化量。
    """
    tag_list = question_tags(question_id)
    current = tag_stats(user_id)
    scores_now = {tag: current[tag].score for tag in tag_list if tag in current}

    deltas: dict[str, int] = {}
    if before:
        for tag in tag_list:
            if tag in current and tag in before:
                deltas[tag] = current[tag].score - before[tag].score

    return {
        "question_id": question_id,
        "is_correct": is_correct,
        "tags": list(tag_list),
        "tag_scores": scores_now,
        "tag_deltas": deltas,
    }


def apply_answers(
    user_id: str, results: Iterable[tuple[str, bool]]
) -> list[dict[str, Any]]:
    """批量回显（一次作业里有多道题时用）。"""
    current = tag_stats(user_id)
    return [
        apply_answer(user_id, qid, ok, before=current) for qid, ok in results
    ]


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
    user_id: str,
    kp_id: str,
    is_correct: bool,
    *,
    before: dict[str, TagStat] | None = None,
) -> dict[str, Any] | None:
    """按知识点回显对应标签的影响（Tutor 用）。同样不写库。"""
    tag_list = tags_for_knowledge_point(kp_id)
    if not tag_list:
        return None
    current = tag_stats(user_id)
    deltas = {
        tag: current[tag].score - before[tag].score
        for tag in tag_list
        if before and tag in current and tag in before
    }
    return {
        "knowledge_point_id": kp_id,
        "is_correct": is_correct,
        "tags": list(tag_list),
        "tag_scores": {tag: current[tag].score for tag in tag_list if tag in current},
        "tag_deltas": deltas,
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

    返回 `[{tag, tag_score, question_id}]`，**整组题尽量都出自最弱的那个标签**
    （出不满才顺延到下一个标签），这样 `target_tag` 表达的「本次专练某一标签」才成立。
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

    # 先把这个标签名下的题**出满**，出不满才轮到下一个标签。
    #
    # 早先的写法是「每个标签只取一道就换下一个」，于是 count=5 会拿到
    # 5 个不同标签的题，和 target_tag 的语义矛盾。
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
        for chosen in candidates:
            if len(picked) >= limit:
                break
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
