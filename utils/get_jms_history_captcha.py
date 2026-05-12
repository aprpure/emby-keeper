from pathlib import Path
import random
from tqdm import tqdm

from PIL import Image
from pyrogram.enums import ParseMode

from embykeeper.telegram.session import ClientsSession
from embykeeper.cli import AsyncTyper
from embykeeper.config import config

app = AsyncTyper()

bot = "jmsembybot"
chat = "api_group"


@app.async_command()
async def generate(config_file: Path, output: Path = "captchas.txt"):
    await config.reload_conf(config_file)
    async with ClientsSession(config.telegram.account[:1]) as clients:
        async for _, tg in clients:
            photos = []
            try:
                async for msg in tg.get_chat_history(bot):
                    if msg.photo:
                        photos.append(msg.photo.file_id)
            finally:
                with open(output, "a+", encoding="utf-8") as f:
                    f.writelines(str(photo) + "\n" for photo in photos)


@app.async_command()
async def label(config_file: Path, inp: Path = "captchas.txt"):
    """使用 LLM 对验证码进行自动标记."""
    import asyncio
    from embykeeper import llm

    await config.reload_conf(config_file)
    output = Path(__file__).parent / "data"
    output.mkdir(exist_ok=True, parents=True)
    with open(inp) as f:
        photos = [l.strip() for l in f.readlines()]
        random.shuffle(photos)
    async with ClientsSession(config.telegram.account[:1]) as clients:
        async for tg in clients:
            for photo in tqdm(photos, desc="标记验证码"):
                data = await tg.download_media(photo, in_memory=True)
                image_bytes = data.getvalue()
                ocr_text = await llm.ocr(image_bytes)
                if not ocr_text:
                    continue
                await tg.send_photo(
                    chat, photo, caption=f"`{ocr_text}`", parse_mode=ParseMode.MARKDOWN
                )
                labelmsg = await tg.wait_reply(chat, timeout=None, outgoing=True)
                if not len(labelmsg.text) == 4:
                    continue
                else:
                    image = Image.open(data)
                    image.save(output / f"{labelmsg.text}.png")


if __name__ == "__main__":
    app()
