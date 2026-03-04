"""
LLM 服务模块
负责模型 API 调用，不承载业务决策逻辑。
"""

from __future__ import annotations

import json
import ssl
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QThread, Signal


class LLMWorker(QThread):
    """异步模型调用线程"""

    result_ready = Signal(str, bool, str)
    DEFAULT_TEMPERATURE = 0.2

    def __init__(
        self,
        request_id: str,
        model_name: str,
        config: dict,
        messages: List[Dict],
        system_prompt: str,
        max_tokens: int = 500,
    ):
        super().__init__()
        self.request_id = request_id
        self.model_name = model_name
        self.config = config
        self.messages = messages
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens

    def run(self):
        try:
            result = self._call_api()
            self.result_ready.emit(self.request_id, True, result)
        except Exception as exc:
            self.result_ready.emit(self.request_id, False, str(exc))

    def _ssl_ctx(self):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _call_api(self) -> str:
        api_key = self.config.get("api_key", "")
        base_url = self.config.get("base_url", "")
        model = self.config.get("model", "")

        if not api_key:
            raise ValueError("API密钥未配置")

        if self.model_name in ("ChatGPT", "DeepSeek", "kimi"):
            return self._call_openai_compatible(api_key, base_url, model)
        if self.model_name == "Gemini":
            return self._call_gemini(api_key, base_url, model)
        if self.model_name == "阿里千问":
            return self._call_qwen(api_key, base_url, model)
        raise ValueError(f"不支持的模型: {self.model_name}")

    def _call_openai_compatible(self, api_key: str, base_url: str, model: str) -> str:
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": self.system_prompt}, *self.messages],
            "temperature": self.DEFAULT_TEMPERATURE,
            "max_tokens": self.max_tokens,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60, context=self._ssl_ctx()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]

    def _call_gemini(self, api_key: str, base_url: str, model: str) -> str:
        url = f"{base_url.rstrip('/')}/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}

        contents = []
        for msg in self.messages:
            role = "user" if msg.get("role") == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.DEFAULT_TEMPERATURE,
                "maxOutputTokens": self.max_tokens,
            },
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60, context=self._ssl_ctx()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "candidates" in data and data["candidates"]:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            raise ValueError("Gemini API返回格式错误")

    def _call_qwen(self, api_key: str, base_url: str, model: str) -> str:
        url = f"{base_url.rstrip('/')}/api/v1/services/aigc/text-generation/generation"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        prompt = self.system_prompt + "\n\n"
        for msg in self.messages:
            role = "用户" if msg.get("role") == "user" else "助手"
            prompt += f"{role}: {msg.get('content', '')}\n"
        prompt += "助手: "

        payload = {
            "model": model,
            "input": {"prompt": prompt},
            "parameters": {
                "temperature": self.DEFAULT_TEMPERATURE,
                "max_tokens": self.max_tokens,
            },
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60, context=self._ssl_ctx()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["output"]["text"]


class LLMService(QObject):
    """LLM 服务"""

    reply_ready = Signal(str, str)
    error_occurred = Signal(str, str)

    def __init__(self, config_manager):
        super().__init__()
        self.config_manager = config_manager
        self._workers: Dict[str, LLMWorker] = {}
        self._system_prompt = "你是专业假发客服助手，请根据规则给出简洁、自然、可执行回复。"

    def generate_reply(
        self,
        user_message: str,
        conversation_history: List[Dict] = None,
        request_id: str = None,
    ) -> str:
        import uuid

        rid = request_id or str(uuid.uuid4())

        model_name = self.config_manager.get_current_model()
        model_config = self.config_manager.get_model_config(model_name)

        if not model_config.get("api_key"):
            self.error_occurred.emit(rid, f"{model_name} 的API密钥未配置")
            return rid

        messages = []
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        worker = LLMWorker(
            request_id=rid,
            model_name=model_name,
            config=model_config,
            messages=messages,
            system_prompt=self._system_prompt,
        )
        worker.result_ready.connect(self._on_worker_result)
        self._workers[rid] = worker
        worker.start()
        return rid

    def generate_reply_sync(self, user_message: str, conversation_history: List[Dict] = None) -> tuple:
        model_name = self.config_manager.get_current_model()
        model_config = self.config_manager.get_model_config(model_name)

        if not model_config.get("api_key"):
            return False, f"{model_name} 的API密钥未配置"

        messages = []
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        try:
            worker = LLMWorker(
                request_id="sync",
                model_name=model_name,
                config=model_config,
                messages=messages,
                system_prompt=self._system_prompt,
            )
            return True, worker._call_api()
        except Exception as exc:
            return False, str(exc)

    def _on_worker_result(self, request_id: str, success: bool, result: str):
        if request_id in self._workers:
            worker = self._workers[request_id]
            if worker.isRunning():
                worker.wait()
            del self._workers[request_id]

        if success:
            self.reply_ready.emit(request_id, result)
        else:
            self.error_occurred.emit(request_id, result)

    def set_system_prompt(self, prompt: str):
        self._system_prompt = (prompt or "").strip() or self._system_prompt

    def get_system_prompt(self) -> str:
        return self._system_prompt

    def get_current_model_name(self) -> str:
        return self.config_manager.get_current_model()

    def load_prompt_docs(self, system_prompt_path: Path, playbook_path: Optional[Path] = None) -> bool:
        """从文档加载基础 prompt（可选附加 playbook）。"""
        try:
            if not system_prompt_path.exists():
                return False
            prompt_text = system_prompt_path.read_text(encoding="utf-8").strip()
            if playbook_path and playbook_path.exists():
                playbook_text = playbook_path.read_text(encoding="utf-8").strip()
                prompt_text = f"{prompt_text}\n\n---\n{playbook_text}"
            self.set_system_prompt(prompt_text)
            return True
        except Exception:
            return False

    def cleanup(self):
        for request_id, worker in list(self._workers.items()):
            if worker.isRunning():
                worker.quit()
                worker.wait(1000)
        self._workers.clear()

    def test_connection(self, model_name: str = None) -> tuple:
        model_name = model_name or self.config_manager.get_current_model()
        config = self.config_manager.get_model_config(model_name)

        if not config.get("api_key"):
            return False, "API密钥未配置"
        if not config.get("base_url"):
            return False, "API地址未配置"

        try:
            worker = LLMWorker(
                request_id="test",
                model_name=model_name,
                config=config,
                messages=[{"role": "user", "content": "ping"}],
                system_prompt="你是一个专业的假发客服",
                max_tokens=1,
            )
            worker._call_api()
            return True, "连接成功"
        except Exception as exc:
            return False, f"连接失败: {str(exc)}"

    def cancel_request(self, request_id: str):
        if request_id in self._workers:
            worker = self._workers[request_id]
            if worker.isRunning():
                worker.terminate()
            del self._workers[request_id]
