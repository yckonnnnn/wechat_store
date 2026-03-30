"""
客服 Agent（LLM-First 版本，Phase 1）

第一性原理：
  - 前端抓取完整聊天记录 → 后端清洗 → 喂给 LLM → LLM 自主回复
  - 移除所有地址/联系方式规则干预
  - LLM 是唯一的回复决策者，知识库仅作参考
  - 保留首轮视频、stale followup 联系方式图片两个固定动作（向后兼容 message_processor）
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..data.memory_store import MemoryStore
from ..services.knowledge_service import KnowledgeService
from ..services.llm_service import LLMService
from ..services.conversation_logger import ConversationLogger
from .agent_types import AgentDecision, MediaJudgeDecision
from .agent_prompt_builder import build_system_prompt, build_conversation_messages
from .intent_detector import IntentDetector


# ── 常量池 ──────────────────────────────────────────────────────────────────

STALE_FOLLOWUP_TEXT_POOL = (
    "姐姐，记得请添加我好友哦，我会发详细定位还有乘车路线以及预约/价格方面事项给到您~❤️",
    "姐姐，您直接按上面的方式加我就可以哦，定位、路线还有预约和价格这些我都能继续发给您❤️",
    "姐姐，您记得加一下我这边哦，后面定位、路线还有预约价格这些我都继续跟您对接❤️",
)


class CustomerServiceAgent:
    """
    客服 Agent（LLM-First 版本）

    完整链路：
      1. IntentDetector 识别意图（仅用于 RAG 过滤）
      2. KnowledgeService 检索知识库（top-1，门槛 0.3）
      3. 组装 Prompt（系统提示 + 知识库参考 + 完整对话历史）
      4. LLMService 生成回复
      5. 返回 AgentDecision（media_items 为空，由固定逻辑处理媒体）

    固定动作（不经 LLM 决策）：
      - 首轮视频：新用户首次会话，由 message_processor._build_first_turn_opening_decision 触发
      - stale followup 联系方式图：1 分钟无回复，由 message_processor._build_stale_followup_media_queue 触发
    """

    # message_processor 检查此属性来决定是否触发首轮 opening
    # "legacy" = 允许首轮 opening；"llm_direct" = 跳过首轮 opening
    reply_mode = "legacy"

    STALE_FOLLOWUP_TEXT_POOL = STALE_FOLLOWUP_TEXT_POOL

    def __init__(
        self,
        knowledge_service: KnowledgeService,
        llm_service: LLMService,
        memory_store: MemoryStore,
        images_dir: Path,
        image_categories_path: Path,
        system_prompt_doc_path: Path,
        playbook_doc_path: Path,
        brand_knowledge_doc_path: Optional[Path] = None,
        reply_templates_path: Optional[Path] = None,
        media_whitelist_path: Optional[Path] = None,
        conversation_log_dir: Optional[Path] = None,
        conversation_logger: Optional[ConversationLogger] = None,
    ):
        self.knowledge_service = knowledge_service
        self.llm_service = llm_service
        self.memory_store = memory_store
        self.conversation_logger = conversation_logger

        self.images_dir = Path(images_dir)
        self.image_categories_path = Path(image_categories_path)
        self.system_prompt_doc_path = Path(system_prompt_doc_path)
        self.playbook_doc_path = Path(playbook_doc_path)
        self.reply_templates_path = Path(reply_templates_path or (Path("config") / "reply_templates.json"))
        self.conversation_log_dir = Path(conversation_log_dir or (Path("data") / "conversations"))

        # 媒体素材路径列表
        self._contact_images: List[str] = []
        self._video_medias: List[str] = []

        # 地址图片索引（按门店分组）
        # key: "sh_jingan", "sh_renmin", "sh_hongkou", "sh_wujiaochang", "sh_xuhui", "beijing_chaoyang"
        # value: List[图片绝对路径]
        self._address_index: Dict[str, List[str]] = {
            "beijing_chaoyang": [],
            "sh_xuhui": [],
            "sh_jingan": [],
            "sh_hongkou": [],
            "sh_wujiaochang": [],
            "sh_renmin": [],
        }

        # 已加载的 prompt 文本（供 get_status 显示）
        self._system_prompt_doc_text: str = ""
        self._playbook_doc_text: str = ""

        self.intent_detector = IntentDetector()

        # UI / 脚本兼容：MainWindow 与 chat_simulator 会在构造后立刻读这些属性并调用 set_options
        self.use_knowledge_first = True
        self.knowledge_threshold = 0.6
        self.first_reply_video_enabled = True

        self.reload_prompt_docs()
        self.reload_media_library()

    # ── 核心决策 ────────────────────────────────────────────────────────────

    def decide(
        self,
        session_id: str,
        user_name: str,
        latest_user_text: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        first_turn_global_override: Optional[bool] = None,
        session_manager: Optional[Any] = None,
    ) -> AgentDecision:
        """
        LLM-First 主决策：

        1. 识别意图（仅用于知识库检索优化）
        2. 知识库检索（top-1，给 LLM 作参考）
        3. 设置系统提示词（含知识库参考）
        4. 清洗对话历史（message_processor_support 已去掉末尾用户消息）
        5. 调用 LLM
        6. 返回 AgentDecision（无媒体决策，media_items=[]）
        """
        t_start = time.perf_counter()

        # 1. 意图识别（仅用于 RAG 过滤，不影响回复决策）
        intent = self._detect_intent(latest_user_text, conversation_history or [])

        # 2. 知识库检索
        kb_context = self._retrieve_kb_context(latest_user_text)
        prompt_build_ms = int((time.perf_counter() - t_start) * 1000)

        # 3. 动态设置系统提示词
        system_prompt = build_system_prompt(kb_context)
        self.llm_service.set_system_prompt(system_prompt)

        # 4. 清洗对话历史（convert_history 已去掉末尾 user 消息，这里只做安全过滤）
        llm_history = build_conversation_messages(conversation_history)

        # 5. 调用 LLM
        t_llm = time.perf_counter()
        success, reply, metrics = self.llm_service.generate_reply_sync(
            user_message=latest_user_text,
            conversation_history=llm_history,
        )
        llm_request_ms = int((time.perf_counter() - t_llm) * 1000)

        if not success or not str(reply or "").strip():
            reply = "姐姐稍等，我确认一下后马上回复您～"

        return AgentDecision(
            reply_text=str(reply).strip(),
            intent=intent,
            route_reason="llm_direct",
            reply_goal="llm_reply",
            media_plan="none",
            reply_source="llm",
            media_items=[],
            rule_id="",
            rule_applied=False,
            llm_model=self.llm_service.get_current_model_name(),
            prompt_build_ms=prompt_build_ms,
            llm_request_ms=llm_request_ms,
            llm_total_ms=int((time.perf_counter() - t_start) * 1000),
            llm_attempt_count=int(metrics.get("attempt_count", 1) or 1),
            llm_message_count=int(metrics.get("message_count", 0) or 0),
            system_prompt_chars=int(metrics.get("system_prompt_chars", 0) or 0),
        )

    # ── 内部：意图识别 ───────────────────────────────────────────────────────

    def _detect_intent(
        self,
        text: str,
        conversation_history: List[Dict[str, str]],
    ) -> str:
        try:
            return self.intent_detector.detect(text, conversation_history, {})
        except Exception:
            return "general"

    # ── 内部：知识库检索 ──────────────────────────────────────────────────────

    def _retrieve_kb_context(self, query: str) -> str:
        """
        检索知识库，返回可嵌入 Prompt 的参考文本。

        阈值由 `knowledge_threshold` 控制；关闭「优先知识库」时不检索。
        """
        try:
            if not self.use_knowledge_first:
                return ""
            thr = float(self.knowledge_threshold) if self.knowledge_threshold else 0.3
            detail = self.knowledge_service.find_answer_detail(query, threshold=max(0.05, min(1.0, thr)))
            if not detail.get("matched"):
                return ""
            question = str(detail.get("question", "") or "").strip()
            answer = str(detail.get("answer", "") or "").strip()
            if not answer:
                return ""
            if question:
                return f"问：{question}\n答：{answer}"
            return f"答：{answer}"
        except Exception:
            return ""

    # ── 首轮视频相关（供 message_processor 调用）────────────────────────────

    def is_user_first_turn_global(self, user_id_hash: str) -> bool:
        """
        判断用户是否完全没有任何历史日志（首次对话）。
        通过扫描对话日志文件来判断。
        """
        if not user_id_hash:
            return False
        try:
            for log_path in self.conversation_log_dir.glob("*.jsonl"):
                for line in log_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue
                    if str(record.get("user_id_hash", "") or "") == user_id_hash:
                        return False
        except Exception:
            pass
        return True

    def summarize_user_turns_from_logs(self, user_id_hash: str) -> Dict[str, int]:
        """统计用户历史对话轮数（兼容旧接口，is_user_first_turn_global 优先）"""
        summary = {"event_count": 0, "user_message_count": 0, "assistant_reply_count": 0}
        if not user_id_hash:
            return summary
        try:
            for log_path in self.conversation_log_dir.glob("*.jsonl"):
                for line in log_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue
                    if str(record.get("user_id_hash", "") or "") != user_id_hash:
                        continue
                    summary["event_count"] += 1
                    event_type = str(record.get("event_type", "") or "")
                    if event_type == "user_message":
                        summary["user_message_count"] += 1
                    elif event_type == "assistant_reply":
                        summary["assistant_reply_count"] += 1
        except Exception:
            pass
        return summary

    # 无本地视频文件时使用的占位路径，实际发送由 send_video_from_material_library 完成
    _MATERIAL_LIBRARY_VIDEO_SENTINEL = "__material_library_video__"

    def build_first_turn_video_items(self, session_id: str) -> List[Dict[str, Any]]:
        """
        构建首轮视频媒体项。

        如果本次 session 已经发过视频（日志中有 media_attempt 记录），则返回空列表。
        视频路径优先取本地素材；本地无素材时使用占位路径，
        实际发送由 browser_service.send_video_from_material_library 完成（页面素材库拖拽）。
        """
        if not self.first_reply_video_enabled:
            return []
        # 检查本次会话是否已发送过视频
        try:
            for log_path in self.conversation_log_dir.glob("*.jsonl"):
                for line in log_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue
                    if str(record.get("session_id", "") or "") != session_id:
                        continue
                    if str(record.get("event_type", "") or "") != "media_attempt":
                        continue
                    payload = record.get("payload", {}) or {}
                    if str(payload.get("media_type", "") or "") == "delayed_video":
                        return []  # 本次会话已发过视频
        except Exception:
            pass

        # 本地有素材文件优先用；否则用哨兵路径，触发页面素材库拖拽
        video_path = self._video_medias[0] if self._video_medias else self._MATERIAL_LIBRARY_VIDEO_SENTINEL
        return [{
            "type": "delayed_video",
            "path": video_path,
            "trigger_source": "first_reply",
            "first_turn_media": True,
        }]

    # ── 媒体相关兼容接口（message_processor.py 调用，Phase 1 均为空操作）────

    def mark_reply_sent(
        self,
        session_id: str,
        user_name: str,
        reply_text: str,
        *,
        is_first_turn_global: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """文本发送后回调。Phase 1 不触发额外媒体，返回 None。"""
        return None

    def build_post_text_media_queue(
        self,
        session_id: str,
        user_name: str,
        planned_media_items: List[Dict[str, Any]],
        extra_media_items: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        文本发送后的媒体队列。Phase 1 只透传 extra_media_items（首轮视频）。
        planned_media_items 来自规则决策，Phase 1 始终为空。
        """
        return [item for item in (extra_media_items or []) if isinstance(item, dict)]

    def judge_post_reply_media(
        self,
        session_id: str,
        user_name: str,
        latest_user_text: str,
        reply_text: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        decision: Optional[AgentDecision] = None,
    ) -> MediaJudgeDecision:
        """回复后媒体裁决。Phase 1 不发任何规则触发的媒体。"""
        return MediaJudgeDecision(media_items=[])

    def mark_media_sent(
        self,
        session_id: str,
        user_name: str,
        media_item: Dict[str, Any],
        success: bool,
    ) -> None:
        """媒体发送结果回调。Phase 1 无需更新状态。"""

    def enqueue_media_compensation(
        self,
        session_id: str,
        user_name: str,
        media_item: Dict[str, Any],
        failure_code: str = "",
        failure_detail: str = "",
    ) -> Optional[Dict[str, Any]]:
        """媒体补偿入队。Phase 1 不使用。"""
        return None

    def clear_media_compensation(
        self,
        session_id: str,
        user_name: str,
        media_item: Dict[str, Any],
    ) -> None:
        """清除媒体补偿。Phase 1 无操作。"""

    def register_planned_required_media(
        self,
        session_id: str,
        user_name: str,
        media_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """注册计划媒体项（透传，供 message_processor 记录日志用）。"""
        return list(media_items or [])

    # ── stale followup 相关（message_processor._send_stale_followup_message 调用）

    def _pick_fixed_reply(
        self,
        session_state: Dict[str, Any],
        category: str,
        replies: tuple,
        fallback: str,
    ) -> str:
        """
        从回复池中按计数器轮换选取，防止每次发完全相同的话术。
        会修改 session_state["fixed_reply_counters"]，调用方负责持久化。
        """
        pool = [str(r).strip() for r in (replies or []) if str(r).strip()]
        if not pool:
            return fallback or ""
        counters = dict(session_state.get("fixed_reply_counters", {}) or {})
        count = int(counters.get(category, 0) or 0)
        chosen = pool[count % len(pool)]
        counters[category] = count + 1
        session_state["fixed_reply_counters"] = counters
        return chosen

    def _pick_contact_image_for_session(
        self,
        session_state: Dict[str, Any],
    ) -> Optional[str]:
        """
        随机选取一张联系方式图片。
        优先选取本次 session 未发送过的图片；若全部发过则从整个池子重选。
        """
        pool = [str(p) for p in self._contact_images if str(p).strip()]
        if not pool:
            return None
        sent_paths = {
            str(p).strip()
            for p in (session_state.get("contact_image_sent_paths", []) or [])
            if str(p).strip()
        }
        available = [p for p in pool if p not in sent_paths]
        if not available:
            available = list(pool)
        return random.choice(available)

    # ── 配置加载 ─────────────────────────────────────────────────────────────

    def reload_prompt_docs(self) -> bool:
        """
        重载系统提示词文档。
        读取 system_prompt_doc_path，成功时更新 LLMService 的 system_prompt。
        """
        self._system_prompt_doc_text = self._read_text(self.system_prompt_doc_path)
        self._playbook_doc_text = self._read_text(self.playbook_doc_path)
        if self._system_prompt_doc_text:
            self.llm_service.set_system_prompt(self._system_prompt_doc_text)
        return bool(self._system_prompt_doc_text)

    def reload_media_library(self) -> None:
        """重建地址/联系方式/视频素材索引。"""
        # 清空地址索引
        for key in self._address_index:
            self._address_index[key] = []
        self._contact_images = []
        self._video_medias = []

        if not self.image_categories_path.exists():
            return

        try:
            data = json.loads(self.image_categories_path.read_text(encoding="utf-8"))
        except Exception:
            return

        images_data = data.get("images", {}) or {}
        store_targets = data.get("store_targets", {}) or {}

        # 联系方式图片
        for raw_name in images_data.get("联系方式", []):
            filename = Path(raw_name).name
            path = self.images_dir / filename
            if path.exists():
                self._contact_images.append(str(path.resolve()))

        # 视频素材
        for raw_name in images_data.get("视频素材", []):
            filename = Path(raw_name).name
            path = self.images_dir / filename
            if path.exists():
                self._video_medias.append(str(path.resolve()))

        # 视频兜底：配置文件未命中时按目录模糊匹配
        if not self._video_medias and self.images_dir.exists():
            all_files = [p for p in self.images_dir.iterdir() if p.is_file()]
            preferred = [
                p for p in all_files
                if p.suffix.lower() in (".mp4", ".mov", ".m4v")
                and ("预约" in p.name or "视频" in p.name)
            ]
            if not preferred:
                preferred = [p for p in all_files if p.suffix.lower() in (".mp4", ".mov", ".m4v")]
            self._video_medias = [str(p.resolve()) for p in preferred if p.exists()]

        # 去重，保留顺序
        if self._video_medias:
            self._video_medias = list(dict.fromkeys(self._video_medias))

        # 地址图片：从店铺地址分类中构建索引
        for raw_name in images_data.get("店铺地址", []):
            filename = Path(raw_name).name
            path = self.images_dir / filename
            if not path.exists():
                continue

            full = str(path.resolve())
            # 优先使用 store_targets 配置
            target_store = str(store_targets.get(filename, "") or "").strip()
            if target_store in self._address_index:
                self._address_index[target_store].append(full)
                continue

            # 配置未命中时，从文件名推断
            inferred_store = self._infer_store_from_name(filename)
            if inferred_store in self._address_index:
                self._address_index[inferred_store].append(full)
            else:
                # 无法识别时，归入人民广场店兜底
                self._address_index["sh_renmin"].append(full)

    def reload_rule_configs(self) -> None:
        """规则配置重载（Phase 1 仅重载知识库地址配置）。"""
        try:
            self.knowledge_service.reload_address_config()
        except Exception:
            pass

    def set_options(
        self,
        use_knowledge_first: bool,
        knowledge_threshold: float,
        first_reply_video_enabled: Optional[bool] = None,
        reply_mode: Optional[str] = None,
    ) -> None:
        """UI / 脚本配置入口（与 MainWindow、chat_simulator 对齐）。"""
        self.use_knowledge_first = bool(use_knowledge_first)
        self.knowledge_threshold = float(knowledge_threshold)
        if first_reply_video_enabled is not None:
            self.first_reply_video_enabled = bool(first_reply_video_enabled)
        if reply_mode is not None:
            self.reply_mode = str(reply_mode or self.reply_mode)

    def get_status(self) -> Dict[str, Any]:
        """给 UI 的状态快照。"""
        return {
            "use_knowledge_first": bool(self.use_knowledge_first),
            "knowledge_threshold": float(self.knowledge_threshold),
            "first_reply_video_enabled": bool(self.first_reply_video_enabled),
            "reply_mode": self.reply_mode,
            "memory_ttl_days": 30,
            "system_prompt_loaded": bool(self._system_prompt_doc_text),
            "playbook_loaded": bool(self._playbook_doc_text),
            "brand_knowledge_loaded": False,
            "address_image_count": sum(len(v) for v in self._address_index.values()),
            "contact_image_count": len(self._contact_images),
            "video_media_count": len(self._video_medias),
        }

    # ── 内部工具 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _infer_store_from_name(filename: str) -> str:
        """从文件名推断门店 key（如"客服陈培静安地址图片 1.jpg" → "sh_jingan"）。"""
        raw = str(filename or "")
        if not raw:
            return ""
        if "北京" in raw:
            return "beijing_chaoyang"
        if "徐汇" in raw or "徐家汇" in raw:
            return "sh_xuhui"
        if "静安" in raw:
            return "sh_jingan"
        if "虹口" in raw:
            return "sh_hongkou"
        if "五角场" in raw or "杨浦" in raw:
            return "sh_wujiaochang"
        if any(k in raw for k in ("人广", "人民广场", "黄浦", "黄埔")):
            return "sh_renmin"
        return ""

    def pick_address_image(
        self,
        target_store: str,
        session_state: Optional[Dict[str, Any]] = None,
        exclude_paths: Optional[List[str]] = None,
    ) -> Optional[str]:
        """从门店地址图片池中选择一张图片（随机，避开已发送的）。"""
        pool = self._address_index.get(target_store, [])
        # 上海门店兜底：如果目标门店没有图片，使用人民广场店的图片
        if not pool and target_store.startswith("sh_"):
            pool = self._address_index.get("sh_renmin", [])
        if not pool:
            return None

        # 获取已发送的图片路径
        sent_paths_by_store = dict((session_state or {}).get("address_image_sent_paths_by_store", {}) or {})
        sent_paths = {
            str(path).strip()
            for path in (sent_paths_by_store.get(target_store, []) or [])
            if str(path).strip()
        }
        excluded = {str(path).strip() for path in (exclude_paths or []) if str(path).strip()}

        # 优先选择未发送且未被排除的图片
        available = [path for path in pool if path not in sent_paths and path not in excluded]
        if not available and excluded:
            # 如果所有图片都被排除，则忽略排除列表，只避开已发送的
            available = [path for path in pool if path not in sent_paths]
        if not available:
            return None
        return random.choice(available)

    @staticmethod
    def _read_text(path: Optional[Path]) -> str:
        if not path:
            return ""
        p = Path(path)
        if not p.exists():
            return ""
        try:
            return p.read_text(encoding="utf-8").strip()
        except Exception:
            return ""
