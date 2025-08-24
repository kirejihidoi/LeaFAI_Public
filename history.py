# history.py
import asyncio
from collections import deque
from typing import Dict, Deque, List, Any

class HistoryStore:
    """
    チャンネル単位で直近の会話を保持するだけの極小実装。
    画像は履歴には埋めず、「[画像xN]」の注記だけ残す。
    """
    def __init__(self, max_turns: int = 6):
        # max_turns は「ユーザーとアシスタントの往復」の上限
        self.max_turns = max_turns
        self._store: Dict[str, Deque[Dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    def _dq(self, cid: str) -> Deque[Dict[str, Any]]:
        if cid not in self._store:
            self._store[cid] = deque()
        return self._store[cid]

    async def append_user(self, cid: str, text: str, image_urls: List[str]):
        text = (text or "").strip()
        if image_urls:
            note = f" [画像x{len(image_urls)}]"
            text = (text + note) if text else note
        await self._append(cid, "user", text or "…")

    async def append_assistant(self, cid: str, text: str):
        await self._append(cid, "assistant", (text or "").strip() or "…")

    async def _append(self, cid: str, role: str, content: str):
        async with self._lock:
            dq = self._dq(cid)
            dq.append({"role": role, "content": content})
            # 「往復」上限なので2倍で切る
            while len(dq) > self.max_turns * 2:
                dq.popleft()

    async def build_messages(self, system_prompt: str, cid: str, current_user_content: List[Dict[str, Any]]):
        """
        OpenAIにそのまま渡せるmessagesを構築。
        履歴は文字列のみ、今回のユーザー発話はマルチモーダルのまま添付。
        """
        async with self._lock:
            past = list(self._dq(cid))
        msgs: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        msgs.extend(past)  # ここは string コンテンツ
        msgs.append({"role": "user", "content": current_user_content})  # 今回だけ image可
        return msgs

    async def reset(self, cid: str):
        async with self._lock:
            self._store.pop(cid, None)
