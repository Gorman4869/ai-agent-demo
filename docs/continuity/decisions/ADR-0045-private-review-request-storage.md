# ADR-0045：私有 review request 与 Run 原子创建

- 状态：accepted
- 日期：2026-10-29
- 任务：M14-T6
- 依赖：ADR-0044、ADR-0015

## 背景

显式内存创建 API 已将六个业务字段纳入 Run request digest，但原始 spec 只在进程内 catalog。
PostgreSQL 重启后仅靠 digest 无法恢复 resource IDs、topic、revision 和 decision。它们属于服务端
绑定的控制面，不能从 input_text、answer、公开事件、Memory fact 或模型输出重新推断。

## 决策

1. app migration 8 新增私有 `review_run_requests`，每个 Run 最多一条；保存 scenario version、六个
   业务字段和 request digest，run_id 为主键及 agent_runs 外键，随 Run 删除。
2. `PostgresReviewRequestStore` 与 PostgresRunStore 共享 async pool。抽取原有 create 的同 connection
   内部方法，保留已有幂等与冲突顺序；在同一事务创建 Run、序列计数器和 spec，任何一步失败全部回滚。
   普通 RunStore.create 的公开合同不变，不引入可插拔事务回调或第二套 Run 状态机。
3. owner/key 幂等与 Run request digest 沿用既有合同。create replay 返回原 Run；缺失私有绑定 fail closed，
   不在旧 Run 上补写客户端提交的 spec。普通 memory 和 PostgreSQL adapters 共享 create/resolve 合同。
4. resolve 只通过 owner-scoped Run 关联读取；数据库数据进入边界时重建 ReviewRunSpec，并按原 Run
   session/input/options 重新计算 request digest。摘要不一致返回稳定 Store 错误，不返回部分控制面。
5. policy_topic 是私有业务字段，最多 512 UTF-8 bytes；它不同于只存摘要的 publication 表。
   原始 owner/key、不可信证据、图片/网页正文或异常不进入此表。spec 不进入公开事件、snapshot、repr
   或 probe 输出。表内 topic 不是加密存储，数据库访问控制与备份保密仍属部署责任。

## 后果与边界

- 崩溃不能留下已提交 Run 却缺少 spec 的新创建半成品；既有缺失绑定不被静默修补。
- PostgreSQL Run create 仍只有既有一次事务；没有独立连接双写或跨 pool 的原子性声称。
- 读取摘要只用于一致性校验，不是数据库管理员级防篡改证明。没有增加触发器审计或新基础设施。
- 当前只实现 request storage。Runtime 的异步 spec resolver、async approval gate 和完整 opt-in
  PostgreSQL HTTP composition 仍需下一原子步骤，不从两进程 Store 证据推断应用恢复已完成。

## 未采用

- 先 create Run 再写 spec：可能产生无法恢复的已提交 Run。
- 将 spec 放进 input_text 或公开 event：混淆数据与控制面并暴露私有 topic。
- 修改通用 RunRecord 增加任意 JSON metadata：扩大所有 Runtime 与 API 的公共合同。
- 复制整套 PostgreSQL Run create SQL：容易与原有幂等、counter 和错误顺序漂移。

验证：V-20261029-003；migration 1–8、事务回滚、digest 不一致拒绝、共享合同与两个独立 PID 恢复。
