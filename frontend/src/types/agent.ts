export type RunStatus = 'idle' | 'connecting' | 'running' | 'completed' | 'failed'

export interface AgentEvent {
  type: string
  data: {
    run_id: string
    index: number
    answer?: string | null
    error?: string | null
  }
  receivedAt: string
}

export interface Evidence {
  title: string
  source: string
  excerpt: string
  score: number
}

export interface ResearchResult {
  approved: boolean
  answer: string
  critique: string
  evidence: Evidence[]
}
