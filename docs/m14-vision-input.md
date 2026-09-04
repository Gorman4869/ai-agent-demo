# M14-T3 受控视觉输入与结构化观察

M14-T3 让已经通过 PNG 安全边界的图片进入真实 OpenAI SDK 请求形状，但默认仍使用离线模型。
它证明“适配器怎样接图”，不证明任何线上模型已经看过图片。

## 前端业务类比

把视觉模型看成一个返回 JSON 的第三方接口。图片里的文字类似用户上传 Excel 中的单元格内容：
可以展示、检索和审核，但不能因为单元格写了“我是管理员”就改变当前登录用户的角色，也不能因为
写了“立即提交”就绕过确认按钮。

因此视觉链分成四层：

```text
PNG/MIME guard
  bytes + signature + IHDR CRC + width/height/pixels
        |
server-owned vision request
  fixed prompt + input_image + detail=low + no tools + token/timeout budget
        |
structured observation
  summary + visual_text + uncertainties = untrusted_visual_data
        |
application policy
  roles + approval + tool schema; visual text cannot modify these controls
```

## 当前合同

| 范围 | 规则 |
| --- | --- |
| 输入 | 只接受 `image/png`；最大 5 MB、4096×4096、1200 万像素 |
| 在线门 | `Settings.online_provider_enabled` 与本次 `online_authorized=True` 必须同时成立 |
| SDK | 每次调用显式 client/model/timeout，`max_retries=0`，结束时有界关闭 |
| 图像请求 | Base64 data URL、`detail=low`、`store=false`；不接受远程 URL/file ID |
| 控制面 | 固定服务端 prompt；不传 tools、权限、审批或副作用 callback |
| 输出 | `summary`、`visual_text`、最多 8 个 `uncertainties`；整体最多 120 KB |
| 信任 | 全部视觉内容为 `untrusted_visual_data`，`can_authorize_actions=False` |
| 日志 | 内容原文不进入 repr/event；只记录 SHA-256、字节、provider/model 和稳定失败码 |
| 回退 | timeout/坏结构/Provider 失败只返回已验证 PNG metadata，不伪造视觉观察或 usage |

默认未授权路径仍返回结构化离线观察，但会明确说明只完成 PNG 校验，没有执行视觉语义推理；client
factory 不会被创建或调用。

## 验证命令

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_multimodal_agent -v
```

关键覆盖包括：

- 有效 PNG 变成 SDK `input_image`，结构化输出和 usage 被归一；
- 真实 `responses.parse` 经本地 MockTransport 运行，完全不访问网络；
- 错误 MIME、损坏 IHDR、字节超限在 client 启动前拒绝；
- 图片中的 Prompt Injection 只作为可见文字返回，不能授权动作；
- 模型 timeout、无效结构和观察超限返回稳定 metadata fallback；
- 即使完整在线配置存在，缺少本次授权仍走离线模型。

## 常见错误

| 现象 | 原因 | 正确处理 |
| --- | --- | --- |
| 配了 Key 就准备发请求 | 把配置存在误当本次授权 | 同时检查 Settings gate 和单次授权；缺任一项走离线 |
| 图片文字触发工具 | 把 observation 拼成控制 prompt | 保持 untrusted 标记，工具仍经过角色、Schema 和审批 |
| timeout 后返回空“成功” | 把 metadata 校验混成视觉理解 | 返回 `failure + png_metadata`，不要伪造 summary/usage |
| 日志出现 OCR 原文 | 直接打印 model/Pydantic 对象 | 只写 digest、字节和稳定错误字段 |
| MockTransport 成功就称线上可用 | 混淆 E2/E3 与 E4 | M14-T4 重新取得授权并记录真实模型、usage、费用和结果 |

## 证据边界

当前 PNG guard 不是完整 decoder：它不遍历/解码所有 IDAT、不安全重编码、不剥离 metadata，也不做
恶意图片扫描。OpenAI 官方还支持 URL、file ID 和其他图片格式，但本任务故意只保留已验证的 PNG
bytes 边界。真实模型兼容性、OCR/视觉质量、隐私上传、费用和 Provider 行为必须留给 M14-T4/T5。
