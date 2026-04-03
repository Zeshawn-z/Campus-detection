import type { ReActStep } from '../../types/agent-chat'

export type ParsedJsonPayload = {
  leading: string
  data: any
}

export type PlanToolCallItem = {
  tool?: string
  name?: string
  reasoning?: string
  parameters?: Record<string, unknown> | string
}

export type ProgressivePlanPayload = {
  leading: string
  stable: Record<string, unknown>
  pending: string
  complete: boolean
  optimistic?: {
    key: string
    value: unknown
  }
}

const PLAN_KEYWORDS = ['reasoning', 'action', 'tool_calls', 'outline', 'response']

export function createStepJsonParser() {
  const jsonCache = new Map<string, ParsedJsonPayload | null>()
  const progressivePlanCache = new Map<string, ProgressivePlanPayload | null>()
  const stepRenderCache = new Map<string, {
    content: string
    state: { mode: 'text' | 'progressive' | 'json'; progressive?: ProgressivePlanPayload | null; parsed?: ParsedJsonPayload | null }
  }>()

  function clearIfOversize(map: Map<string, unknown>, maxSize = 500) {
    if (map.size > maxSize) {
      map.clear()
    }
  }

  function tryParseJson(text: string): any | null {
    try {
      return JSON.parse(text)
    } catch {
      return null
    }
  }

  function decodeJsonEscapes(raw: string): string {
    return raw
      .replace(/\\"/g, '"')
      .replace(/\\n/g, '\n')
      .replace(/\\r/g, '\r')
      .replace(/\\t/g, '\t')
      .replace(/\\\\/g, '\\')
  }

  function parseJsonStringToken(source: string, start: number): { complete: boolean; end: number } {
    if (source[start] !== '"') return { complete: false, end: start }

    let escape = false
    for (let i = start + 1; i < source.length; i += 1) {
      const ch = source[i]
      if (escape) {
        escape = false
        continue
      }
      if (ch === '\\') {
        escape = true
        continue
      }
      if (ch === '"') {
        return { complete: true, end: i + 1 }
      }
    }

    return { complete: false, end: source.length }
  }

  function parseJsonBalancedToken(
    source: string,
    start: number,
    openChar: '{' | '[',
  ): { complete: boolean; end: number } {
    const closeChar = openChar === '{' ? '}' : ']'
    let depth = 0
    let inString = false
    let escape = false

    for (let i = start; i < source.length; i += 1) {
      const ch = source[i]

      if (escape) {
        escape = false
        continue
      }

      if (inString) {
        if (ch === '\\') {
          escape = true
        } else if (ch === '"') {
          inString = false
        }
        continue
      }

      if (ch === '"') {
        inString = true
        continue
      }

      if (ch === openChar) {
        depth += 1
        continue
      }

      if (ch === closeChar) {
        depth -= 1
        if (depth === 0) {
          return { complete: true, end: i + 1 }
        }
      }
    }

    return { complete: false, end: source.length }
  }

  function parseJsonValueToken(source: string, start: number): { complete: boolean; end: number } {
    const first = source[start]
    if (!first) return { complete: false, end: source.length }

    if (first === '"') {
      return parseJsonStringToken(source, start)
    }
    if (first === '{') {
      return parseJsonBalancedToken(source, start, '{')
    }
    if (first === '[') {
      return parseJsonBalancedToken(source, start, '[')
    }

    let i = start
    while (i < source.length && source[i] !== ',' && source[i] !== '}') {
      i += 1
    }

    const token = source.slice(start, i).trim()
    if (!token) return { complete: false, end: source.length }

    try {
      JSON.parse(token)
      return { complete: true, end: i }
    } catch {
      return { complete: false, end: source.length }
    }
  }

  function parseOptimisticText(raw: string): string {
    const text = raw.trimStart()
    if (!text) return ''

    if (!text.startsWith('"')) {
      return text.slice(0, 240)
    }

    let out = ''
    let escape = false
    for (let i = 1; i < text.length; i += 1) {
      const ch = text[i]
      if (escape) {
        out += `\\${ch}`
        escape = false
        continue
      }
      if (ch === '\\') {
        escape = true
        continue
      }
      if (ch === '"') {
        break
      }
      out += ch
    }

    return decodeJsonEscapes(out)
  }

  function parseOptimisticOutline(raw: string): string[] {
    const list: string[] = []
    const start = raw.indexOf('[')
    const src = start >= 0 ? raw.slice(start) : raw

    const regex = /"((?:\\.|[^"\\])*)"/g
    let match: RegExpExecArray | null = regex.exec(src)
    while (match) {
      list.push(decodeJsonEscapes(match[1]))
      if (list.length >= 12) break
      match = regex.exec(src)
    }

    return list
  }

  function parseOptimisticToolCalls(raw: string): PlanToolCallItem[] {
    const tools: string[] = []
    const reasons: string[] = []

    const toolRegex = /"tool"\s*:\s*"((?:\\.|[^"\\])*)/g
    let toolMatch: RegExpExecArray | null = toolRegex.exec(raw)
    while (toolMatch) {
      tools.push(decodeJsonEscapes(toolMatch[1]))
      if (tools.length >= 6) break
      toolMatch = toolRegex.exec(raw)
    }

    const reasonRegex = /"reasoning"\s*:\s*"((?:\\.|[^"\\])*)/g
    let reasonMatch: RegExpExecArray | null = reasonRegex.exec(raw)
    while (reasonMatch) {
      reasons.push(decodeJsonEscapes(reasonMatch[1]))
      if (reasons.length >= 6) break
      reasonMatch = reasonRegex.exec(raw)
    }

    const maxLen = Math.max(tools.length, reasons.length)
    const result: PlanToolCallItem[] = []
    for (let i = 0; i < maxLen; i += 1) {
      result.push({ tool: tools[i], reasoning: reasons[i] })
    }
    return result
  }

  function parseOptimisticValue(key: string, raw: string): unknown {
    if (key === 'reasoning' || key === 'action' || key === 'response') {
      return parseOptimisticText(raw)
    }
    if (key === 'outline') {
      return parseOptimisticOutline(raw)
    }
    if (key === 'tool_calls') {
      return parseOptimisticToolCalls(raw)
    }
    return parseOptimisticText(raw)
  }

  function isLikelyPlanPayload(stable: Record<string, unknown>, source: string): boolean {
    if (Object.keys(stable).some(key => PLAN_KEYWORDS.includes(key))) return true
    return /"(reasoning|action|tool_calls|outline|response)"\s*:/.test(source)
  }

  function getProgressivePlan(content: string): ProgressivePlanPayload | null {
    if (!content) return null
    if (progressivePlanCache.has(content)) return progressivePlanCache.get(content) || null

    const braceIdx = content.indexOf('{')
    if (braceIdx < 0) {
      progressivePlanCache.set(content, null)
      return null
    }

    const leading = content.slice(0, braceIdx).trim()
    const source = content.slice(braceIdx)
    if (!source.startsWith('{')) {
      progressivePlanCache.set(content, null)
      return null
    }

    const stable: Record<string, unknown> = {}
    let pending = ''
    let complete = false
    let optimistic: ProgressivePlanPayload['optimistic']
    let i = 1

    while (i < source.length) {
      while (i < source.length && /\s/.test(source[i])) i += 1
      if (i >= source.length) break

      if (source[i] === '}') {
        complete = true
        i += 1
        break
      }

      const fieldStart = i
      if (source[i] !== '"') {
        pending = source.slice(fieldStart)
        break
      }

      const keyToken = parseJsonStringToken(source, i)
      if (!keyToken.complete) {
        pending = source.slice(fieldStart)
        break
      }

      const keyRaw = source.slice(i, keyToken.end)
      let key = ''
      try {
        key = JSON.parse(keyRaw)
      } catch {
        pending = source.slice(fieldStart)
        break
      }

      i = keyToken.end
      while (i < source.length && /\s/.test(source[i])) i += 1
      if (i >= source.length || source[i] !== ':') {
        pending = source.slice(fieldStart)
        break
      }

      i += 1
      while (i < source.length && /\s/.test(source[i])) i += 1
      if (i >= source.length) {
        pending = source.slice(fieldStart)
        break
      }

      const valueStart = i
      const valueToken = parseJsonValueToken(source, i)
      if (!valueToken.complete) {
        const rawValue = source.slice(valueStart)
        optimistic = {
          key,
          value: parseOptimisticValue(key, rawValue),
        }
        pending = source.slice(fieldStart)
        break
      }

      const valueRaw = source.slice(valueStart, valueToken.end).trim()
      try {
        stable[key] = JSON.parse(valueRaw)
      } catch {
        pending = source.slice(fieldStart)
        break
      }

      i = valueToken.end
      while (i < source.length && /\s/.test(source[i])) i += 1

      if (i >= source.length) {
        break
      }
      if (source[i] === ',') {
        i += 1
        continue
      }
      if (source[i] === '}') {
        complete = true
        i += 1
        break
      }

      pending = source.slice(i)
      break
    }

    if (!complete && !pending && i < source.length) {
      pending = source.slice(i)
    }

    if (!isLikelyPlanPayload(stable, source)) {
      progressivePlanCache.set(content, null)
      return null
    }

    const payload: ProgressivePlanPayload = {
      leading,
      stable,
      pending: pending.trimStart(),
      complete,
      optimistic,
    }

    clearIfOversize(progressivePlanCache)
    progressivePlanCache.set(content, payload)
    return payload
  }

  function getParsedJson(content: string): ParsedJsonPayload | null {
    if (!content) return null
    if (jsonCache.has(content)) return jsonCache.get(content) || null

    let parsed: ParsedJsonPayload | null = null
    const trimmed = content.trim()
    if (!trimmed) {
      jsonCache.set(content, null)
      return null
    }

    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      const whole = tryParseJson(trimmed)
      if (whole !== null) {
        parsed = { leading: '', data: whole }
      }
    }

    if (!parsed) {
      const braceIdx = content.indexOf('{')
      const bracketIdx = content.indexOf('[')
      let idx = -1
      if (braceIdx >= 0 && bracketIdx >= 0) idx = Math.min(braceIdx, bracketIdx)
      else idx = Math.max(braceIdx, bracketIdx)

      if (idx >= 0) {
        const leading = content.slice(0, idx).trim()
        const candidate = content.slice(idx).trim()
        const tail = tryParseJson(candidate)
        if (tail !== null) {
          parsed = { leading, data: tail }
        }
      }
    }

    clearIfOversize(jsonCache)
    jsonCache.set(content, parsed)
    return parsed
  }

  function shouldUsePlanParser(step: ReActStep): boolean {
    if (!step.content || step.content.length > 12000) return false
    if (step.type === 'thought') return true
    if (step.sourceType === 'plan' || step.sourceType === 'agent_planning' || step.sourceType === 'planning_progress' || step.sourceType === 'agent_replanning') {
      return true
    }
    return /"(reasoning|action|tool_calls|outline|response)"\s*:/.test(step.content.slice(0, 2000))
  }

  function shouldUseGenericJsonParser(step: ReActStep): boolean {
    if (!step.content || step.content.length > 4000) return false
    if (step.type !== 'thought' && step.type !== 'action') return false
    const trimmed = step.content.trimStart()
    return trimmed.startsWith('{') || trimmed.startsWith('[')
  }

  function getStepRenderState(step: ReActStep): {
    mode: 'text' | 'progressive' | 'json'
    progressive?: ProgressivePlanPayload | null
    parsed?: ParsedJsonPayload | null
  } {
    const cacheKey = step.id
    const cached = stepRenderCache.get(cacheKey)
    if (cached && cached.content === step.content) {
      return cached.state
    }

    let state: { mode: 'text' | 'progressive' | 'json'; progressive?: ProgressivePlanPayload | null; parsed?: ParsedJsonPayload | null } = {
      mode: 'text',
    }

    if (shouldUsePlanParser(step)) {
      const progressive = getProgressivePlan(step.content)
      if (progressive) {
        state = { mode: 'progressive', progressive }
      }
    }

    if (state.mode === 'text' && shouldUseGenericJsonParser(step)) {
      const parsed = getParsedJson(step.content)
      if (parsed) {
        state = { mode: 'json', parsed }
      }
    }

    clearIfOversize(stepRenderCache, 1200)
    stepRenderCache.set(cacheKey, {
      content: step.content,
      state,
    })
    return state
  }

  function getPlanOutline(payload: ProgressivePlanPayload | null | undefined): string[] {
    if (!payload) return []
    const fromStable = payload.stable.outline
    if (Array.isArray(fromStable) && fromStable.length > 0) {
      return fromStable.map(item => String(item ?? ''))
    }

    if (payload.optimistic?.key === 'outline' && Array.isArray(payload.optimistic.value)) {
      return payload.optimistic.value.map(item => String(item ?? ''))
    }

    return []
  }

  function getPlanToolCalls(payload: ProgressivePlanPayload | null | undefined): PlanToolCallItem[] {
    if (!payload) return []
    const fromStable = payload.stable.tool_calls
    if (Array.isArray(fromStable) && fromStable.length > 0) {
      return fromStable.filter(item => !!item && typeof item === 'object') as PlanToolCallItem[]
    }

    if (payload.optimistic?.key === 'tool_calls' && Array.isArray(payload.optimistic.value)) {
      return payload.optimistic.value as PlanToolCallItem[]
    }

    return []
  }

  function getPlanTextField(payload: ProgressivePlanPayload | null | undefined, field: 'reasoning' | 'action'): string {
    if (!payload) return ''
    const stable = payload.stable[field]
    if (typeof stable === 'string' && stable) return stable

    if (payload.optimistic?.key === field && typeof payload.optimistic.value === 'string') {
      return payload.optimistic.value
    }

    return ''
  }

  function isOptimisticField(payload: ProgressivePlanPayload | null | undefined, field: 'reasoning' | 'action' | 'outline' | 'tool_calls'): boolean {
    if (!payload?.optimistic) return false
    return payload.optimistic.key === field
  }

  return {
    getStepRenderState,
    getPlanOutline,
    getPlanToolCalls,
    getPlanTextField,
    isOptimisticField,
  }
}
