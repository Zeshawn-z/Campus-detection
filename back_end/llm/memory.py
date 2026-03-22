"""
会话记忆模块 - 双层存储架构
- 热数据：Redis 缓存（快速读写，6小时TTL）
- 冷数据：数据库持久化（ChatSession + ChatMessage）
- 写操作同时写入两层，读操作优先读缓存
"""
from __future__ import annotations

from typing import List, Dict, Optional
from django.core.cache import cache
from django.utils import timezone
import json
import logging
import uuid

logger = logging.getLogger(__name__)

CACHE_PREFIX = "llm_chat_memory:"
DEFAULT_TTL_SEC = 60 * 60 * 6  # 6小时
MAX_HISTORY = 20


class ChatMemoryStore:
    """双层聊天记忆存取封装：Redis缓存 + 数据库持久化"""

    @staticmethod
    def _key(session_id: str) -> str:
        return f"{CACHE_PREFIX}{session_id}"

    @classmethod
    def get_or_create_session(cls, session_id: str, user=None, model_type: str = "default") -> 'ChatSession':
        """获取或创建对话会话"""
        from .models import ChatSession
        session, created = ChatSession.objects.get_or_create(
            session_id=session_id,
            defaults={
                'user': user,
                'model_type': model_type,
                'title': '新对话'
            }
        )
        if not created and user and not session.user:
            session.user = user
            session.save(update_fields=['user'])
        return session

    @classmethod
    def get_history(cls, session_id: str) -> List[Dict]:
        """获取会话历史（优先读缓存，缓存未命中读数据库）"""
        # 先读缓存
        data = cache.get(cls._key(session_id))
        if data:
            try:
                return json.loads(data)
            except Exception:
                pass
        
        # 缓存未命中，从数据库加载
        try:
            from .models import ChatSession, ChatMessage
            session = ChatSession.objects.filter(session_id=session_id).first()
            if not session:
                return []
            
            messages = ChatMessage.objects.filter(session=session).order_by('created_at')[:MAX_HISTORY]
            history = [
                {"role": msg.role, "content": msg.content, "ts": msg.created_at.isoformat()}
                for msg in messages
            ]
            
            # 回填缓存
            if history:
                cache.set(cls._key(session_id), json.dumps(history, ensure_ascii=False), DEFAULT_TTL_SEC)
            
            return history
        except Exception as e:
            logger.warning(f"从数据库加载历史失败: {e}")
            return []

    @classmethod
    def append(cls, session_id: str, role: str, content: str, 
               user=None, model_type: str = "default", metadata: dict = None,
               ttl: int = DEFAULT_TTL_SEC) -> List[Dict]:
        """追加消息到会话（同时写入缓存和数据库）"""
        now = timezone.now()
        
        # 1. 写入数据库
        try:
            from .models import ChatSession, ChatMessage
            session = cls.get_or_create_session(session_id, user=user, model_type=model_type)
            
            ChatMessage.objects.create(
                session=session,
                role=role,
                content=content,
                metadata=metadata or {}
            )
            
            # 自动生成会话标题（取用户第一条消息的前30字）
            if session.title == '新对话' and role == 'user':
                session.title = content[:30] + ('...' if len(content) > 30 else '')
                session.save(update_fields=['title', 'updated_at'])
            else:
                session.save(update_fields=['updated_at'])
                
        except Exception as e:
            logger.warning(f"持久化消息失败: {e}")
        
        # 2. 更新缓存
        history = cls.get_history(session_id)
        history.append({"role": role, "content": content, "ts": now.isoformat()})
        if len(history) > MAX_HISTORY:
            history = history[-MAX_HISTORY:]
        cache.set(cls._key(session_id), json.dumps(history, ensure_ascii=False), ttl)
        
        return history

    @classmethod
    def set_history(cls, session_id: str, history: List[Dict], ttl: int = DEFAULT_TTL_SEC):
        """设置缓存中的历史（兼容旧接口）"""
        compact = [
            {"role": h.get("role"), "content": h.get("content"), "ts": h.get("ts")}
            for h in history[-MAX_HISTORY:]
            if h.get("role") in ("user", "assistant") and h.get("content")
        ]
        cache.set(cls._key(session_id), json.dumps(compact, ensure_ascii=False), ttl)

    @classmethod
    def clear(cls, session_id: str):
        """清除缓存（不删除数据库记录，仅标记归档）"""
        cache.delete(cls._key(session_id))
        try:
            from .models import ChatSession
            ChatSession.objects.filter(session_id=session_id).update(is_archived=True)
        except Exception as e:
            logger.warning(f"归档会话失败: {e}")

    @classmethod
    def get_user_sessions(cls, user, limit: int = 20) -> List[Dict]:
        """获取用户的所有会话列表"""
        try:
            from .models import ChatSession
            sessions = ChatSession.objects.filter(
                user=user, 
                is_archived=False
            ).order_by('-updated_at')[:limit]
            
            return [
                {
                    'session_id': s.session_id,
                    'title': s.title,
                    'model_type': s.model_type,
                    'created_at': s.created_at.isoformat(),
                    'updated_at': s.updated_at.isoformat(),
                    'message_count': s.messages.count()
                }
                for s in sessions
            ]
        except Exception as e:
            logger.warning(f"获取用户会话列表失败: {e}")
            return []

    @classmethod
    def delete_session(cls, session_id: str):
        """彻底删除会话（缓存+数据库）"""
        cache.delete(cls._key(session_id))
        try:
            from .models import ChatSession
            ChatSession.objects.filter(session_id=session_id).delete()
        except Exception as e:
            logger.warning(f"删除会话失败: {e}")

    @classmethod
    def persist_snapshot(cls, session_id: str, tag: str = ""):
        """兼容旧接口：快照已由 append 自动持久化，此方法为空操作"""
        pass


def normalize_frontend_history(history: Optional[List[Dict]]) -> List[Dict]:
    """将前端历史标准化为 [ {role, content} ]"""
    if not history:
        return []
    out = []
    for item in history:
        role = item.get("role") or item.get("sender")
        content = item.get("content") or item.get("text")
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out[-MAX_HISTORY:]
