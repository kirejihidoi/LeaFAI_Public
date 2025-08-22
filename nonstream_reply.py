# nonstream_reply.py
import os
import asyncio
import logging
import random
from typing import Optional, List, Dict, Any, Tuple

import httpx
from openai import AsyncOpenAI, APIError, APIConnectionError, RateLimitError, APITimeoutError

__all__ = ["nonstream_progressive_reply"]

# Discord のメッセージ上限を考慮（安全マージン）
DISCORD_CHUNK = 1900

# デフォルトモデル（環境変数で上書き可能）
DEFAULT_MODEL_FAST = os.getenv("MODEL_FAST", "gpt-5-mini")
DEFAULT_MODEL_HEAVY = os.getenv("MODEL_HEAVY", "gpt-5")
DEFAULT_MODEL_VISION = os.getenv("MODEL_VISION", "gpt-5-vision")


def _supports_tuning(model: str) -> bool:
    """gpt-5 系は sampling パラメータ非対応。gpt-4/4o 系のみ有効化。"""
    return not model.startswith("gpt-5")


def _message_has_image(messages: List[Dict[str, Any]]) -> bool:
    """OpenAI chat payload 中に image 指定があるかの簡易検出。"""
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            for part in c:
                if not isinstance(part, dict):
                    continue
                t = part.get("type")
                if t in ("image_url", "input_image"):
                    return True
                if "image_url" in part:
                    return True
    return False


async def _call_chat_once(
    oai: AsyncOpenAI,
    *,
    model: str,
    messages: List[Dict[str, Any]],
    max_completion_tokens: int,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    force_text: bool = True,  # True のとき response_format={"type":"text"} を付ける
) -> Tuple[str, Optional[str]]:
    """
    1回だけ Chat Completions を叩く。
    戻り値: (text, finish_reason)  ※text は空文字のこともある
    """
    args: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_completion_tokens,
    }
    if force_text:
        args["response_format"] = {"type": "text"}

    if _supports_tuning(model):
        if temperature is not None:
            args["temperature"] = temperature
        if top_p is not None:
            args["top_p"] = top_p
        if frequency_penalty is not None:
            args["frequency_penalty"] = frequency_penalty
        if presence_penalty is not None:
            args["presence_penalty"] = presence_penalty

    resp = await oai.chat.completions.create(**args)

    if not getattr(resp, "choices", None):
        logging.warning("Chat completion returned no choices (model=%s)", model)
        return "", None

    ch = resp.choices[0]
    finish_reason = getattr(ch, "finish_reason", None)
    msg = getattr(ch, "message", None)
    text = (msg and (msg.content or "")) or ""
    text = text.strip()

    if not text:
        logging.warning(
            "Chat completion returned empty content (model=%s, finish_reason=%s)",
            model,
            finish_reason,
        )

    return text, finish_reason


async def nonstream_progressive_reply(
    *,
    channel,                              # discord.abc.Messageable（例: message.channel）
    messages: List[Dict[str, Any]],
    oai: AsyncOpenAI,
    model_full: str = DEFAULT_MODEL_HEAVY,
    model_preview: str = DEFAULT_MODEL_FAST,
    allowed_mentions=None,
    my_msgs: Optional[Dict[int, Dict[str, Any]]] = None,

    # タイムアウト/リトライ系
    preview_deadline: int = 20,
    full_hard_deadline: int = 90,
    full_per_try_timeout: int = 40,
    full_retries: int = 1,

    # トークン上限（必要に応じて調整可）
    preview_tokens: int = 1500,
    full_tokens_fast: int = 3000,
    full_tokens_heavy: int = 6000,

    # サンプリング（gpt-5 系には自動で適用しない）
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
    presence_penalty: Optional[float] = None,

    # 画像混在時の強制差し替え
    model_vision: Optional[str] = None,

    # 生成後の整形コールバック
    postprocess=None,

    # 追加: トランケーション検知で自動延長するか
    auto_extend_on_truncation: bool = True,
) -> str:
    """
    typing() だけ見せて、完成文を一括送信（長文は分割）する版。
    返り値: 送信した最終テキスト全体（分割時は結合）。
    """

    # 画像が混ざっていたら、ビジョンモデルへ強制切替
    if _message_has_image(messages):
        mv = model_vision or DEFAULT_MODEL_VISION
        model_full = mv
        model_preview = mv

    async def _preview_call() -> str:
        try:
            async with asyncio.timeout(min(full_per_try_timeout, preview_deadline)):
                txt, _ = await _call_chat_once(
                    oai,
                    model=model_preview,
                    messages=messages,
                    max_completion_tokens=preview_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    frequency_penalty=frequency_penalty,
                    presence_penalty=presence_penalty,
                )
            return txt
        except Exception as e:
            logging.warning("preview_call failed: %s", e)
            return ""

    async def _full_call_with_light_retry() -> str:
        tries = max(1, full_retries + 1)
        # “gpt-5*” は heavy 側、その他は fast 側の上限を初期値に
        base_tokens = full_tokens_heavy if model_full.startswith("gpt-5") else full_tokens_fast

        last_err: Optional[BaseException] = None
        # 試行1: 通常呼び（force_text=True）
        for attempt in range(tries):
            try:
                async with asyncio.timeout(full_per_try_timeout):
                    txt, fr = await _call_chat_once(
                        oai,
                        model=model_full,
                        messages=messages,
                        max_completion_tokens=base_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        frequency_penalty=frequency_penalty,
                        presence_penalty=presence_penalty,
                        force_text=True,
                    )
                if txt:
                    return txt

                # 空応答。finish_reason=length なら “トークン不足由来” の可能性 → 自動延長試行
                if auto_extend_on_truncation and fr == "length":
                    try_tokens = min(base_tokens * 2, 2048)
                    logging.warning("Auto-extending due to truncation: %s -> %s", base_tokens, try_tokens)
                    async with asyncio.timeout(full_per_try_timeout):
                        txt2, _ = await _call_chat_once(
                            oai,
                            model=model_full,
                            messages=messages,
                            max_completion_tokens=try_tokens,
                            temperature=temperature,
                            top_p=top_p,
                            frequency_penalty=frequency_penalty,
                            presence_penalty=presence_penalty,
                            force_text=False,  # response_format を外して再試行
                        )
                    if txt2:
                        return txt2

                # 通常の空応答は失敗扱いにして、次ループ
                raise RuntimeError("empty_content")
            except (APITimeoutError, APIConnectionError, RateLimitError, APIError, httpx.ReadTimeout, asyncio.TimeoutError, RuntimeError) as e:
                last_err = e
                if attempt < tries - 1:
                    await asyncio.sleep(1.0 + random.random() * 0.5)

        # フォールバック（mini or vision）
        try:
            async with asyncio.timeout(full_per_try_timeout):
                # どうしても空を返してくるケース向けに、超短文を強制するダウンシフト
                forced_messages = messages + [
                    {"role": "system", "content": "直前の会話に短く一言で返して。20文字以内。"}
                ]
                fb, _ = await _call_chat_once(
                    oai,
                    model=model_preview,
                    messages=forced_messages,
                    max_completion_tokens=max(64, preview_tokens),
                    temperature=temperature,
                    top_p=top_p,
                    frequency_penalty=frequency_penalty,
                    presence_penalty=presence_penalty,
                    force_text=True,
                )
            if fb:
                return fb
        except Exception as e2:
            logging.error("Fallback model failed: %s", e2)

        logging.error("Full+fallback produced empty content; returning default fallback text. last_err=%r", last_err)
        return "……返す言葉が見つからなかったわ。"

    # typing インジケータを出しつつ、裏で生成
    async with channel.typing():
        preview_task = asyncio.create_task(_preview_call())
        full_task = asyncio.create_task(_full_call_with_light_retry())

        try:
            final_text = await asyncio.wait_for(full_task, timeout=full_hard_deadline)
        except asyncio.TimeoutError:
            final_text = "魔力切れ。少ししてからもう一度。"

    # 生成後の整形
    final_text = (final_text or "").strip()
    if postprocess:
        try:
            final_text = postprocess(final_text) or final_text
        except Exception:
            pass

    # 長文は分割して順に送信
    chunks = [final_text[i:i + DISCORD_CHUNK] for i in range(0, len(final_text), DISCORD_CHUNK)] or [final_text]
    sent_all: List[str] = []
    for c in chunks:
        sent = await channel.send(c, allowed_mentions=allowed_mentions)
        sent_all.append(c)
        if my_msgs is not None:
            try:
                my_msgs[sent.id] = {
                    "channel_id": getattr(sent.channel, "id", None),
                    "content": c[:200],
                    "at": getattr(sent, "created_at", None),
                }
            except Exception:
                pass

    return "".join(sent_all)
