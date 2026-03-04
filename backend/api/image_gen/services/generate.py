def truncate_prompt(prompt: str, max_tokens: int = 75) -> str:
    parts = [p.strip() for p in prompt.split(",") if p.strip()]
    result = []
    current_tokens = 0

    for part in parts:
        part_tokens = len(part.split())
        if current_tokens + part_tokens <= max_tokens:
            result.append(part)
            current_tokens += part_tokens
        else:
            break

    return ", ".join(result) if result else prompt[:300]
