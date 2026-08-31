# ADR-0038：受控代码命令的有界输出、资源预算与进程树所有权

- 状态：accepted
- 日期：2026-08-31
- 任务：`M13-T5`
- 依赖：`ADR-0035`

## 背景

既有 `ControlledCodeAgent` 已固定 workspace、命令 argv、cwd、环境、timeout 和输出上限，写入也
要求精确路径审批。但命令仍由 `subprocess.run(capture_output=True)` 执行：stdout/stderr 会先完整
进入内存，再做返回截断；timeout 只证明直接进程被处理，没有整棵子进程树的实际证据；同步
`run()` 也没有接收 Run 取消信号。

只把截断数值调小不能解决管道洪泛或后台子进程泄漏。另一方面，本项目的代码 Agent 是教学用
应用级 Harness，不能把 Python 进程控制描述成完整容器、虚拟机或默认断网沙箱。

## 决策

### 1. 持续排空 stdout/stderr，只保留有界前缀

`backend.app.advanced.process_runner` 以两个 daemon reader 同时持续读取 stdout/stderr。每条流最多
保留命令本次 capture limit 的字节，超过部分继续排空但立即丢弃；最终继续沿用 stdout 优先、
stderr 使用剩余额度的确定性组合规则。

审计记录实际观察到的总字节数与 `truncated`，运行预算只消费真正保留并返回的有界字节。即使
命令无限写输出，管道也不会因停止读取而反压卡死，内存不会随完整输出线性增长。

### 2. 每个命令拥有固定资源预算

`CommandSpec.resources` 使用服务端构造的 `ProcessResourceLimits`，默认限制进程数、进程树内存和
CPU 时间；命令输入不能覆盖这些值。timeout、命令输出上限以及运行级 action/input/output 预算
继续保留，分别解决墙钟时间、单命令返回和整次计划累计上限。

Windows 使用 Job Object 统计 active process、整棵 Job 的 peak memory 与 user/kernel CPU；Linux
使用独立 session/process group，并从 `/proc` 汇总同一进程组。以 10ms 有界轮询发现超限后终止
整棵树。资源监控不可用、未知平台或进程所有权无法建立时均以稳定错误失败关闭，不降级为普通
`Popen`。

### 3. timeout、取消、超限和正常退出都收口进程树

Windows Job 设置 `KILL_ON_JOB_CLOSE`；Linux 对独立进程组执行 `SIGKILL`。timeout、运行中取消、
资源超限和监控失败会主动终止整棵树；即使直接进程正常退出，也会执行一次树清理，防止后台
子进程继续持有 pipe 或在 workspace 中运行。

`ControlledCodeAgent.run()` 接受可选、只读的取消信号。动作前已取消时不计 action、不启动
进程；检查运行中取消返回 `command_cancelled`。timeout、取消、资源超限与 cleanup/output read
失败拥有不同稳定错误码，后续动作一律停止。

### 4. 审计只保留安全元数据

`ActionOutcome` 可在进程内向调用方返回有界 stdout/stderr，但字段继续 `repr=False`。持久或日志
友好的 `AuditEntry` 只增加 observed byte count、termination reason、resource limit、process
scope 和 tree cleanup 结果；不复制 stdout/stderr、完整 argv、环境或原始异常。

## 后果

- 默认路径保持离线、标准库实现、无密钥、无新依赖；既有 `CheckAction(command_name)` 和 Demo
  调用方式兼容。
- Windows 实际测试覆盖 Job Object 下的 stdout/stderr 洪泛、无限输出、timeout、取消、嵌套
  子进程、CPU/内存/进程数预算和 junction 逃逸。
- Linux 必须用真实 Linux 进程执行同一合同后，才能把跨平台范围记为已验证；Windows 成功不能
  代替 Linux 证据。
- 资源统计是 10ms 应用级采样，可能在一个采样间隔内短暂超出阈值；它不替代容器 cgroup、
  seccomp、文件系统隔离或网络策略。当前 Harness 也没有默认禁网能力。
- Windows 标准库 `Popen` 在进程创建后才暴露 handle，Job assignment 不是 suspended-create 的
  原子绑定；因此只能运行服务端审核的固定命令。需要承受恶意 executable 启动代码时，必须把
  Harness 放入预先配置资源/网络策略的容器或专用 worker，不能依赖本边界单独防护。
- 命令仍必须由服务端完整注册。Job/process group 不能把任意解释器参数、恶意二进制或不可信
  workspace 变成安全输入。

## 未采用方案

- `subprocess.run(capture_output=True)` 后再截断：仍会完整缓冲，无法处理无限输出。
- 输出达到上限后停止读取 pipe：子进程可能因 pipe 满而永久阻塞，直到 timeout。
- timeout 后只调用 `process.kill()`：无法保证嵌套或后台子进程结束。
- 引入 `psutil`：当前标准库已能覆盖 Windows/Linux 验收，不为单一任务增加依赖。
- 宣称应用级 Harness 默认断网：当前没有网络 namespace 或容器网络策略，必须如实保留为后续
  强隔离边界。

## 验证依据

- `backend/tests/test_code_agent.py`
- `backend/tests/test_code_agent_process.py`
- `backend.app.advanced.code_demo`
- 本任务对应 verification 记录
