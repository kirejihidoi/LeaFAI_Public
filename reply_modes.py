import re, os

DEFAULT_MAX_OUT = int(os.getenv("MAX_COMPLETION_TOKENS", "384"))
HEAVY_MAX_OUT = int(os.getenv("HEAVY_COMPLETION_TOKENS", "896"))

def detect_heavy_task(text: str) -> bool:
    return bool(re.search(r"(長文|詳細|コード|全文|README|実装|エラー解析|stacktrace|ログ)", text or ""))

def choose_max_out(text: str) -> int:
    return HEAVY_MAX_OUT if detect_heavy_task(text) else DEFAULT_MAX_OUT
