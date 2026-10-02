"""VLM 试卷识别层：图片 → 结构化题目。

职责边界（这是刻意的设计）：
  - VLM 只负责**看**：识别题干、选项、学生作答、以及它自己算出的正确答案。
  - 服务端负责**判**：正确答案优先以题库为准，知识点映射必须落在我们的
    知识点树上，错误类型必须落在我们的分类法里。

理由：模型不认识 `math.derivative.monotonicity` 这种 ID，也不知道我们的
错误分类。让它自由发挥，输出就没法进 Knowledge Engine。
把"看"和"判"分开，换模型时判定逻辑不会跟着漂。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Sequence

from .. import knowledge
from ..config import get_settings
from ..question_bank import BankQuestion, get_bank, stem_fingerprint  # noqa: F401
from .llm import LlmClient, LlmUnavailable, build_user_message, get_llm

# 题干相似度达到这个阈值，就认为是题库里的同一道题
BANK_MATCH_THRESHOLD = 0.72

# 没有题库命中时，用关键词兜底推断知识点（ID 必须是 knowledge_points 清单里的）
_KEYWORD_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("极值", "极大", "极小"),
        "math.derivative.extrema",
    ),
    (
        ("最大值", "最小值", "最值", "闭区间"),
        "math.derivative.absolute_extrema",
    ),
    (
        ("单调", "递增区间", "递减区间", "增函数", "减函数"),
        "math.derivative.monotonicity",
    ),
    (
        ("取值范围", "恒成立", "求参数", "求 a", "求实数"),
        "math.derivative.monotonicity_parameter",
    ),
    (
        ("零点", "根的个数", "两个根", "三个根", "方程"),
        "math.derivative.monotonicity_applications",
    ),
    (
        ("奇函数", "偶函数", "奇偶"),
        "math.function.parity_and_monotonicity",
    ),
)


@dataclass
class RawQuestion:
    """VLM 产出的原始题目，尚未经过服务端判定。"""

    question_number: str
    stem: str
    options: dict[str, str]
    student_answer: str | None
    correct_answer: str | None
    correctness: str
    knowledge_point_ids: list[str]
    tags: list[str]
    error_type: str | None
    diagnosis: str
    explanation: str | None
    confidence: float
    difficulty: float
    image_index: int = 0
    bank_question_id: str | None = None


@dataclass
class VlmOutcome:
    questions: list[RawQuestion] = field(default_factory=list)
    generated_by: str = "vlm"
    model: str = ""
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 规范化 / 匹配
# ---------------------------------------------------------------------------

_PUNCT = re.compile(r"[\s，。、；：？！（）()【】\[\]，,\.:;!?\"'`~·…—\-_]+")


def normalize_stem(text: str) -> str:
    """把题干压成可比较的骨架：全角转半角、去标点空格、统一大小写。"""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = normalized.replace("（", "(").replace("）", ")")
    return _PUNCT.sub("", normalized)


def match_bank_question(stem: str) -> tuple[BankQuestion | None, float]:
    """在题库里找这道题。返回 (题目, 相似度)。"""
    target = normalize_stem(stem)
    if len(target) < 6:
        return None, 0.0
    best: BankQuestion | None = None
    best_score = 0.0
    for question in get_bank().all():
        candidate = normalize_stem(question.stem)
        if not candidate:
            continue
        if target == candidate:
            return question, 1.0
        score = SequenceMatcher(None, target, candidate).ratio()
        if score > best_score:
            best, best_score = question, score
    if best_score >= BANK_MATCH_THRESHOLD:
        return best, best_score
    return None, best_score


def infer_knowledge_points(stem: str, options: dict[str, str]) -> list[str]:
    """题库没命中时的关键词兜底。"""
    haystack = (stem + " " + " ".join(options.values())).lower()
    hits: list[str] = []
    for keywords, kp_id in _KEYWORD_RULES:
        if any(kw.lower() in haystack for kw in keywords):
            if kp_id not in hits:
                hits.append(kp_id)
    return hits


def _clean_answer(value: Any, options: dict[str, str]) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text or text in ("NULL", "NONE", "无", "未作答", "N/A"):
        return None
    match = re.search(r"[ABCD]", text)
    if not match:
        return None
    key = match.group(0)
    return key if key in options else None


def _clean_correctness(value: Any, student: str | None, correct: str | None) -> str:
    """correctness 以两个答案的直接比较为准，不完全信任模型自报。"""
    if student is None:
        return "unknown"
    if correct is None:
        raw = str(value or "").strip().lower()
        return raw if raw in ("correct", "wrong", "partial", "unknown") else "unknown"
    return "correct" if student == correct else "wrong"


def _clean_error_type(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text in knowledge.ERROR_TYPES and text != "unknown" else None


def _clean_confidence(value: Any, default: float = 0.8) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _clean_difficulty(value: Any, kp_ids: Sequence[str]) -> float:
    """题目难度。

    题库规范禁止在题里写 difficulty，所以缺省时用知识点的服务端兜底难度。
    模型如果给了 1–5 的整数也接受（它只是辅助信息）。
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if 1.0 <= number <= 5.0:
        return (number - 1.0) / 4.0
    if 0.0 < number <= 1.0:
        return number
    for kp_id in kp_ids:
        point = knowledge.get_point(kp_id)
        if point:
            return point.default_difficulty
    return 0.5


def _clean_options(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, str] = {}
    for key, text in value.items():
        key_text = str(key).strip().upper()
        if len(key_text) == 1 and key_text in "ABCDEF":
            cleaned[key_text] = str(text).strip()
    return cleaned


def _clean_tags(value: Any, *, bank_question: Any = None) -> list[str]:
    """标签收敛。

    - 命中题库的题：**以题库的标签为准**（需求明确说标签系统就用题库里的标签）。
    - 没命中的题：用模型挑的标签，但必须落在标签宇宙里 ——
      模型偶尔会自己造词，放任它会凭空长出一堆只有一道题的标签。
    """
    if bank_question is not None:
        return list(bank_question.tags)

    from . import tag_service

    universe = set(tag_service.tag_universe())
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for raw in value:
        text = str(raw or "").strip()
        if text and text in universe and text not in result:
            result.append(text)
    return result


def raw_questions_from_payload(payload: dict[str, Any]) -> list[RawQuestion]:
    """把模型返回的 JSON 收敛成 RawQuestion，并做服务端判定。"""
    items = payload.get("questions")
    if not isinstance(items, list):
        return []

    results: list[RawQuestion] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        stem = str(item.get("stem") or "").strip()
        if not stem:
            continue
        options = _clean_options(item.get("options"))

        bank_question, score = match_bank_question(stem)
        if bank_question is not None:
            # 题库命中：正确答案、知识点、难度都以题库为准
            correct = bank_question.answer
            kp_ids = list(bank_question.knowledge_point_ids)
            difficulty = bank_question.difficulty
            if not options:
                options = dict(bank_question.options)
        else:
            correct = _clean_answer(item.get("answer"), options) if options else None
            raw_kps = item.get("knowledge_point_ids") or []
            kp_ids = [
                str(k).strip()
                for k in raw_kps
                if isinstance(k, str) and knowledge.is_known(str(k).strip())
            ]
            if not kp_ids:
                kp_ids = infer_knowledge_points(stem, options)
            difficulty = _clean_difficulty(item.get("difficulty"), kp_ids)

        student = _clean_answer(item.get("student_answer"), options) if options else None
        if student is None and options:
            student = _clean_answer(item.get("student_answer"), options)

        results.append(
            RawQuestion(
                question_number=str(
                    item.get("question_number") or item.get("number") or index + 1
                ).strip(),
                stem=stem,
                options=options,
                student_answer=student,
                correct_answer=correct,
                correctness=_clean_correctness(
                    item.get("correctness"), student, correct
                ),
                knowledge_point_ids=kp_ids,
                tags=_clean_tags(item.get("tags"), bank_question=bank_question),
                error_type=_clean_error_type(item.get("error_type")),
                diagnosis=str(item.get("diagnosis") or "").strip(),
                explanation=(str(item.get("explanation")).strip() or None)
                if item.get("explanation")
                else (bank_question.explanation if bank_question else None),
                confidence=_clean_confidence(item.get("confidence"), 0.9 if score > 0.9 else 0.75),
                difficulty=difficulty,
                image_index=index,
                bank_question_id=bank_question.id if bank_question else None,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def build_prompt(subject: str = "mathematics", topic: str | None = None) -> str:
    # 只列叶子知识点（没有子节点的）。官方清单是扁平的，所以这里就是全部 7 个。
    #
    # 注意这里曾经写成 `if knowledge.children_of(point.id)` —— 只列"有子节点的"，
    # 于是换成扁平清单后清单为空，模型拿到残缺 prompt 后稳定返回空题目。
    # test_vlm_pipeline 里有用例锁住"每个知识点都必须出现在 prompt 里"。
    leaves = [p for p in knowledge.all_points() if not knowledge.children_of(p.id)]
    kp_lines = "\n".join(
        f"  - {point.id}: {point.name}（{point.description}）" for point in leaves
    )
    error_lines = "\n".join(
        f"  - {code}: {label}"
        for code, label in knowledge.ERROR_TYPES.items()
        if code != "unknown"
    )
    topic_line = f"本次作业主题：{topic}" if topic else ""

    # 标签清单：模型必须从这份清单里给每道题挑标签（标签系统靠它计分）。
    from . import tag_service

    tag_lines = "\n".join(f"  - {tag}" for tag in tag_service.tag_universe())

    return f"""你是一位中国高中数学老师，正在批改学生上传的作业/试卷照片。学科：{subject}。{topic_line}

请识别照片中出现的**每一道选择题**，并输出严格的 JSON。

硬性要求：
1. 只输出 JSON 对象，不要任何解释文字，不要 markdown 代码围栏。
2. 题干和选项用纯文本表达，**不要使用 LaTeX**（不要出现 \\frac、$、^{{}} ）。数学式就写成 f'(x) = 3x^2 - 6x 这样。
3. options 的键固定为 "A"/"B"/"C"/"D"，值是选项文字。
4. student_answer 填学生在卷面上**实际选择**的选项字母；若学生未作答或字迹无法辨认，填 null。
5. answer 填**你自己重新计算**出的正确选项字母。请务必自己解一遍，不要假设学生是对的。
6. correctness：学生答案与正确答案一致填 "correct"，不一致填 "wrong"，学生未作答填 "unknown"。
7. knowledge_point_ids 只能从下面这份清单里选（可多选，最多 3 个）：
{kp_lines}
8. tags 填这道题涉及的**标签**，必须**逐字**从下面这份清单里选（1 到 4 个，不要自己造词）：
{tag_lines}
9. error_type 只能取以下之一（做对了就填 null）：
{error_lines}
10. diagnosis：用一两句中文说清学生**错在哪一步**（例如"能正确求出导数，但把 f'(x)>0 对应的区间写反了"）。做对了就说明他掌握得好在哪。
11. explanation：写出完整的关键解题步骤。
12. confidence：0 到 1 之间，表示你对本题识别与判定的把握。
13. difficulty：1-5 的整数，1 最简单、5 最难。

输出格式必须严格如下：
{{"questions":[{{"question_number":"17","stem":"已知函数 f(x) = x^3 - 3x^2 + 2，求 f(x) 的单调递增区间。","options":{{"A":"(-inf, 0)","B":"(0, 2)","C":"(-inf, 0) 和 (2, +inf)","D":"(2, +inf)"}},"student_answer":"A","answer":"C","correctness":"wrong","knowledge_point_ids":["math.derivative.monotonicity"],"tags":["利用导数判断函数单调性与单调区间"],"error_type":"transformation","diagnosis":"学生能够正确求出导数，但把导数符号与函数单调性的对应关系弄反了。","explanation":"f'(x) = 3x^2 - 6x = 3x(x-2)，令 f'(x) > 0 得 x<0 或 x>2，故单调递增区间为 (-inf,0) 和 (2,+inf)。","confidence":0.92,"difficulty":3}}]}}

如果照片里没有任何题目，返回 {{"questions":[]}}。"""


# ---------------------------------------------------------------------------
# 二次求解校验
# ---------------------------------------------------------------------------
#
# 为什么必须做这一步：视觉模型**会在数学上出错**。
# 实测中 Qwen3-VL-32B 把 f'(x)=3x(x-2)>0 的答案判成了 (0,2)，
# 而正确答案是 x<0 或 x>2。对教育产品来说，"教错答案"是比功能缺失
# 严重得多的失败——它会直接污染 Knowledge State 并误导学生。
#
# 所以规则是：**没有题库背书的答案，必须由另一个模型独立求解复现，
# 两个模型不一致时宁可不采信**（记为 unknown，不计入掌握度统计）。

MAX_VERIFY_PER_ANALYSIS = 8

# 多张图片并行识别。设上限是为了别把模型的并发配额打满（打满会触发限流，
# 反而比串行更慢）。
VLM_CONCURRENCY = 4
# 二次求解校验同样并行
VERIFY_CONCURRENCY = 4
# JSON 非法时，**每个模型**最多尝试这么多次；主模型用完才轮到备选模型
JSON_ATTEMPTS_PER_MODEL = 5

SOLVER_PROMPT = """你是一位中国高中数学老师。请**独立**解答下面这道单选题——
只根据题目本身推导，不要猜测"标准答案"或"学生可能选什么"。

题目：{stem}

选项：
{options}

请只输出 JSON，不要任何其他文字：
{{"answer":"正确选项的字母","reason":"一句话说明关键步骤","confidence":0.85}}"""


def _format_options(options: dict[str, str]) -> str:
    return "\n".join(f"{key}. {text}" for key, text in sorted(options.items()))


async def _solve_independently(
    stem: str, options: dict[str, str], llm: LlmClient, model: str
) -> str | None:
    messages = [
        {
            "role": "user",
            "content": SOLVER_PROMPT.format(stem=stem, options=_format_options(options)),
        }
    ]
    try:
        payload, _ = await llm.complete_json(
            messages,
            model=model,
            temperature=0.0,
            # 备用模型是推理模型，思维链占用 completion_tokens，要留余量
            max_tokens=1500,
            retries=0,
        )
    except LlmUnavailable:
        return None
    return _clean_answer(payload.get("answer"), options)


def verification_model(settings: Any, llm: LlmClient) -> str:
    """二次求解校验用哪个模型。

    优先用**另一个厂商**的模型：识别用的是视觉模型，校验用文本模型，
    两边异构，独立性更好 —— 同一家的模型容易犯同样的错。
    """
    if settings.verify_with_backup_model and llm.backup_configured:
        return settings.backup_llm_model
    return settings.llm_model


async def verify_answers(
    questions: Sequence[RawQuestion], *, client: LlmClient | None = None
) -> list[str]:
    """对没有题库背书的题目做二次求解校验，返回告警列表。

    各题之间并行（互不依赖），所以一整套试卷的校验耗时取决于最慢的那一道，
    而不是所有题目之和。
    """
    settings = get_settings()
    llm = client or get_llm()
    if not llm.configured:
        return []

    warnings: list[str] = []

    pending = [
        question
        for question in questions
        if question.bank_question_id is None  # 题库已背书，可信
        and question.options
        and question.correct_answer
        and question.student_answer is not None  # 没作答就不需要判定对错
    ]
    if len(pending) > MAX_VERIFY_PER_ANALYSIS:
        warnings.append("题目较多，部分题目未做二次校验，结果仅供参考")
        pending = pending[:MAX_VERIFY_PER_ANALYSIS]
    if not pending:
        return warnings

    semaphore = asyncio.Semaphore(VERIFY_CONCURRENCY)
    model = verification_model(settings, llm)

    async def solve(question: RawQuestion) -> str | None:
        async with semaphore:
            return await _solve_independently(
                question.stem, question.options, llm, model
            )

    solved = await asyncio.gather(
        *(solve(question) for question in pending), return_exceptions=True
    )

    for question, solver_answer in zip(pending, solved):
        if isinstance(solver_answer, BaseException) or solver_answer is None:
            warnings.append(
                f"第 {question.question_number} 题的答案未能二次确认，本题不计入掌握度统计"
            )
            question.correctness = "unknown"
            question.correct_answer = None
            question.error_type = None
            continue

        if solver_answer == question.correct_answer:
            question.confidence = min(1.0, round(question.confidence + 0.05, 4))
            continue

        warnings.append(
            f"第 {question.question_number} 题的正确答案存在分歧"
            f"（识别模型认为 {question.correct_answer}，独立求解认为 {solver_answer}），"
            f"本题不计入掌握度统计"
        )
        question.correctness = "unknown"
        question.correct_answer = None
        question.error_type = None

    return warnings


# ---------------------------------------------------------------------------
# 调用
# ---------------------------------------------------------------------------

async def analyze_images(
    images: Sequence[tuple[bytes, str]],
    *,
    subject: str = "mathematics",
    topic: str | None = None,
    client: LlmClient | None = None,
) -> VlmOutcome:
    """对每张图片做一次 VLM 识别，合并结果。

    主模型失败会自动退到 fallback 模型；都失败则抛 LlmUnavailable，
    由 homework_service 决定用哪种离线兜底。
    """
    settings = get_settings()
    llm = client or get_llm()
    prompt = build_prompt(subject, topic)

    models = [settings.vlm_model]
    if settings.vlm_fallback_model and settings.vlm_fallback_model != settings.vlm_model:
        models.append(settings.vlm_fallback_model)
    # 最后一道防线：**另一个厂商**的模型。主厂商整体挂掉时（实测遇到过
    # SiliconFlow 返 500），同一家的备选模型会一起哑，只有换厂商才救得回来。
    if llm.backup_configured and settings.backup_llm_model not in models:
        models.append(settings.backup_llm_model)

    semaphore = asyncio.Semaphore(VLM_CONCURRENCY)

    async def analyze_one(
        image_index: int, raw: bytes, mime: str
    ) -> tuple[list[RawQuestion], str, list[str]]:
        """单张图片：主模型先试，JSON 不合法就重试，用尽次数再换备选模型。"""
        async with semaphore:
            payload: dict[str, Any] | None = None
            last_error: Exception | None = None
            used_model = models[0]
            notes: list[str] = []

            for model in models:
                try:
                    payload, reply = await llm.complete_json(
                        [build_user_message(prompt, [(raw, mime)])],
                        model=model,
                        temperature=0.1,
                        # 一张试卷可能有十几道题，每题还要写 diagnosis + explanation。
                        # 3000 会在中途截断（实测 9 道题就爆了），所以给足。
                        max_tokens=8000,
                        vision=True,
                        retries=0,
                        attempts=JSON_ATTEMPTS_PER_MODEL,
                    )
                except LlmUnavailable as exc:
                    last_error = exc
                    continue

                used_model = reply.model
                if model != models[0]:
                    notes.append(
                        f"第 {image_index + 1} 张：主 VLM 未成功，已降级到 {model}"
                    )
                break

            if payload is None:
                raise LlmUnavailable(
                    f"第 {image_index + 1} 张图片识别失败"
                    f"（已尝试 {', '.join(models)}，"
                    f"每个模型最多 {JSON_ATTEMPTS_PER_MODEL} 次）: {last_error}"
                )

            parsed = raw_questions_from_payload(payload)
            for question in parsed:
                question.image_index = image_index
            if not parsed:
                notes.append(f"第 {image_index + 1} 张图片未识别出题目")
            return parsed, used_model, notes

    # 多张图片并行处理：互不依赖，耗时取决于最慢的一张
    results = await asyncio.gather(
        *(analyze_one(index, raw, mime) for index, (raw, mime) in enumerate(images)),
        return_exceptions=True,
    )

    outcome = VlmOutcome(generated_by="vlm")
    failed = 0
    for index, result in enumerate(results):
        if isinstance(result, BaseException):
            failed += 1
            outcome.warnings.append(f"第 {index + 1} 张图片分析失败：{result}")
            continue
        parsed, used_model, notes = result
        outcome.questions.extend(parsed)
        outcome.warnings.extend(notes)
        if used_model:
            outcome.model = used_model

    total = len(results)
    if failed and failed == total:
        raise LlmUnavailable(
            "全部 {} 张图片都识别失败：{}".format(total, "；".join(outcome.warnings[-failed:]))
        )
    if failed:
        outcome.warnings.append(f"共 {total} 张图片，其中 {failed} 张识别失败，已跳过")

    # 二次求解校验：没有题库背书的答案必须能被独立复现
    if outcome.questions:
        outcome.warnings.extend(await verify_answers(outcome.questions, client=llm))

    return outcome


def image_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def dump_outcome(outcome: VlmOutcome) -> str:
    """把识别结果序列化成可缓存的 JSON（Demo 缓存用）。"""
    return json.dumps(
        [
            {
                "question_number": q.question_number,
                "stem": q.stem,
                "options": q.options,
                "student_answer": q.student_answer,
                "correct_answer": q.correct_answer,
                "correctness": q.correctness,
                "knowledge_point_ids": q.knowledge_point_ids,
                "error_type": q.error_type,
                "diagnosis": q.diagnosis,
                "explanation": q.explanation,
                "confidence": q.confidence,
                "difficulty": q.difficulty,
                "bank_question_id": q.bank_question_id,
            }
            for q in outcome.questions
        ],
        ensure_ascii=False,
        indent=2,
    )
