import os, math
from typing import List, Dict

MAX_PROMPT_TOKENS = int(os.getenv("MAX_PROMPT_TOKENS", "3000"))
MAX_COMPLETION_TOKENS_DEFAULT = int(os.getenv("MAX_COMPLETION_TOKENS", "384"))

try:
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    def count_tokens(text: str) -> int:
        return len(enc.encode(text))
except Exception:
    def count_tokens(text: str) -> int:
        return max(1, math.ceil(len(text) / 4))

def messages_token_len(msgs: List[Dict[str, str]]) -> int:
    total = 0
    for m in msgs:
        total += count_tokens(m.get("content", "")) + 4
    return total

def fit_to_budget(msgs: List[Dict[str, str]], budget: int = MAX_PROMPT_TOKENS) -> List[Dict[str, str]]:
    if messages_token_len(msgs) <= budget:
        return msgs
    head = []
    rest = []
    for m in msgs:
        if m.get("role") == "system" and len(head) < 2:
            head.append(m)
        else:
            rest.append(m)
    pruned = head + rest
    i = len(head)
    while messages_token_len(pruned) > budget and i < len(pruned) - 1:
        if pruned[i].get("role") != "system":
            del pruned[i]
        else:
            i += 1
    while messages_token_len(pruned) > budget and len(pruned) > 0:
        last = pruned[-1]
        c = last.get("content", "")
        if len(c) < 200:
            break
        last["content"] = c[-int(len(c)*0.8):]
    return pruned
