import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { z } from 'zod'

const knowledge: Record<string, string> = {
  agent: 'Agent 是由模型、工具与循环控制组成的程序。',
  mcp: 'MCP 用统一协议连接 Agent 客户端与外部工具、资源和提示。',
  rag: 'RAG 先检索证据，再把证据加入模型上下文生成回答。',
}

const server = new McpServer({
  name: 'ai-agent-learning-knowledge',
  version: '0.1.0',
})

server.registerTool(
  'lookup_concept',
  {
    description: 'Look up one AI Agent course concept.',
    inputSchema: {
      name: z.string().min(1).describe('Concept name, such as agent, mcp, or rag'),
    },
  },
  async ({ name }) => ({
    content: [
      {
        type: 'text',
        text: knowledge[name.trim().toLowerCase()] ?? '未找到该概念',
      },
    ],
  }),
)

server.registerTool(
  'list_concepts',
  {
    description: 'List all AI Agent course concepts.',
    inputSchema: {},
  },
  async() =>({
    content: [{type:'text',text:JSON.stringify(Object.keys(knowledge))}],
  })
)

async function main(): Promise<void> {
  const transport = new StdioServerTransport()
  await server.connect(transport)
  console.error('Knowledge MCP server is running on stdio')
}

main().catch((error: unknown) => {
  console.error('Knowledge MCP server failed:', error)
  process.exit(1)
})
