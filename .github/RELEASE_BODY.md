## What's Changed

- 重构验证码 OCR：`OCRService` 统一提示词组装、LLM 调用与结果清洗，`checkiner` / `misty` / `link_local` / 工具脚本共用同一入口
- 新增验证码专用提示词与 `build_captcha_prompt` / `normalize_captcha`，支持长度提示、超长截断与字符范围过滤
- 修复 Peach 验证码错误后重复发送 `/start` 导致的重试循环，改为等待机器人补发新图；兼容 inline / reply 键盘，点击回调超时视为已点击
- 未配置 `[llm]` 时 OCR 只警告一次；更新 `ocr` / `bot_captcha_char_range` 配置说明
- 新增 OCR / Peach / Base / link_local OCR 单元测试

**Full Changelog**: https://github.com/emby-keeper/emby-keeper/compare/v0.0.0...v7.6.2
