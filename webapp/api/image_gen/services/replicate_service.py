import replicate


async def generate_replicate(
    positive_prompt: str,
    negative_prompt: str,
    model_version: str = "aisha-ai-official/wai-nsfw-illustrious-v11:c1d5b02687df6081c7953c74bcc527858702e8c153c9382012ccc3906752d3ec"
):
    result = await replicate.async_run(
        model_version,
        input={
            "prompt": positive_prompt,
            "negative_prompt": negative_prompt,
        }
    )

    return result[0].url
