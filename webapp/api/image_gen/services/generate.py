import replicate
import fal_client
from ..schemas.generate import ImageSize


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


async def submit_real(
        prompt: str,
        allow_nsfw: bool,
        image_size: ImageSize = ImageSize(width=1024, height=1024)
):
    handler = await fal_client.submit_async(
        # model_name,
        "fal-ai/z-image/turbo",
        arguments={
            "prompt": prompt,
            "enable_safety_checker": not allow_nsfw,
            "image_size": image_size.model_dump(),
        }
    )

    result = await handler.get()  # wait for result
    return result["images"][0]["url"]
    # result : {"images": list[{"url": str, ...}], ...}  ||  result["images"][0]["url"] to get url


async def submit_anime(
    positive_prompt: str,
    negative_prompt: str,
    model_version: str = "aisha-ai-official/wai-nsfw-illustrious-v11:c1d5b02687df6081c7953c74bcc527858702e8c153c9382012ccc3906752d3ec"
):
    positive_prompt = truncate_prompt(positive_prompt, max_tokens=75)
    negative_prompt = truncate_prompt(negative_prompt, max_tokens=75)

    result = await replicate.async_run(
        model_version,
        input={
            "prompt": positive_prompt,
            "negative_prompt": negative_prompt,
        }
    )

    return result[0].url
