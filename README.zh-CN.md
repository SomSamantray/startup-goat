# Startup India GOAT

`startup-india-goat` 是一个面向 Agent 的技能，用带引用的证据研究一家印度初创公司或有限的公司群组。它支持自然语言请求，在采集前展示研究契约，并区分公开信息与明确授权的会话。

根据可用性，它覆盖 GitHub、Reddit、X、YouTube、Web、YourStory、Screener、The Ken、Inc42、Startup India、Tracxn 和 LinkedIn。付费墙、CAPTCHA、配额、认证和模式变化都会如实标记。

每次运行会把 Markdown、HTML、版本化 JSON、已清理的原始证据和清单保存到 `STARTUP_GOAT_MEMORY_DIR`（默认 `~/Documents/StartupIndiaGOAT/`）。GOAT 评估是定性的，不输出不透明的综合分数。

请参阅 [`skills/startup-india-goat/SKILL.md`](skills/startup-india-goat/SKILL.md) 和 [`CONFIGURATION.md`](CONFIGURATION.md)。