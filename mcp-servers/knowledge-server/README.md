# TypeScript Knowledge MCP Server

```powershell
npm install
npm run build
npm start
```

该 Server 通过 STDIO 暴露 `lookup_concept` 工具。STDIO 用于 JSON-RPC，因此普通日志只能写入 stderr；源码使用 `console.error`，不要改成 `console.log`。
