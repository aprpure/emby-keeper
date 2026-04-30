import asyncio
import base64
from html import unescape
from io import BytesIO
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from curl_cffi.requests import AsyncSession
from loguru import logger

from embykeeper import llm
from embykeeper.config import config
from embykeeper.ocr import OCRService
from embykeeper.utils import get_proxy_str


class LocalLink:
    def __init__(self, client):
        self.client = client
        self.log = logger.bind(scheme="telelink", username=client.me.full_name, backend="local")

    @property
    def cfg(self):
        return getattr(config, "llm", None)

    @property
    def mode(self) -> str:
        cfg = self.cfg
        return (getattr(cfg, "mode", None) or "auto").lower() if cfg else "auto"

    @property
    def helper_command(self) -> Optional[str]:
        cfg = self.cfg
        return getattr(cfg, "helper_command", None) if cfg else None

    @property
    def helper_timeout(self) -> int:
        cfg = self.cfg
        return int(getattr(cfg, "helper_timeout", 120) or 120) if cfg else 120

    @property
    def has_llm(self) -> bool:
        cfg = self.cfg
        return bool(cfg and getattr(cfg, "api_key", None))

    @property
    def has_helper(self) -> bool:
        return bool(self.helper_command)

    @property
    def enabled(self) -> bool:
        cfg = self.cfg
        return bool(cfg and (self.has_llm or self.has_helper or self.mode == "local"))

    @property
    def allow_remote_fallback(self) -> bool:
        return self.mode != "local"

    def supports_service(self, service: str) -> bool:
        if service == "registrar":
            return True

        cfg = self.cfg
        if not cfg:
            return False

        supported = {"ocr"}
        if self.has_llm:
            supported.update({"gpt", "visual", "prime", "super", "pornemby_pack"})
        if self.has_helper:
            supported.update(
                {
                    "gpt",
                    "visual",
                    "captcha",
                    "prime",
                    "super",
                    "pornemby_pack",
                }
            )
        if self.mode == "local":
            supported.update({"prime", "super", "pornemby_pack"})

        supported.update(getattr(cfg, "auth_services", None) or [])
        return service in supported

    async def auth(self, service: str, log_func=None) -> bool:
        if self.supports_service(service):
            return True

        if log_func:
            if not self.cfg:
                log_func("初始化错误: 已启用 skip_auth = true, 但未配置 llm 或本地 helper, 无法替代 @embykeeper_auth_bot.")
            elif service == "captcha":
                log_func("初始化错误: 已启用本地 LLM 模式, 但未配置 llm.helper_command 以处理验证码令牌请求.")
            elif service in {"gpt", "visual"}:
                log_func("初始化错误: 已启用本地 LLM 模式, 但未配置 llm.api_key 或 llm.helper_command.")
            else:
                log_func(f"初始化错误: 已启用本地 LLM 模式, 但本地后端未声明支持服务 {service.upper()}.")
        return False

    async def _run_helper(self, method: str, payload: Dict[str, Any]) -> Optional[Any]:
        if not self.helper_command:
            return None

        request = {
            "method": method,
            "instance": str(getattr(self.client, "me", None) and self.client.me.id or ""),
            **payload,
        }
        proc = await asyncio.create_subprocess_shell(
            self.helper_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(json.dumps(request, ensure_ascii=False).encode("utf-8")),
                timeout=self.helper_timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            self.log.warning(f"本地 helper 执行超时: {method}.")
            return None

        stderr_text = stderr.decode("utf-8", errors="ignore").strip()
        if proc.returncode != 0:
            if stderr_text:
                self.log.warning(f"本地 helper 执行失败 ({method}): {stderr_text}")
            else:
                self.log.warning(f"本地 helper 执行失败 ({method}), 返回值 {proc.returncode}.")
            return None

        output = stdout.decode("utf-8", errors="ignore").strip()
        if not output:
            if stderr_text:
                self.log.debug(f"本地 helper 无输出 ({method}): {stderr_text}")
            return None

        try:
            result = json.loads(output)
        except json.JSONDecodeError:
            return output

        if isinstance(result, dict):
            status = result.get("status")
            if status == "error":
                self.log.warning(f"本地 helper 返回错误 ({method}): {result.get('errmsg') or 'unknown'}.")
                return None
            if "result" in result:
                return result["result"]
        return result

    async def gpt(self, prompt: str) -> Tuple[Optional[str], Optional[str]]:
        if self.has_llm:
            answer = await llm.gpt(prompt)
            if answer:
                self.log.debug("LLM 智能回答成功.")
                return answer, "llm"
        result = await self._run_helper("gpt", {"prompt": prompt})
        if isinstance(result, dict):
            answer = result.get("answer")
            by = result.get("by") or "helper"
            if answer:
                return answer, by
        elif isinstance(result, str):
            return result, "helper"
        return None, None

    async def infer(self, prompt: str) -> Tuple[Optional[str], Optional[str]]:
        answer, by = await self.gpt(prompt)
        return answer, by

    async def terminus_answer(self, question: str) -> Tuple[Optional[str], Optional[str]]:
        prompt = (
            "你正在辅助回答 Telegram 机器人考试题. "
            "请直接给出最可能正确的答案. 如果题目包含选项, 优先输出选项原文或选项字母; "
            "如果题目要求输出固定文本, 则精确输出该文本. 不要解释.\n\n"
            f"{question}"
        )
        answer, by = await self.gpt(prompt)
        if answer:
            return answer.strip(), by
        result = await self._run_helper("terminus_answer", {"question": question})
        if isinstance(result, dict):
            answer = result.get("answer")
            by = result.get("by") or "helper"
            if answer:
                return answer.strip(), by
        elif isinstance(result, str):
            return result.strip(), "helper"
        return None, None

    async def pornemby_answer(self, question: str) -> Tuple[Optional[str], Optional[str]]:
        prompt = (
            "你正在回答单选题. 请只输出一个选项字母 A/B/C/D, 禁止输出解释或其他内容.\n\n"
            f"{question}"
        )
        answer, by = await self.gpt(prompt)
        if answer:
            match = re.search(r"\b([ABCD])\b", answer.upper())
            if match:
                return match.group(1), by
        result = await self._run_helper("pornemby_answer", {"question": question})
        if isinstance(result, dict):
            answer = result.get("answer")
            by = result.get("by") or "helper"
        else:
            answer = result
            by = "helper"
        if isinstance(answer, str):
            match = re.search(r"\b([ABCD])\b", answer.upper())
            if match:
                return match.group(1), by
        return None, None

    async def visual(self, photo_bytes: bytes, options: List[str], question=None) -> Tuple[Optional[str], Optional[str]]:
        if self.has_llm:
            answer = await llm.visual(photo_bytes, options, question)
            if answer:
                self.log.debug(f"LLM 视觉识别成功: {answer}")
                return answer, "llm"
        result = await self._run_helper(
            "visual",
            {
                "photo_base64": base64.b64encode(photo_bytes).decode("utf-8"),
                "options": options,
                "question": question,
            },
        )
        if isinstance(result, dict):
            answer = result.get("answer")
            by = result.get("by") or "helper"
            if answer:
                return answer, by
        elif isinstance(result, str):
            return result, "helper"
        return None, None

    async def ocr(self, photo_bytes: bytes) -> Optional[str]:
        try:
            ocr = await OCRService.get()
            with ocr:
                result = await ocr.run(BytesIO(photo_bytes))
            if result:
                self.log.debug(f"本地 OCR 识别成功: {result}")
                return result
        except Exception as e:
            self.log.debug(f"本地 OCR 识别失败: {e}")

        if self.has_llm:
            answer = await llm.ocr(photo_bytes)
            if answer:
                self.log.debug(f"LLM OCR 识别成功: {answer}")
                return answer

        result = await self._run_helper(
            "ocr",
            {"photo_base64": base64.b64encode(photo_bytes).decode("utf-8")},
        )
        if isinstance(result, dict):
            return result.get("answer") or result.get("result")
        elif isinstance(result, str):
            return result
        return None

    def _html_to_text(self, html: str) -> str:
        html = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", html)
        html = re.sub(r"(?i)<br\\s*/?>", "\n", html)
        html = re.sub(r"(?i)</(p|div|li|tr|td|h1|h2|h3|h4|h5|h6)>", "\n", html)
        html = re.sub(r"(?s)<[^>]+>", " ", html)
        text = unescape(html)
        lines = []
        for line in text.splitlines():
            normalized = re.sub(r"[ \t\xa0]+", " ", line).strip()
            if normalized:
                lines.append(normalized)
        return "\n".join(lines)

    async def captcha_content(self, site: str, url: str = None) -> Optional[str]:
        if url:
            try:
                async with AsyncSession(
                    proxy=get_proxy_str(config.proxy, curl=True),
                    impersonate="chrome",
                    timeout=20.0,
                    allow_redirects=True,
                ) as session:
                    resp = await session.get(url)
                    if resp.ok:
                        content_type = (resp.headers.get("content-type") or "").lower()
                        if content_type.startswith("image/"):
                            result = await self.ocr(resp.content)
                            if result:
                                return result.strip()
                        else:
                            text = self._html_to_text(resp.text)
                            if text:
                                if self.has_llm:
                                    prompt = (
                                        "以下是网页可见文本. 请提取用户打开网页后需要复制回复的最终正文. "
                                        "只输出最终正文, 禁止解释.\n\n"
                                        f"站点: {site}\nURL: {url}\n\n网页文本:\n{text[:12000]}"
                                    )
                                    answer = await llm.gpt(prompt)
                                    if answer:
                                        return answer.strip()
                                if len(text) <= 200:
                                    return text.strip()
            except Exception as e:
                self.log.debug(f"本地抓取网页验证码内容失败: {e}")

        result = await self._run_helper("captcha_content", {"site": site, "url": url})
        if isinstance(result, dict):
            return result.get("content") or result.get("answer") or result.get("result")
        elif isinstance(result, str):
            return result
        return None

    async def captcha(self, site: str, url: str = None) -> Optional[str]:
        result = await self._run_helper("captcha", {"site": site, "url": url})
        if isinstance(result, dict):
            return result.get("token") or result.get("answer") or result.get("result")
        elif isinstance(result, str):
            return result
        return None

    async def cf_clearance(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        result = await self._run_helper("cf_clearance", {"url": url})
        if isinstance(result, dict):
            return result.get("cf_clearance"), result.get("useragent")
        return None, None

    async def wssocks(self) -> Tuple[Optional[str], Optional[str]]:
        result = await self._run_helper("wssocks", {})
        if isinstance(result, dict):
            return result.get("url"), result.get("token")
        return None, None

    async def captcha_wssocks(
        self, token: str, url: str, user_agent: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        result = await self._run_helper(
            "captcha_wssocks",
            {"token": token, "url": url, "user_agent": user_agent},
        )
        if isinstance(result, dict):
            return result.get("cf_clearance"), result.get("useragent")
        return None, None

    async def send_log(self, message: str) -> bool:
        result = await self._run_helper("send_log", {"message": message})
        if isinstance(result, dict):
            success = result.get("success")
            if success is not None:
                return bool(success)
        elif isinstance(result, bool):
            return result
        self.log.info(f"本地日志推送替代: {message}")
        return True

    async def send_msg(self, message: str) -> bool:
        result = await self._run_helper("send_msg", {"message": message})
        if isinstance(result, dict):
            success = result.get("success")
            if success is not None:
                return bool(success)
        elif isinstance(result, bool):
            return result
        self.log.info(f"本地即时消息替代: {message}")
        return True