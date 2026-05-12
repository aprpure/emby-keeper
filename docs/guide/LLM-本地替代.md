# LLM 本地替代

本文说明 `telegram.account.skip_auth = true` 时, Embykeeper 如何用本地 LLM / helper 替代 `@embykeeper_auth_bot`.

## 路由规则

- `skip_auth = false`: 所有 `Link` 请求保持原行为, 继续发给远端 `@embykeeper_auth_bot`.
- `skip_auth = true`: 所有 `Link` 能力切换到本地后端 `LocalLink`, 不再访问远端认证机器人.

这意味着当前账号是否启用本地替代, 完全由该账号的 `skip_auth` 决定, 而不是由 `llm.mode` 决定.

## 能力映射

| Link 接口 | `skip_auth = false` | `skip_auth = true` |
| ----- | ----- | ----- |
| `auth(service)` | 远端 `/auth` | 本地能力探测, 校验 `llm` / `helper_command` 是否足够 |
| `gpt(prompt)` | 远端 `/gpt` | `llm.gpt()` 或 helper `gpt` |
| `infer(prompt)` | 远端 `/infer` | 复用本地 `gpt` |
| `visual(photo, options)` | 远端 `/visual` | `llm.visual()` 或 helper `visual` |
| `ocr(photo)` | 远端 `/ocr` | 本地 `OCRService` -> `llm.ocr()` -> helper `ocr` |
| `terminus_answer(question)` | 远端 `/terminus_answer` | 本地 prompt 包装后调用 `gpt` 或 helper |
| `pornemby_answer(question)` | 远端 `/pornemby_answer` | 本地 prompt 包装后调用 `gpt` 或 helper |
| `captcha(site, url)` | 远端 `/captcha` | helper `captcha` |
| `captcha_content(site, url)` | 远端 `/captcha` | 本地抓取网页正文 / OCR, 或 helper `captcha_content` |
| `wssocks()` | 远端 `/wssocks` | helper `wssocks` |
| `captcha_wssocks(token, url)` | 远端 `/captcha_wssocks` | helper `captcha_wssocks` |
| `send_log(message)` | 远端 `/log` | helper `send_log`, 否则只记录本地日志 |
| `send_msg(message)` | 远端 `/msg` | helper `send_msg`, 否则只记录本地日志 |

## 本地能力边界

纯 LLM 可以直接覆盖的能力:

- 智能问答 `gpt`
- 图片选项识别 `visual`
- 题目求解 `terminus_answer`
- 单选题求解 `pornemby_answer`
- 部分网页正文提取 `captcha_content`

仅靠 LLM 无法可靠完成, 需要 `helper_command` 的能力:

- 验证码令牌 `captcha`
- Cloudflare / 代理隧道 `wssocks`, `captcha_wssocks`
- 需要外部推送渠道的 `send_log`, `send_msg`

## 配置示例

最小可用配置, 适合只替代问答、视觉识别、OCR:

```toml
[llm]
api_key = "sk-xxx"
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini"
vision_model = "gpt-4o-mini"
timeout = 60

[[telegram.account]]
phone = "+8612345678901"
checkiner = true
monitor = true
skip_auth = true
```

带 helper 的完整替代配置, 适合还要替代验证码令牌或日志推送:

```toml
[llm]
api_key = "sk-xxx"
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini"
vision_model = "gpt-4o-mini"
helper_command = "python local_helper.py"
helper_timeout = 120

[[telegram.account]]
phone = "+8612345678901"
checkiner = true
monitor = true
messager = true
skip_auth = true
```

## 常见结果

- 如果 `skip_auth = false`, 即使配置了 `llm`, 远端 `@embykeeper_auth_bot` 仍然会被使用.
- 如果 `skip_auth = true` 但没有配置 `llm` 或 `helper_command`, 依赖远端能力的站点会在初始化阶段直接报缺少本地替代能力.
- 如果 `skip_auth = true` 且只配置了 `llm.api_key`, 那么问答、视觉、OCR 等能力可用, 但验证码令牌和 Cloudflare 会话类能力仍然需要 `helper_command`.