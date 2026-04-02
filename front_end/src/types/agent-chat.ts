/**
 * 智能体对话类型定义
 * 基于 ReAct（Reasoning + Acting）范式的消息模型
 */

export type StepType = 'thought' | 'tool_call' | 'tool_result' | 'action' | 'final_answer'

export type ToolCallStatus = 'calling' | 'success' | 'error'

export interface ToolCall {
  name: string
  args: Record<string, unknown>
  status: ToolCallStatus
}

export interface ReActStep {
  type: StepType
  id: string
  content: string
  toolCall?: ToolCall
  streaming?: boolean
  sourceType?: string
}

export type MessageRole = 'user' | 'assistant'

export interface AgentMessage {
  id: string
  role: MessageRole
  content: string
  steps: ReActStep[]
  streaming?: boolean
  createdAt: Date
}

export interface ChatSession {
  id: string
  title: string
  messages: AgentMessage[]
  createdAt: Date
}
