# ADR-0005：显式 Settings，不自动加载 dotenv

- 状态：accepted
- 日期：2026-07-16
- 关联任务：`M8-T1`
- 取代：无

## 背景

现有后端通过 `os.getenv()` 读取服务端认证配置，API Schema 使用 Pydantic v2，领域对象主要使用冻结 dataclass。`pydantic-settings` 和 `python-dotenv` 当前虽存在于本地虚拟环境，但它们是 MCP 依赖链带入的传递依赖，没有在 `backend/requirements-m2.txt` 中作为本项目直接依赖锁定。

M8-T1 需要建立集中配置与应用组合根，同时必须保证默认离线、Key 不自动启用网络、密钥不进入表示或日志，并遵守“新增依赖需另行许可”的边界。

## 决策

1. 新增冻结的 Pydantic `Settings` 与 `RunBudgetSettings`，使用手写 `from_environment()` 解析进程环境。
2. 使用 `SecretStr` 保存 API Key，并从普通 dump、JSON、`repr` 和安全摘要中排除原值。
3. Runtime 与 Model Provider 分开配置：Runtime 为 `manual | agents_sdk | langgraph`，Provider 为 `mock | openai`。
4. 默认值固定为 `manual + mock + online=false`；环境中仅存在 Key 或模型名不会启用在线能力。
5. OpenAI 只有在 Provider、Runtime、在线开关、Key、模型名和有限预算全部合法时才可形成有效配置。M8-T1 只校验门禁，不执行在线调用。
6. Run 总超时、单次模型超时、模型调用次数和模型重试分别命名；Token 与费用是单 Run 累计上限，避免把模型重试策略误用于工具、数据库或副作用。
7. Key 与模型名拒绝控制字符、内部空白和异常长度，但不绑定当前供应商前缀或模型白名单。
8. 敏感 Trace 开关固定为 false；在后续里程碑建立完整脱敏策略前，配置为 true 必须拒绝启动。
9. 新增冻结 dataclass `ApplicationContainer`，仅收拢当前 Settings、Run Service、Knowledge、Memory 和 Authenticator；Runtime 与 Coordinator 在 `M8-T3` 接入。
10. `.env.example` 仅作为环境变量模板；应用不自动读取 `.env`，不引入隐式的文件优先级或工作目录差异。

## 依赖变更清单

| 项目 | 决策 | 原因 |
| --- | --- | --- |
| `backend/requirements-m2.txt` | 不变 | M8-T1 可复用项目已使用的 Pydantic 与标准库 |
| `pydantic-settings` | 不直接使用 | 当前仅为传递依赖，直接使用会形成未锁定依赖 |
| `python-dotenv` | 不直接使用 | 避免应用在不同工作目录下隐式读取本地文件 |
| OpenAI SDK/Runner | 本任务不实例化 | 真实 Runtime 属于 `M8-T4`，在线执行属于 `M8-T6` |

## 影响

- 默认应用创建保持确定性、离线和无 Key 可运行。
- 无效在线环境会在应用依赖产生副作用前失败，错误只指出配置字段，不回显原始值。
- 现有 `create_app()` 四个依赖参数继续兼容；新 Container 与旧参数不得混用，避免两个真相源。
- 模块级 `app = create_app()` 会在导入时验证进程环境；配置错误会阻止服务启动，这是预期的 fail-fast 行为。
- 后续若需要多来源 Settings、Secret Manager 或 dotenv，必须在对应里程碑取得依赖许可并新增 ADR。
