import { ref, computed, nextTick, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { areaService, alertService } from '../services'
import {
  createChatStream,
  deleteChatSession,
  generateSessionId,
  getAlertAIAnalysis,
  getAreaUsagePattern,
  getChatSessionDetail,
  getChatSessions,
  getLatestAreaAnalysis,
  generateAreaNotice,
  triggerAreaAnalysis,
  type ChatHistory,
  type ChatSessionDetail,
  type ChatSessionInfo,
} from '../services/LLM'
import type { AgentMessage, ChatSession, ReActStep, ToolCallStatus } from '../types/agent-chat'
import type { AreaItem, Alert } from '../types'

interface BackendStreamEvent {
  type?: string
  event_version?: number
  message?: string
  text?: string
  content?: string
  delta?: string
  summary?: string
  step?: string
  step_id?: string
  step_kind?: string
  step_title?: string
  step_status?: string
  status?: string
  iteration?: number
  tool_index?: number
  tool?: string
  parameters?: Record<string, unknown>
  reasoning?: string
  success?: boolean
  result_preview?: unknown
  error?: string
  action?: string
  tool_calls?: Array<Record<string, unknown>>
  outline?: string[]
  data?: unknown
}

interface MessageRuntimeState {
  planningStepId?: string
  currentToolStepId?: string
  finalActionStepId?: string
  protocolV2: boolean
  finalStarted: boolean
  finished: boolean
}

interface SidebarApp {
  id: 'area-analysis' | 'usage-pattern' | 'alert-analysis' | 'generate-notice'
  name: string
}

type ModelType = 'analysis' | 'fast' | 'reasoning' | 'deep_reasoning'

let idCounter = 0
function uid(prefix: string): string {
  idCounter += 1
  return `${prefix}_${Date.now()}_${idCounter}`
}

function toText(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === null || typeof value === 'undefined') return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function toChatHistory(messages: AgentMessage[]): ChatHistory {
  return messages
    .filter(m => !!m.content)
    .map(m => ({
      role: m.role === 'user' ? 'user' : 'assistant',
      content: m.content,
    }))
}

function mapServerSession(item: ChatSessionInfo): ChatSession {
  return {
    id: item.session_id,
    title: item.title || '新对话',
    messages: [],
    createdAt: new Date(item.created_at),
  }
}

function mapServerMessagesToAgent(detail: ChatSessionDetail): AgentMessage[] {
  return detail.messages
    .filter(msg => msg.role === 'user' || msg.role === 'assistant')
    .map(msg => ({
      id: `db_${msg.id}`,
      role: msg.role as 'user' | 'assistant',
      content: msg.content,
      steps: [],
      streaming: false,
      createdAt: new Date(msg.created_at),
    }))
}

export function useAgentChat() {
  const sessions = ref<ChatSession[]>([])
  const currentSessionId = ref<string | null>(null)
  const sidebarCollapsed = ref(false)

  const currentSession = computed(() => sessions.value.find(s => s.id === currentSessionId.value) ?? null)
  const currentMessages = computed<AgentMessage[]>(() => currentSession.value?.messages ?? [])

  const inputText = ref('')
  const isGenerating = ref(false)
  const selectedModelType = ref<ModelType>('analysis')
  const scrollRef = ref<HTMLElement>()
  const inputRef: Ref<any> = ref(null)

  const finalStartedMap = ref<Record<string, boolean>>({})
  const runtimeStates = ref<Record<string, MessageRuntimeState>>({})
  const loadedServerSessionIds = ref<Set<string>>(new Set())
  const appTriggeredBySession = ref<Record<string, Record<string, boolean>>>({})
  const appLoadingId = ref<string>('')

  const sidebarApps = ref<SidebarApp[]>([
    { id: 'area-analysis', name: '区域分析' },
    { id: 'usage-pattern', name: '使用模式分析' },
    { id: 'alert-analysis', name: '告警分析' },
    { id: 'generate-notice', name: '生成公告' },
  ])

  let abortController: AbortController | null = null

  function createSession(title = '新对话'): ChatSession {
    const session: ChatSession = {
      id: generateSessionId(),
      title,
      messages: [],
      createdAt: new Date(),
    }
    sessions.value.unshift(session)
    currentSessionId.value = session.id
    loadedServerSessionIds.value.add(session.id)
    return session
  }

  function startNewChat() {
    createSession()
  }

  async function ensureSessionMessagesLoaded(sessionId: string) {
    if (!sessionId || loadedServerSessionIds.value.has(sessionId)) return
    const detail = await getChatSessionDetail(sessionId)
    if (!detail) return

    const session = sessions.value.find(item => item.id === sessionId)
    if (!session) return

    session.messages = mapServerMessagesToAgent(detail)
    loadedServerSessionIds.value.add(sessionId)
    scrollToBottom()
  }

  async function switchSession(id: string) {
    currentSessionId.value = id
    await ensureSessionMessagesLoaded(id)
    nextTick(scrollToBottom)
  }

  async function deleteSession(id: string) {
    const idx = sessions.value.findIndex(s => s.id === id)
    if (idx === -1) return

    const deletingCurrent = currentSessionId.value === id
    sessions.value.splice(idx, 1)
    if (deletingCurrent) {
      currentSessionId.value = sessions.value[0]?.id ?? null
      if (currentSessionId.value) {
        await ensureSessionMessagesLoaded(currentSessionId.value)
      }
    }

    loadedServerSessionIds.value.delete(id)

    await deleteChatSession(id)
  }

  function showFinalAnswer(msg: AgentMessage): boolean {
    return !!finalStartedMap.value[msg.id] || (!msg.streaming && !!msg.content)
  }

  function handleSend() {
    const text = inputText.value.trim()
    if (!text || isGenerating.value) return
    inputText.value = ''
    sendMessage(text)
  }

  function sendQuickPrompt(text: string) {
    if (isGenerating.value) return
    sendMessage(text)
  }

  function selectModel(type: ModelType) {
    if (isGenerating.value) return
    selectedModelType.value = type
  }

  function ensureRuntimeState(messageId: string): MessageRuntimeState {
    if (!runtimeStates.value[messageId]) {
      runtimeStates.value[messageId] = { protocolV2: false, finalStarted: false, finished: false }
    }
    return runtimeStates.value[messageId]
  }

  function findMessageById(messageId: string): AgentMessage | null {
    for (const session of sessions.value) {
      const found = session.messages.find(m => m.id === messageId)
      if (found) return found
    }
    return null
  }

  function appendStep(msg: AgentMessage, partial: Partial<ReActStep> & Pick<ReActStep, 'type'>): ReActStep {
    const step: ReActStep = {
      id: partial.id || uid('step'),
      type: partial.type,
      content: partial.content || '',
      streaming: partial.streaming ?? false,
      toolCall: partial.toolCall,
      sourceType: partial.sourceType,
    }
    msg.steps.push(step)
    return step
  }

  function updateStep(msg: AgentMessage, stepId: string | undefined, updater: (step: ReActStep) => ReActStep) {
    if (!stepId) return
    const idx = msg.steps.findIndex(step => step.id === stepId)
    if (idx < 0) return
    msg.steps.splice(idx, 1, updater(msg.steps[idx]))
  }

  function appendStepContent(msg: AgentMessage, stepId: string | undefined, delta: string) {
    if (!delta) return
    updateStep(msg, stepId, step => ({ ...step, content: step.content + delta }))
  }

  function setStepStreaming(msg: AgentMessage, stepId: string | undefined, streaming: boolean) {
    updateStep(msg, stepId, step => ({ ...step, streaming }))
  }

  function setToolStatus(msg: AgentMessage, stepId: string | undefined, status: ToolCallStatus) {
    updateStep(msg, stepId, step => ({
      ...step,
      toolCall: step.toolCall ? { ...step.toolCall, status } : step.toolCall,
    }))
  }

  function closePlanningStep(msg: AgentMessage, state: MessageRuntimeState) {
    if (!state.planningStepId) return
    setStepStreaming(msg, state.planningStepId, false)
    state.planningStepId = undefined
  }

  function closeToolStep(msg: AgentMessage, state: MessageRuntimeState, status: ToolCallStatus = 'success') {
    if (!state.currentToolStepId) return
    setToolStatus(msg, state.currentToolStepId, status)
    setStepStreaming(msg, state.currentToolStepId, false)
    state.currentToolStepId = undefined
  }

  function formatPlan(event: BackendStreamEvent): string {
    const lines: string[] = []
    const action = event.action || 'direct_response'
    lines.push(`行动: ${action}`)

    if (Array.isArray(event.outline) && event.outline.length > 0) {
      lines.push('回答大纲:')
      for (const item of event.outline) {
        lines.push(`- ${item}`)
      }
    }

    if (Array.isArray(event.tool_calls) && event.tool_calls.length > 0) {
      lines.push('计划调用工具:')
      for (const call of event.tool_calls) {
        const tool = call.tool || call.name || 'unknown'
        const params = call.parameters || call.args || {}
        lines.push(`- ${tool}: ${toText(params)}`)
      }
    }

    return lines.join('\n')
  }

  function formatObservation(event: BackendStreamEvent): string {
    if (event.success === false) {
      return event.error ? `执行失败: ${event.error}` : '执行失败'
    }
    const preview = toText(event.result_preview)
    if (preview) {
      return `执行成功\n${preview}`
    }
    if (event.content) return event.content
    return '执行成功'
  }

  function markFinished(messageId: string) {
    const msg = findMessageById(messageId)
    if (!msg) return
    const state = ensureRuntimeState(messageId)

    closePlanningStep(msg, state)
    closeToolStep(msg, state, 'success')
    setStepStreaming(msg, state.finalActionStepId, false)

    msg.streaming = false
    state.finished = true
    isGenerating.value = false
    abortController = null
    scrollToBottom()
  }

  function normalizeToolStatus(status?: string): ToolCallStatus {
    if (status === 'error' || status === 'failed') return 'error'
    if (status === 'calling' || status === 'running') return 'calling'
    return 'success'
  }

  function stepKindToType(stepKind?: string): ReActStep['type'] {
    if (stepKind === 'planning') return 'thought'
    if (stepKind === 'tool_call') return 'tool_call'
    if (stepKind === 'tool_result') return 'tool_result'
    return 'action'
  }

  function isLegacyAgentEvent(type?: string): boolean {
    if (!type) return false
    return [
      'agent_planning',
      'agent_replanning',
      'planning_progress',
      'thought',
      'plan',
      'tool_execution',
      'observation',
      'final_generation',
    ].includes(type)
  }

  function handleBackendEvent(event: BackendStreamEvent, messageId: string) {
    const msg = findMessageById(messageId)
    if (!msg || !event || !event.type) return

    const state = ensureRuntimeState(messageId)
    if (event.type === 'step_start' || event.type === 'step_delta' || event.type === 'step_end') {
      state.protocolV2 = true
    }

    if (state.protocolV2 && isLegacyAgentEvent(event.type)) {
      return
    }

    switch (event.type) {
      case 'chain_start': {
        appendStep(msg, {
          type: 'action',
          content: event.message || '正在处理请求...',
          sourceType: event.type,
        })
        break
      }

      case 'step_start': {
        const stepId = event.step_id || uid('step')
        const stepKind = event.step_kind || ''
        const stepType = stepKindToType(stepKind)

        if (stepKind === 'planning') {
          closePlanningStep(msg, state)
          closeToolStep(msg, state, 'success')
          const planningStep = appendStep(msg, {
            id: stepId,
            type: 'thought',
            content: '',
            streaming: true,
            sourceType: event.type,
          })
          state.planningStepId = planningStep.id
          break
        }

        if (stepKind === 'tool_call') {
          closePlanningStep(msg, state)
          const toolName = event.tool || 'unknown'
          const reason = event.reasoning ? `\n原因: ${event.reasoning}` : ''
          const step = appendStep(msg, {
            id: stepId,
            type: 'tool_call',
            content: (event.message || `执行工具: ${toolName}`) + reason,
            streaming: true,
            sourceType: event.type,
            toolCall: {
              name: toolName,
              args: event.parameters || {},
              status: 'calling',
            },
          })
          state.currentToolStepId = step.id
          break
        }

        if (stepKind === 'final_generation') {
          closePlanningStep(msg, state)
          closeToolStep(msg, state, 'success')
          const step = appendStep(msg, {
            id: stepId,
            type: 'action',
            content: event.message || '生成最终回答...',
            streaming: true,
            sourceType: event.type,
          })
          state.finalActionStepId = step.id
          break
        }

        appendStep(msg, {
          id: stepId,
          type: stepType,
          content: event.message || event.step_title || '',
          streaming: true,
          sourceType: event.type,
        })
        break
      }

      case 'step_delta': {
        const delta = event.delta || event.content || event.text || ''
        if (!delta) break

        if (event.step_id) {
          const exists = msg.steps.some(step => step.id === event.step_id)
          if (!exists) {
            appendStep(msg, {
              id: event.step_id,
              type: stepKindToType(event.step_kind),
              content: '',
              streaming: true,
              sourceType: event.type,
            })
          }
          appendStepContent(msg, event.step_id, delta)
          setStepStreaming(msg, event.step_id, true)
        } else if (state.planningStepId) {
          appendStepContent(msg, state.planningStepId, delta)
          setStepStreaming(msg, state.planningStepId, true)
        }
        break
      }

      case 'step_end': {
        const stepId = event.step_id
        if (!stepId) break

        const endedStep = msg.steps.find(step => step.id === stepId)
        const endStatus = event.status || event.step_status || (event.success === false ? 'error' : 'success')

        if (endedStep?.type === 'thought') {
          const summaryText = toText(event.summary || event.message || '')
          updateStep(msg, stepId, step => ({
            ...step,
            content: step.content?.trim() ? step.content : summaryText,
            streaming: false,
          }))
          if (state.planningStepId === stepId) {
            state.planningStepId = undefined
          }
          break
        }

        if (endedStep?.type === 'tool_call') {
          const status = normalizeToolStatus(endStatus)
          setToolStatus(msg, stepId, status)
          setStepStreaming(msg, stepId, false)

          if (state.currentToolStepId === stepId) {
            state.currentToolStepId = undefined
          }

          const hasObservation = event.result_preview || event.error || event.content
          if (hasObservation) {
            const observationEvent: BackendStreamEvent = {
              success: status !== 'error',
              content: event.content,
              result_preview: event.result_preview,
              error: event.error,
            }
            appendStep(msg, {
              type: 'tool_result',
              content: formatObservation(observationEvent),
              sourceType: 'step_end',
            })
          }
          break
        }

        setStepStreaming(msg, stepId, false)
        if (state.finalActionStepId === stepId) {
          state.finalActionStepId = undefined
        }
        break
      }

      case 'agent_planning':
      case 'agent_replanning': {
        closePlanningStep(msg, state)
        const planningStep = appendStep(msg, {
          type: 'thought',
          content: event.message || '正在分析用户问题并规划执行步骤...',
          streaming: true,
          sourceType: event.type,
        })
        state.planningStepId = planningStep.id
        break
      }

      case 'planning_progress': {
        const raw = (event.content || '').trim()
        if (!raw) break

        if (!state.planningStepId) {
          const planningStep = appendStep(msg, {
            type: 'thought',
            content: '正在分析用户问题并规划执行步骤...\n',
            streaming: true,
            sourceType: 'agent_planning',
          })
          state.planningStepId = planningStep.id
        }
        appendStepContent(msg, state.planningStepId, raw)
        setStepStreaming(msg, state.planningStepId, true)
        break
      }

      case 'thought': {
        const thoughtContent = toText(event.data || event.content || event.message)

        if (state.planningStepId) {
          updateStep(msg, state.planningStepId, step => ({
            ...step,
            content: thoughtContent || step.content,
            streaming: false,
          }))
          state.planningStepId = undefined
        } else {
          appendStep(msg, {
            type: 'thought',
            content: thoughtContent,
            sourceType: event.type,
          })
        }
        break
      }

      case 'plan': {
        closePlanningStep(msg, state)
        appendStep(msg, {
          type: 'action',
          content: formatPlan(event),
          sourceType: event.type,
        })
        break
      }

      case 'tool_execution': {
        closePlanningStep(msg, state)
        const toolName = event.tool || 'unknown'
        const reason = event.reasoning ? `\n原因: ${event.reasoning}` : ''
        const step = appendStep(msg, {
          type: 'tool_call',
          content: (event.message || `执行工具: ${toolName}`) + reason,
          streaming: true,
          sourceType: event.type,
          toolCall: {
            name: toolName,
            args: event.parameters || {},
            status: 'calling',
          },
        })
        state.currentToolStepId = step.id
        break
      }

      case 'observation': {
        const status: ToolCallStatus = event.success === false ? 'error' : 'success'
        closeToolStep(msg, state, status)
        appendStep(msg, {
          type: 'tool_result',
          content: formatObservation(event),
          sourceType: event.type,
        })
        break
      }

      case 'final_generation': {
        closePlanningStep(msg, state)
        closeToolStep(msg, state, 'success')
        const step = appendStep(msg, {
          type: 'action',
          content: event.message || '生成最终回答...',
          streaming: true,
          sourceType: event.type,
        })
        state.finalActionStepId = step.id
        break
      }

      case 'content': {
        if (!state.finalStarted) {
          state.finalStarted = true
          finalStartedMap.value[msg.id] = true
          setStepStreaming(msg, state.finalActionStepId, false)
        }
        msg.content += event.text || ''
        break
      }

      case 'error': {
        closePlanningStep(msg, state)
        closeToolStep(msg, state, 'error')
        setStepStreaming(msg, state.finalActionStepId, false)

        appendStep(msg, {
          type: 'action',
          content: event.message || '处理出错',
          sourceType: event.type,
        })

        if (event.message) {
          msg.content += `${msg.content ? '\n\n' : ''}${event.message}`
          finalStartedMap.value[msg.id] = true
        }

        markFinished(msg.id)
        break
      }

      case 'chain_end': {
        markFinished(msg.id)
        break
      }

      default: {
        if (event.message || event.content) {
          appendStep(msg, {
            type: 'thought',
            content: event.message || event.content || '',
            sourceType: event.type,
          })
        }
      }
    }

    scrollToBottom()
  }

  function pushLocalAssistantMessage(title: string, body: string) {
    let session = currentSession.value
    if (!session) {
      session = createSession(title)
    }

    session.messages.push({
      id: uid('msg_assistant_local'),
      role: 'assistant',
      content: `## ${title}\n\n${body}`,
      steps: [],
      streaming: false,
      createdAt: new Date(),
    })

    scrollToBottom()
  }

  async function getPreferredArea(): Promise<AreaItem | null> {
    const areas = await areaService.getAll({}, true)
    if (!Array.isArray(areas) || areas.length === 0) return null
    const sorted = [...areas].sort((a, b) => (Number(b.detected_count) || 0) - (Number(a.detected_count) || 0))
    return sorted[0] || null
  }

  async function runAreaAnalysisApp() {
    const area = await getPreferredArea()
    if (!area) {
      pushLocalAssistantMessage('区域AI分析', '未找到可分析区域，请先检查区域数据。')
      return
    }

    try {
      const latest = await getLatestAreaAnalysis(area.id)
      pushLocalAssistantMessage(
        `区域AI分析 - ${latest.area_name}`,
        `${latest.analysis_text || '暂无分析文本'}\n\n状态: ${latest.alert_status || 'normal'}\n提示: ${latest.alert_message || '无'}`,
      )
      return
    } catch (error: any) {
      const code = error?.response?.status
      if (code !== 404) {
        throw error
      }
    }

    const triggered = await triggerAreaAnalysis(area.id)
    pushLocalAssistantMessage(
      `区域AI分析 - ${area.name}`,
      triggered?.message || '已触发后台分析任务，请稍后再次点击查看结果。',
    )
  }

  async function runUsagePatternApp() {
    const area = await getPreferredArea()
    if (!area) {
      pushLocalAssistantMessage('使用模式分析', '未找到可分析区域，请先检查区域数据。')
      return
    }

    const result = await getAreaUsagePattern(area.id)
    const asObj = result as any
    const pattern = asObj?.data?.id ? asObj.data : (asObj?.id ? asObj : null)
    if (!pattern) {
      pushLocalAssistantMessage(
        `使用模式分析 - ${area.name}`,
        asObj?.message || '当前暂无可用分析结果，后台可能仍在生成。',
      )
      return
    }

    const peak = Array.isArray(pattern.peak_hours) ? pattern.peak_hours.join('、') : toText(pattern.peak_hours)
    const quiet = Array.isArray(pattern.quiet_hours) ? pattern.quiet_hours.join('、') : toText(pattern.quiet_hours)

    pushLocalAssistantMessage(
      `使用模式分析 - ${pattern.area_name}`,
      `高峰时段: ${peak || '暂无'}\n低峰时段: ${quiet || '暂无'}\n平均停留(分钟): ${pattern.average_duration ?? '暂无'}\n典型人群: ${pattern.typical_user_groups || '暂无'}`,
    )
  }

  async function runAlertAnalysisApp() {
    const alerts = await alertService.getUnsolvedAlerts()
    if (!Array.isArray(alerts) || alerts.length === 0) {
      pushLocalAssistantMessage('告警AI分析', '当前没有未处理告警。')
      return
    }

    const target = alerts[0] as Alert
    const analysis = await getAlertAIAnalysis(target.id)
    const data = analysis as any

    if (!data?.analysis_text) {
      pushLocalAssistantMessage('告警AI分析', data?.message || '告警分析正在生成中，请稍后再次触发。')
      return
    }

    pushLocalAssistantMessage(
      `告警AI分析 - #${target.id}`,
      `${data.analysis_text}\n\n建议: ${data.handling_suggestions || '暂无'}\n可能原因: ${data.potential_causes || '暂无'}`,
    )
  }

  async function runGenerateNoticeApp() {
    const area = await getPreferredArea()
    if (!area) {
      pushLocalAssistantMessage('生成AI公告', '未找到可用区域，无法生成公告。')
      return
    }

    const notice = await generateAreaNotice(area.id, 'status')
    pushLocalAssistantMessage(`AI公告 - ${notice.title}`, notice.content || '无内容')
  }

  async function triggerSidebarApp(appId: SidebarApp['id']) {
    if (isGenerating.value) {
      ElMessage.warning('当前正在生成回复，请稍后再触发应用')
      return
    }

    let session = currentSession.value
    if (!session) {
      session = createSession('AI应用会话')
    }

    const sessionId = session.id
    appTriggeredBySession.value[sessionId] = appTriggeredBySession.value[sessionId] || {}

    if (appTriggeredBySession.value[sessionId][appId]) {
      ElMessage.info('当前会话已触发过该应用，避免重复执行')
      return
    }

    appLoadingId.value = appId
    try {
      if (appId === 'area-analysis') {
        await runAreaAnalysisApp()
      } else if (appId === 'usage-pattern') {
        await runUsagePatternApp()
      } else if (appId === 'alert-analysis') {
        await runAlertAnalysisApp()
      } else if (appId === 'generate-notice') {
        await runGenerateNoticeApp()
      }
      appTriggeredBySession.value[sessionId][appId] = true
    } catch (error: any) {
      const msg = error?.response?.data?.error || error?.message || '执行失败'
      ElMessage.error(`应用执行失败: ${msg}`)
      pushLocalAssistantMessage('应用执行失败', String(msg))
    } finally {
      appLoadingId.value = ''
    }
  }

  function sendMessage(text: string) {
    if (!text.trim() || isGenerating.value) return

    let session = currentSession.value
    if (!session) {
      session = createSession(text.slice(0, 20))
      session.title = text.length > 20 ? `${text.slice(0, 20)}...` : text
    } else if (session.messages.length === 0) {
      session.title = text.length > 20 ? `${text.slice(0, 20)}...` : text
    }

    const history = toChatHistory(session.messages)

    const userMsg: AgentMessage = {
      id: uid('msg_user'),
      role: 'user',
      content: text,
      steps: [],
      createdAt: new Date(),
    }

    const assistantMsg: AgentMessage = {
      id: uid('msg_assistant'),
      role: 'assistant',
      content: '',
      steps: [],
      streaming: true,
      createdAt: new Date(),
    }

    session.messages.push(userMsg)
    session.messages.push(assistantMsg)

    finalStartedMap.value[assistantMsg.id] = false
    runtimeStates.value[assistantMsg.id] = { protocolV2: false, finalStarted: false, finished: false }

    isGenerating.value = true
    scrollToBottom()

    abortController = createChatStream(
      text,
      history,
      (data: BackendStreamEvent) => {
        handleBackendEvent(data, assistantMsg.id)
      },
      (error) => {
        const errMessage = error instanceof Error ? error.message : '连接中断'
        handleBackendEvent({ type: 'error', message: `连接异常: ${errMessage}` }, assistantMsg.id)
        ElMessage.error('智能体连接异常，请稍后重试')
      },
      () => {
        const state = runtimeStates.value[assistantMsg.id]
        if (!state || state.finished) return
        markFinished(assistantMsg.id)
      },
      selectedModelType.value,
      session!.id,
    )
  }

  function scrollToBottom() {
    nextTick(() => {
      const el = scrollRef.value
      if (el) {
        el.scrollTop = el.scrollHeight
      }
    })
  }

  async function init() {
    if (sessions.value.length > 0) return

    const serverSessions = await getChatSessions()
    if (Array.isArray(serverSessions) && serverSessions.length > 0) {
      sessions.value = serverSessions.map(mapServerSession)
      currentSessionId.value = sessions.value[0].id
      await ensureSessionMessagesLoaded(sessions.value[0].id)
      return
    }

    createSession()
  }

  return {
    sessions,
    currentSessionId,
    currentSession,
    currentMessages,
    sidebarCollapsed,
    sidebarApps,
    appLoadingId,
    selectedModelType,
    inputText,
    inputRef,
    scrollRef,
    isGenerating,
    showFinalAnswer,
    handleSend,
    sendQuickPrompt,
    selectModel,
    startNewChat,
    switchSession,
    deleteSession,
    triggerSidebarApp,
    scrollToBottom,
    init,
  }
}
