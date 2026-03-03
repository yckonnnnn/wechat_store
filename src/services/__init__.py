"""
服务层模块
"""

from .llm_service import LLMService
from .browser_service import BrowserService
from .knowledge_service import KnowledgeService
from .conversation_logger import ConversationLogger
from .crm_contact_service import CRMContactService, CRMContactRecord

__all__ = ['LLMService', 'BrowserService', 'KnowledgeService', 'ConversationLogger', 'CRMContactService', 'CRMContactRecord']
