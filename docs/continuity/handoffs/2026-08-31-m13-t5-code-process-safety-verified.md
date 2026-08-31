# M13-T5 交接：代码 Agent 资源与进程树安全验证通过

- 日期：2026-08-31，Asia/Shanghai
- 完成任务：`M13-T5 / verified`
- 验证基线：`4c029bb500cf96b1e7647a5c7f9f4631d33cf538`
- 验证记录：`V-20260831-005`
- 关联决策：`ADR-0038`
- 在线模型/付费调用：未执行，费用 0

## 本轮结果

`ControlledCodeAgent` 不再通过 `subprocess.run(capture_output=True)` 完整缓冲命令输出。新的标准库
process runner 以两个 reader 持续排空 stdout/stderr，只保留有界前缀；timeout、取消、资源
超限、监控失败和正常 parent 退出均进入整棵进程树清理。

Windows 使用 kill-on-close Job Object，Linux 使用独立 session/process group。服务端
`ProcessResourceLimits` 固定进程数、进程树内存和 CPU；审计增加 observed bytes、termination、
resource、process scope 和 cleanup 结果，但不包含 stdout/stderr、argv、环境或原始异常。

## 修改文件

- 进程边界：`backend/app/advanced/process_runner.py`。
- 代码 Agent/预算/导出：`backend/app/advanced/code_agent.py`、`harness.py`、`__init__.py`。
- 测试：`backend/tests/test_code_agent_process.py`；既有 `test_code_agent.py` 未改且全部回归。
- 决策/规约：`ADR-0038`、`BACKEND_CODING_STANDARDS.md`。
- 连续性：实施计划、verification、known issues、status 和本 handoff。
- 未修改 `docs/progress.md`，学习者个人进度保持不变。

## 实际验证

| 范围 | 结果 |
| --- | --- |
| Windows 定向合同 | 20 项通过、1 项既有 symlink 能力 skip；真实 junction 通过 |
| Linux 一次性无网络/只读容器 | 同一 20 项通过、仅 Windows junction 按平台 skip；容器 `--rm` |
| 输出/进程故障 | 8 MiB 洪泛、无限输出、timeout、取消、嵌套 marker 均通过 |
| 资源预算 | Windows/Linux 的 CPU、tree memory、process count 均实际触发稳定分类并清理树 |
| 完整 offline 门 | 后端 691 项通过、1 项既有 symlink skip；Demo 与 `pip check` 通过 |
| AST | 四个改动 Python 文件只读解析通过 |

## 保留的失败与修复

1. 沙箱内既有 7 项在 `TemporaryDirectory` setup 被 Windows Temp ACL 拒绝；相同命令沙箱外通过。
2. 首轮 junction 新测试的生产断言通过，但 cleanup 在 `tearDown` 后重复删除 junction；只调整测试
   夹具为断言后 `finally` 清理，最终通过。
3. `py_compile` 只因沙箱拒绝写仓库 `__pycache__` 失败；随后 AST 只读解析和真实 import/执行均
   通过，没有把写权限错误记录成语法失败。

## 未验证与保留边界

- 10ms 资源采样允许一个采样间隔的短暂超限；不是 cgroup/seccomp/VM 硬隔离。
- Windows Job assignment 不是 suspended-create 原子绑定；只允许服务端审核的 executable/argv。
- 独立 `ControlledCodeAgent` 没有默认禁网或强 workspace 隔离；Linux 验证容器的
  `--network none` 只属于该次验证环境。
- `KI-016` 的 durable/数据库生产故障和 `KI-017` 的普通同步工具 thread 仍未关闭。

## 下一条原子动作

恢复 M13-T6：只读审查现有 load/eval/observability、RunCoordinator、PostgreSQL 故障注入和部署
脚本，列出并发 Run、慢客户端、数据库断开、模型限流和重启恢复的最小场景、指标、资源归属与
清理合同。未经新授权不执行有状态压测、不读取 Key/用户 `.env`、不调用在线 Provider、不 push。

## 交接时工作区

本 handoff 创建时 M13-T5 实现与连续性文件尚未提交；`main` 基线为 `4c029bb`，相对
`origin/main` 已含三个既有本地提交。结束前只提交 M13-T5 文件，不 push；新 HEAD 由后续
verification/status 锚点记录。
