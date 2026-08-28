# M11-T7 交接：DashScope 在线 Embedding 冒烟已验证

- 日期：2026-08-28
- 任务：`M11-T7 / verified`
- 验证：`V-20260828-006`
- 验证基线：`5ed22c5`

## 已验证事实

- 在用户单次授权下，DashScope `text-embedding-v4` 已真实完成隔离 `vector(64)` pgvector 的文档向量化、查询向量化、写入与查询。
- 输出为 provider=`dashscope`、model=`text-embedding-v4`、dimensions=`64`、batch size=`1`、2 次 Provider 请求、27 input/total tokens、约 2077 ms；美元费用和来源仍为 unknown。
- 本次只在临时子进程移除了 SOCKS `ALL_PROXY/all_proxy`，没有修改 Windows 用户环境变量、全局代理或依赖。只读确认临时文档计数为 0。

## 保留边界

- 一次受控冒烟不是生产延迟、吞吐、稳定性、开放域检索质量或费用账单证据。
- 既有 OpenAI 失败历史、M11-T6 三维固定评测表及 `m11-rag-v1` 保持不变。

## 下一条原子动作

M11-T7 已完成。M11-T8 是学习交付与验收任务，当前按用户要求暂停；未经用户明确改优先级，不进入 M12 或执行新的在线调用。
