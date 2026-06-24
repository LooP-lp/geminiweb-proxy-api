import time
import threading
import hashlib
import json
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, field
from collections import OrderedDict


@dataclass
class ConversationSession:
    session_id: str
    api_key_hash: str
    first_user_hash: str
    fingerprint_text: str
    conversation_id: str
    response_id: str
    choice_id: str
    committed_messages: List[dict] = field(default_factory=list)
    message_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)


def _normalize_user_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "\n".join(parts)
    return str(content or "")


def _first_user_hash(messages: List[dict]) -> str:
    """以首条 user 消息内容生成稳定哈希，作为会话身份。"""
    for msg in messages:
        if msg.get("role") == "user":
            text = _normalize_user_text(msg.get("content", ""))
            if text.strip():
                return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return ""


def _fingerprint_text(messages: List[dict]) -> str:
    for msg in messages:
        if msg.get("role") == "user":
            text = _normalize_user_text(msg.get("content", "")).strip()
            if text:
                return (text[:50] + "...") if len(text) > 50 else text
    return "未知对话"


class MultiSessionManager:
    def __init__(self, session_ttl: int = 7200):
        self.session_ttl = session_ttl
        self._sessions: OrderedDict[str, ConversationSession] = OrderedDict()
        self._lock = threading.RLock()
        self._cleanup_stop = False
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def _api_key_hash(self, api_key: str) -> str:
        return hashlib.sha256(api_key.encode()).hexdigest()[:8]

    def _session_id(self, api_key: str, first_user_hash: str) -> str:
        return hashlib.sha256(f"{api_key}:{first_user_hash}".encode()).hexdigest()[:16]

    def find_or_create_session(
        self, api_key: str, messages: List[dict]
    ) -> tuple[ConversationSession, bool]:
        """按首条 user 消息哈希定位会话；不存在则创建。无副作用（不推进任何状态）。"""
        fu_hash = _first_user_hash(messages)
        ak_hash = self._api_key_hash(api_key)
        if not fu_hash:
            # 没有 user 消息，给一个一次性 session
            sid = hashlib.sha256(f"{api_key}:{time.time_ns()}".encode()).hexdigest()[:16]
            session = ConversationSession(
                session_id=sid,
                api_key_hash=ak_hash,
                first_user_hash="",
                fingerprint_text=_fingerprint_text(messages),
                conversation_id="",
                response_id="",
                choice_id="",
            )
            with self._lock:
                self._sessions[sid] = session
            return session, True

        sid = self._session_id(api_key, fu_hash)
        with self._lock:
            session = self._sessions.get(sid)
            now = time.time()
            if session and now - session.last_used_at <= self.session_ttl:
                return session, False
            if session:
                # 过期，重建
                del self._sessions[sid]
            session = ConversationSession(
                session_id=sid,
                api_key_hash=ak_hash,
                first_user_hash=fu_hash,
                fingerprint_text=_fingerprint_text(messages),
                conversation_id="",
                response_id="",
                choice_id="",
            )
            self._sessions[sid] = session
            return session, True

    def commit_session(
        self,
        session_id: str,
        conversation_id: str,
        response_id: str,
        choice_id: str,
        committed_messages: List[dict],
    ):
        """成功响应后提交状态。"""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.conversation_id = conversation_id
                session.response_id = response_id
                session.choice_id = choice_id
                session.committed_messages = committed_messages
                session.message_count = len(committed_messages)
                session.last_used_at = time.time()
                self._sessions.move_to_end(session_id)

    def invalidate_session(self, session_id: str):
        """清除会话上下文（保留首条哈希以便下次复用同一 session_id 重新建立上下文）。"""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.conversation_id = ""
                session.response_id = ""
                session.choice_id = ""
                session.committed_messages = []
                session.message_count = 0
                session.last_used_at = time.time()

    def get_user_sessions(self, api_key: str) -> List[Dict]:
        ak_hash = self._api_key_hash(api_key)
        with self._lock:
            result = []
            for session in self._sessions.values():
                if session.api_key_hash == ak_hash:
                    result.append({
                        "session_id": session.session_id,
                        "fingerprint": session.fingerprint_text,
                        "message_count": session.message_count,
                        "has_context": bool(session.conversation_id),
                        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(session.created_at)),
                        "last_used": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(session.last_used_at)),
                        "idle_seconds": int(time.time() - session.last_used_at),
                    })
            result.sort(key=lambda x: x["idle_seconds"])
            return result

    def reset_session(self, api_key: str, session_id: str) -> bool:
        ak_hash = self._api_key_hash(api_key)
        with self._lock:
            session = self._sessions.get(session_id)
            if session and session.api_key_hash == ak_hash:
                del self._sessions[session_id]
                return True
            return False

    def reset_all_sessions(self, api_key: str) -> int:
        ak_hash = self._api_key_hash(api_key)
        with self._lock:
            to_delete = [sid for sid, s in self._sessions.items() if s.api_key_hash == ak_hash]
            for sid in to_delete:
                del self._sessions[sid]
            return len(to_delete)

    def get_stats(self) -> Dict:
        with self._lock:
            return {"active_sessions": len(self._sessions), "session_ttl": self.session_ttl}

    def _cleanup_loop(self):
        while not self._cleanup_stop:
            time.sleep(60)
            self._cleanup_expired()

    def _cleanup_expired(self):
        with self._lock:
            now = time.time()
            expired = [sid for sid, s in self._sessions.items() if now - s.last_used_at > self.session_ttl]
            for sid in expired:
                del self._sessions[sid]
            if expired:
                print(f"[SESSION] 清理了 {len(expired)} 个过期会话")

    def shutdown(self):
        self._cleanup_stop = True
        if self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)


_global_multi_session_manager: Optional[MultiSessionManager] = None


def get_multi_session_manager() -> MultiSessionManager:
    global _global_multi_session_manager
    if _global_multi_session_manager is None:
        _global_multi_session_manager = MultiSessionManager(session_ttl=7200)
    return _global_multi_session_manager


def shutdown_multi_session_manager():
    global _global_multi_session_manager
    if _global_multi_session_manager:
        _global_multi_session_manager.shutdown()
        _global_multi_session_manager = None
