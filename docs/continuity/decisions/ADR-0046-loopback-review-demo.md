# ADR-0046：显式 loopback 合成审查演示入口

- 状态：accepted
- 日期：2026-10-29
- 任务：M14-T6
- 依据：ADR-0044/0045，前端规约的静态凭据禁止规则

## 决策

新增独立 `backend.app.review_demo` 启动入口，CLI 固定绑定 127.0.0.1:8000。只装载 server-owned
合成 PNG、policy、Browser fixture 和内存 review revision/publication。视觉固定 OfflineVisionModel，
网页读取真实 PlaywrightBrowserDriver 的 route-fulfilled fixture；不选择 Provider、不读取模型 Key。

该入口明确没有登录：服务端为本地操作员提供固定的合成 reviewer。请求只接受 loopback client 和
localhost/127.0.0.1 Host；普通 create_app、create_review_app 和 PostgreSQL factory 不使用此身份。
前端通过 Vite 同源代理调用现有接口，不打包或保存静态 Bearer Token。所有副作用仅修改演示内存表。

## 边界

- 这是显式 local-only 教学身份，不是匿名用户在普通应用中的权限提升，也不是生产身份验证。
- 不将该入口暴露公网或通过反向代理转发给其他用户；默认 app 的 Principal/审批规则不变。
- 重启演示后端会丢失内存记录；刷新页面只恢复仍存在的同一 Run。PostgreSQL应用恢复引用前序独立验证。
- 本地 Web UI 与后端 Chromium 的完整演示可以无 Key 重现，但不能证明在线视觉、真实账单或公网安全。

验证：V-20261029-005，loopback/Host测试与真实 Chromium 创建、审批、刷新闭环。
