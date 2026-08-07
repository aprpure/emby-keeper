from urllib.parse import parse_qs, urlparse

from curl_cffi.requests import AsyncSession, RequestsError
from pyrogram.types import Message
from pyrogram.raw.functions.messages import RequestWebView

from embykeeper.config import config
from embykeeper.runinfo import RunStatus
from embykeeper.utils import to_iterable, truncate_str, get_proxy_str

from ..link import Link
from ._templ_a import TemplateACheckin


class MooncakeCheckin(TemplateACheckin):
    name = "月饼"
    bot_username = "Moonkkbot"
    bot_use_captcha = False
    bot_checkin_cmd = "/start"
    templ_panel_keywords = ["用户面板"]

    # 月饼改版后, 签到由 embyguard 服务端完成, 客户端仅提交 Telegram WebApp 数据.
    # 流程参考前端 TelegramVerifyView: 先 POST /telegram/checkin (init_data),
    # 若返回需要 Turnstile, 再 POST /telegram/checkin/{challenge} (init_data + turnstile_token).
    api_base = "https://embyguard.com/api/v1"

    async def message_handler(self, client, message: Message):
        text = message.caption or message.text
        if (
            text
            and any(keyword in text for keyword in to_iterable(self.templ_panel_keywords))
            and message.reply_markup
        ):
            keys = [k for r in message.reply_markup.inline_keyboard for k in r]
            for k in keys:
                if "签到" in k.text and k.web_app:
                    url = k.web_app.url
                    bot_peer = await self.client.resolve_peer(self.bot_username)
                    url_auth = (
                        await self.client.invoke(
                            RequestWebView(peer=bot_peer, bot=bot_peer, platform="ios", url=url)
                        )
                    ).url
                    init_data = parse_qs(urlparse(url_auth).fragment).get("tgWebAppData", [None])[0]
                    server = parse_qs(urlparse(url).query).get("server", [None])[0]
                    if not init_data or not server:
                        self.log.warning("签到失败: 无法获取 WebApp 数据或 server 参数.")
                        return await self.fail()
                    return await self.do_checkin(server, init_data, url)
            else:
                self.log.warning("签到失败: 未找到签到按钮.")
                return await self.fail()

        if message.text and "请先点击下面加入我们的" in message.text:
            self.log.warning("签到失败: 账户错误.")
            return await self.fail()

        await super().message_handler(client, message)

    async def do_checkin(self, server: str, init_data: str, webview_url: str):
        """向 embyguard 服务端提交签到, 并根据返回状态结束或重试."""
        api = f"{self.api_base}/servers/{server}"
        headers = {
            "Content-Type": "application/json",
            "Referer": webview_url,
            "Origin": f"{urlparse(webview_url).scheme}://{urlparse(webview_url).netloc}",
        }
        for i in range(10):
            try:
                async with AsyncSession(
                    proxy=get_proxy_str(config.proxy, curl=True),
                    impersonate="chrome",
                    timeout=20.0,
                    allow_redirects=True,
                    headers=headers,
                ) as session:
                    resp = await session.post(f"{api}/telegram/checkin", json={"init_data": init_data})
                    result = resp.json()
                    error = result.get("error") if isinstance(result, dict) else None
                    if error:
                        msg = error.get("message", "") if isinstance(error, dict) else ""
                        code = error.get("code", "") if isinstance(error, dict) else ""
                        self.log.warning(f"签到失败: 接口返回错误 ({code}): {msg}.")
                        return await self.retry()
                    status = result.get("status")
                    if status in ("checked_in", "already_checked_in", "pending"):
                        return await self._handle_result(status, result)
                    # 否则需要先通过 Cloudflare Turnstile 验证
                    challenge = result.get("challenge")
                    site_key = result.get("site_key")
                    if not challenge or not site_key:
                        self.log.warning(
                            f"签到失败: 需要验证码但返回配置异常:\n{truncate_str(str(result), 200)}"
                        )
                        return await self.retry()
                    token = await Link(self.client).captcha("mooncake")
                    if not token:
                        self.log.warning("签到失败: 验证码解析失败, 正在重试.")
                        return await self.retry()
                    resp = await session.post(
                        f"{api}/telegram/checkin/{challenge}",
                        json={"init_data": init_data, "turnstile_token": token},
                    )
                    result = resp.json()
                    status = result.get("status")
                    if status in ("checked_in", "already_checked_in", "pending"):
                        return await self._handle_result(status, result)
                    self.log.warning(
                        f"签到失败: 验证码提交后返回异常:\n{truncate_str(str(result), 200)}"
                    )
                    return await self.retry()
            except (RequestsError, OSError, ValueError):
                self.log.warning(
                    f"无法连接到签到接口, 可能是网络或代理不稳定, 正在重试 ({i+1}/10)."
                )
                continue
            except Exception as e:
                self.log.warning(f"签到失败: 接口返回异常: {e.__class__.__name__}: {e}.")
                return await self.fail()
        self.log.warning("无法连接到签到接口, 重试超限.")
        return await self.retry()

    async def _handle_result(self, status: str, result: dict):
        balance = result.get("wallet_balance", "")
        if status == "checked_in":
            reward = result.get("reward", "")
            self.log.info(f"[yellow]签到成功[/]: 获得奖励 {reward}, 当前余额 {balance}.")
            return await self.finish(RunStatus.SUCCESS, "签到成功")
        elif status == "already_checked_in":
            self.log.info(f"今日已经签到, 当前余额 {balance}.")
            return await self.finish(RunStatus.NONEED, "今日已签到")
        else:  # pending
            self.log.info("签到结果待核对, 请勿重复签到.")
            return await self.finish(RunStatus.NONEED, "签到结果待核对")
