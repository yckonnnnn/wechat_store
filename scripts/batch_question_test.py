#!/usr/bin/env python3
"""
批量测试脚本：读取常见问题测试1.md中的问题，按顺序测试并输出回复结果
"""

import sys
import time
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.private_cs_agent import CustomerServiceAgent
from src.data.config_manager import ConfigManager
from src.data.knowledge_repository import KnowledgeRepository
from src.data.memory_store import MemoryStore
from src.services.knowledge_service import KnowledgeService
from src.services.llm_service import LLMService
from src.utils.constants import ENV_FILE, KNOWLEDGE_BASE_FILE, MODEL_SETTINGS_FILE


class StubLLMService:
    """规则联调时的本地占位 LLM，避免真实 API 调用。"""

    def __init__(self, fixed_reply: str = "姐姐，这个问题我给您简要说明。"):
        self._prompt = ""
        self._fixed_reply = fixed_reply

    def set_system_prompt(self, prompt: str):
        self._prompt = prompt or ""

    def generate_reply_sync(self, user_message: str, conversation_history=None) -> tuple:
        return True, self._fixed_reply

    def get_current_model_name(self) -> str:
        return "StubLLM"


def build_agent(no_llm: bool = True, stub_reply: str = "姐姐，这个问题我给您简要说明。") -> CustomerServiceAgent:
    """构建客服代理实例"""
    sim_data_dir = PROJECT_ROOT / "data" / "simulator"
    sim_data_dir.mkdir(parents=True, exist_ok=True)
    convo_dir = sim_data_dir / "conversations"
    convo_dir.mkdir(parents=True, exist_ok=True)

    config_manager = ConfigManager(config_file=MODEL_SETTINGS_FILE, env_file=ENV_FILE)
    repository = KnowledgeRepository(data_file=KNOWLEDGE_BASE_FILE)
    knowledge_service = KnowledgeService(repository, address_config_path=Path("config") / "address.json")
    llm_service = StubLLMService(stub_reply) if no_llm else LLMService(config_manager)
    memory_store = MemoryStore(sim_data_dir / "agent_memory.json")

    return CustomerServiceAgent(
        knowledge_service=knowledge_service,
        llm_service=llm_service,
        memory_store=memory_store,
        images_dir=Path("images"),
        image_categories_path=Path("config") / "image_categories.json",
        system_prompt_doc_path=Path("docs") / "system_prompt_private_ai_customer_service.md",
        playbook_doc_path=Path("docs") / "private_ai_customer_service_playbook.md",
        reply_templates_path=Path("config") / "reply_templates.json",
        media_whitelist_path=Path("config") / "media_whitelist.json",
        conversation_log_dir=convo_dir,
    )

def read_questions_from_file(file_path: Path) -> List[str]:
    """从文件中读取问题列表"""
    questions = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):  # 跳过空行和标题
                    questions.append(line)
    except FileNotFoundError:
        print(f"错误：找不到文件 {file_path}")
        return []
    except Exception as e:
        print(f"错误：读取文件失败 {e}")
        return []
    
    return questions

def test_questions_batch(questions: List[str], session_id: str = "batch_test", user_name: str = "测试用户"):
    """批量测试问题"""
    print("=" * 80)
    print("批量测试开始")
    print("=" * 80)
    
    # 初始化客服代理
    try:
        agent = build_agent(no_llm=True)  # 使用Stub LLM避免API调用
        print("✅ 客服代理初始化成功")
    except Exception as e:
        print(f"❌ 客服代理初始化失败: {e}")
        return
    
    print(f"📝 共 {len(questions)} 个问题待测试")
    print("-" * 80)
    
    for i, question in enumerate(questions, 1):
        print(f"\n🔍 问题 {i}/{len(questions)}: {question}")
        print("-" * 40)
        
        try:
            # 处理问题
            result = agent.decide(
                session_id=session_id,
                user_name=user_name,
                latest_user_text=question,
                conversation_history=[]
            )
            
            if result:
                # 输出回复结果
                print(f"💬 回复: {result.reply_text}")
                print(f"📊 来源: {result.reply_source}")
                print(f"🎯 意图: {result.intent}")
                print(f"⚙️  规则: {result.rule_id}")
                
                # 输出媒体触发情况
                media_items = result.media_items or []
                media_types = []
                for item in media_items:
                    if isinstance(item, dict):
                        media_type = item.get("type", "")
                        if media_type == "address_image":
                            media_types.append("地址图片")
                        elif media_type == "contact_image":
                            media_types.append("联系方式图片")
                        elif media_type == "delayed_video":
                            media_types.append("视频")
                
                if media_types:
                    print(f"📎 媒体触发: {', '.join(media_types)}")
                else:
                    print("📎 媒体触发: 无")
            else:
                print("❌ 未获得回复结果")
                
        except Exception as e:
            print(f"❌ 处理问题时出错: {e}")
        
        # 添加延迟，避免处理过快
        time.sleep(0.5)
    
    print("\n" + "=" * 80)
    print("批量测试完成")
    print("=" * 80)

def main():
    """主函数"""
    # 读取问题文件
    questions_file = PROJECT_ROOT / "常见问题测试1.md"
    
    print(f"📖 从文件读取问题: {questions_file}")
    questions = read_questions_from_file(questions_file)
    
    if not questions:
        print("❌ 没有找到有效问题，退出")
        return
    
    print(f"✅ 成功读取 {len(questions)} 个问题")
    
    # 开始批量测试
    test_questions_batch(questions)

if __name__ == "__main__":
    main()
