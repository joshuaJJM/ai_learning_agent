"""题库加载器。

严格遵循约定的 bank JSON 规范：

    {
      "schema_version": "1.0",
      "bank_id": "...", "bank_name": "...", "language": "zh-CN",
      "source": "...", "version": "1.0.0", "updated_at": "2026-10-01",
      "questions": [
        { "id": "...", "type": "single_choice", "stem": "...",
          "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
          "answer": "B", "explanation": "...",
          "knowledge_point_ids": ["..."], "tags": ["..."],
          "source_ref": "..." }
      ]
    }

本版**只支持单选题**。`difficulty` 是可选扩展字段（1..5）；
缺省时回退到该知识点在 knowledge.py 里登记的典型难度档位。

加载器是宽容的：单条题目不合法只会被丢弃并记入 warnings，
不会让整个服务起不来。warning 会暴露在 /health 与启动日志里。
"""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from . import knowledge, tags as tag_vocab

BANKS_DIR = Path(__file__).resolve().parent / "seed" / "banks"

SUPPORTED_SCHEMA_VERSION = "1.0"
SUPPORTED_QUESTION_TYPES = ("single_choice",)


@dataclass(frozen=True)
class BankQuestion:
    id: str
    #: 题库文件里的原始 id（可能是「第001题」这种序号）。只用于展示，不参与关联。
    source_id: str
    #: 给用户看的题号（从 source_id 里抽数字）。练习接口的 question_number 用它。
    question_number: str
    bank_id: str
    type: str
    stem: str
    options: dict[str, str]
    answer: str
    explanation: str
    knowledge_point_ids: tuple[str, ...]
    tags: tuple[str, ...]
    source_ref: str
    difficulty: float  # 归一化到 0..1

    @property
    def choice_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.options.keys()))


@dataclass
class BankMeta:
    bank_id: str
    bank_name: str
    language: str
    source: str
    version: str
    updated_at: str
    file: str
    question_count: int = 0


@dataclass
class LoadReport:
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


#: 只有形如 ASCII 点分标识的 id 才被认为是「稳定 id」。
_STABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)+$")


def stem_fingerprint(stem: str, length: int = 10) -> str:
    """题干的内容指纹。

    用它做题目身份，而不是题库给的序号：题库重新生成时，
    序号会整体平移（第001题变成别的题），而**内容没变指纹就不变**。
    内容真的改了 → 指纹变 → 视为另一道题，这正是我们想要的语义。
    """
    normalized = re.sub(r"\s+", "", stem or "")
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:length]


def stable_question_id(bank_id: str, source_id: str, stem: str) -> str:
    """给一道题定一个稳定 id。

    题库文件里的 id 合规就用它；是「第001题」这种序号就改用内容指纹，
    拼成 `math.<主题>.<分组>.<指纹>` —— 既有稳定语义，也符合录入标准的形状。
    """
    if _STABLE_ID_PATTERN.match(source_id):
        return source_id
    return f"{bank_id}.{stem_fingerprint(stem)}"


def display_number(source_id: str, fallback_index: int) -> str:
    """给用户看的题号。从「第001题」里抽出 001；抽不到就用顺序号。"""
    match = re.search(r"\d+", source_id or "")
    if match:
        return match.group(0)
    if source_id:
        return source_id.rsplit(".", 1)[-1]
    return str(fallback_index)


def _resolve_difficulty(kp_ids: Sequence[str]) -> float:
    """题目难度。

    题库规范**明确禁止**在题里写 `difficulty`，所以难度由服务端按知识点兜底
    （`knowledge.py` 里每个知识点的 `default_difficulty`）。
    如果某个题库文件仍然带了 `difficulty`，加载器会忽略它并告警。
    """
    for kp_id in kp_ids:
        point = knowledge.get_point(kp_id)
        if point is not None:
            return point.default_difficulty
    return 0.5


class QuestionBank:
    def __init__(self) -> None:
        self.questions: dict[str, BankQuestion] = {}
        self.banks: dict[str, BankMeta] = {}
        self.report = LoadReport()
        self._fingerprinted_ids = 0
        self._undeclared_tags = 0

    # -- 查询 ---------------------------------------------------------------
    def get(self, question_id: str) -> BankQuestion | None:
        return self.questions.get(question_id)

    def all(self) -> list[BankQuestion]:
        return list(self.questions.values())

    def by_knowledge_point(self, kp_id: str) -> list[BankQuestion]:
        return [q for q in self.questions.values() if kp_id in q.knowledge_point_ids]

    def by_bank(self, bank_id: str) -> list[BankQuestion]:
        return [q for q in self.questions.values() if q.bank_id == bank_id]

    def stats(self) -> dict[str, int]:
        return {"bank_count": len(self.banks), "question_count": len(self.questions)}

    # -- 加载 ---------------------------------------------------------------
    def load(self, directory: Path | None = None) -> "QuestionBank":
        directory = directory or BANKS_DIR
        self.questions.clear()
        self.banks.clear()
        self.report = LoadReport()

        if not directory.exists():
            self.report.warnings.append(f"题库目录不存在: {directory}")
            return self

        for path in sorted(directory.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self.report.errors.append(f"{path.name}: 无法解析 JSON ({exc})")
                continue
            self._load_one(path, raw)

        return self

    def _load_one(self, path: Path, raw: dict) -> None:
        name = path.name
        if not isinstance(raw, dict):
            self.report.errors.append(f"{name}: 顶层必须是 JSON 对象")
            return

        schema_version = str(raw.get("schema_version", "")).strip()
        if schema_version != SUPPORTED_SCHEMA_VERSION:
            self.report.warnings.append(
                f"{name}: schema_version={schema_version!r}，本服务按 "
                f"{SUPPORTED_SCHEMA_VERSION} 解析"
            )

        bank_id = str(raw.get("bank_id") or path.stem).strip()
        if bank_id != path.stem:
            self.report.warnings.append(
                f"{name}: bank_id={bank_id!r} 与文件名不一致，以 bank_id 为准"
            )

        questions = raw.get("questions")
        if not isinstance(questions, list):
            self.report.errors.append(f"{name}: questions 必须是数组")
            return

        meta = BankMeta(
            bank_id=bank_id,
            bank_name=str(raw.get("bank_name", bank_id)),
            language=str(raw.get("language", "zh-CN")),
            source=str(raw.get("source", "")),
            version=str(raw.get("version", "")),
            updated_at=str(raw.get("updated_at", "")),
            file=name,
        )

        accepted = 0
        self._fingerprinted_ids = 0
        self._undeclared_tags = 0
        for index, item in enumerate(questions):
            question = self._parse_question(name, bank_id, index, item)
            if question is None:
                continue
            if question.id in self.questions:
                self.report.warnings.append(f"{name}: 题目 id 重复，已跳过 {question.id}")
                continue
            self.questions[question.id] = question
            accepted += 1

        if self._fingerprinted_ids:
            self.report.warnings.append(
                f"{name}: 有 {self._fingerprinted_ids} 道题的 id 不符合录入标准"
                f"（math.<主题>.<分组>.<编号>），已改用**题干内容指纹**做稳定 id。"
                f"这样题库重新生成时，只要题目内容没变，历史 Evidence 就不会挂错。"
                f"建议题库生成方直接产出规范 id。"
            )
        if self._undeclared_tags:
            self.report.warnings.append(
                f"{name}: 有 {self._undeclared_tags} 处标签不在 seed/tags.json 的标签表里。"
                f"标签宇宙取「标签表 ∪ 题库实际标签」，所以这些标签仍会正常计分，"
                f"但建议把标签表补全。"
            )

        meta.question_count = accepted
        if bank_id in self.banks:
            self.report.warnings.append(f"{name}: bank_id 重复 ({bank_id})")
        self.banks[bank_id] = meta

    def _parse_question(
        self, name: str, bank_id: str, index: int, item: object
    ) -> BankQuestion | None:
        label = f"{name}[{index}]"
        if not isinstance(item, dict):
            self.report.warnings.append(f"{label}: 不是对象，已跳过")
            return None

        source_id = str(item.get("id") or "").strip()
        if not source_id:
            self.report.warnings.append(f"{label}: 缺少 id，已跳过")
            return None
        qid = source_id

        qtype = str(item.get("type") or "single_choice").strip()
        if qtype not in SUPPORTED_QUESTION_TYPES:
            self.report.warnings.append(
                f"{label} ({source_id}): 暂不支持题型 {qtype!r}，已跳过"
            )
            return None

        stem = str(item.get("stem") or "").strip()
        if not stem:
            self.report.warnings.append(f"{label} ({source_id}): 题干为空，已跳过")
            return None

        # id 不合规（例如「第001题」）时改用**内容指纹**做稳定 id。
        #
        # 为什么不直接用题库给的序号：题库一旦重新生成，序号会整体平移，
        # 旧的 Evidence 就挂到别的题上了。指纹只在**内容真的变了**的时候才变，
        # 那正好意味着"这已经是另一道题"。
        if not _STABLE_ID_PATTERN.match(source_id):
            qid = stable_question_id(bank_id, source_id, stem)
            self._fingerprinted_ids += 1
            if qid in self.questions:
                self.report.warnings.append(
                    f"{label} ({source_id}): 题干指纹与已有题目冲突（{qid}），已跳过"
                )
                return None

        raw_options = item.get("options")
        if not isinstance(raw_options, dict) or not (2 <= len(raw_options) <= 8):
            self.report.warnings.append(
                f"{label} ({qid}): options 必须是 2–8 个选项的对象，已跳过"
            )
            return None
        options = {str(k).strip().upper(): str(v).strip() for k, v in raw_options.items()}

        expected_keys = [chr(ord("A") + offset) for offset in range(len(options))]
        if sorted(options) != expected_keys:
            self.report.warnings.append(
                f"{label} ({qid}): 选项键必须从 A 开始连续排列（实际 {sorted(options)}），已跳过"
            )
            return None
        if any(not text for text in options.values()):
            self.report.warnings.append(f"{label} ({qid}): 存在空选项，已跳过")
            return None

        answer = str(item.get("answer") or "").strip().upper()
        if answer not in options:
            self.report.warnings.append(
                f"{label} ({qid}): answer={answer!r} 不在 options 中，已跳过"
            )
            return None

        raw_kps = item.get("knowledge_point_ids") or []
        if not isinstance(raw_kps, list):
            raw_kps = []
        kp_ids: list[str] = []
        for kp_id in raw_kps:
            kp_id = str(kp_id).strip()
            if not kp_id:
                continue
            if not knowledge.is_known(kp_id):
                self.report.warnings.append(
                    f"{label} ({qid}): 未知知识点 {kp_id!r}（不在 knowledge_points 清单里），"
                    f"已忽略该映射"
                )
                continue
            if kp_id in kp_ids:
                self.report.warnings.append(f"{label} ({qid}): 知识点 {kp_id} 重复，已去重")
                continue
            kp_ids.append(kp_id)
        if not kp_ids:
            self.report.warnings.append(f"{label} ({qid}): 没有有效知识点映射")

        # tags 是**标签系统**的输入（练习推荐用），必须原样保留。
        #
        # 注意：录入标准原本要求 tags 与知识点名称一一对应，但团队后来给标签
        # 单独定义了一套体系，所以这里不再用知识点名去覆盖文件里的 tags，
        # 只做合法性与「是否在标签表里」的校验。
        raw_tags = item.get("tags")
        file_tags: list[str] = []
        if isinstance(raw_tags, list):
            for raw_tag in raw_tags:
                text = tag_vocab.normalize(raw_tag)
                if not text:
                    continue
                if not tag_vocab.is_valid(text):
                    self.report.warnings.append(
                        f"{label} ({qid}): 标签过长（>{tag_vocab.TAG_MAX_LENGTH}），已忽略 {text[:20]!r}…"
                    )
                    continue
                if text not in file_tags:
                    file_tags.append(text)
        if not file_tags:
            self.report.warnings.append(f"{label} ({qid}): 缺少 tags，该题不参与标签计分")
        else:
            declared = set(tag_vocab.declared_tags())
            if declared:
                for text in file_tags:
                    if text not in declared:
                        self._undeclared_tags += 1

        # 规范禁止在题目里写 difficulty / source / source_ref
        for forbidden in ("difficulty", "source", "source_ref"):
            if forbidden in item:
                self.report.warnings.append(
                    f"{label} ({qid}): 题目出现了规范禁止的字段 {forbidden!r}，已忽略"
                )

        return BankQuestion(
            id=qid,
            source_id=source_id,
            question_number=display_number(source_id, index + 1),
            bank_id=bank_id,
            type=qtype,
            stem=stem,
            options=options,
            answer=answer,
            explanation=str(item.get("explanation") or "").strip(),
            knowledge_point_ids=tuple(kp_ids),
            tags=tuple(file_tags),
            source_ref="",
            difficulty=_resolve_difficulty(kp_ids),
        )


_bank: QuestionBank | None = None


def get_bank() -> QuestionBank:
    global _bank
    if _bank is None:
        _bank = QuestionBank().load()
    return _bank


def reload_bank(directory: Path | None = None) -> QuestionBank:
    global _bank
    _bank = QuestionBank().load(directory)
    return _bank
