<template>
  <div class="react-steps">
    <div
      v-for="step in steps"
      :key="step.id"
      class="react-step"
      :class="[`react-step--${step.type}`]"
    >
      <div class="react-step__row" @click="toggleCollapse(step.id)">
        <svg
          class="react-step__chevron"
          :class="{ 'is-expanded': !isCollapsed(step.id) }"
          viewBox="0 0 16 16"
          width="14"
          height="14"
          fill="none"
        >
          <path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>

        <span class="react-step__tag" :class="`react-step__tag--${step.type}`">
          {{ stepTag(step.type) }}
        </span>

        <code v-if="step.type === 'tool_call'" class="react-step__tool-name">
          {{ step.toolCall?.name || 'unknown' }}
        </code>

        <span v-if="step.type === 'tool_call' && step.toolCall" class="react-step__status">
          <span v-if="step.toolCall.status === 'calling'" class="status-calling">
            <span class="dot-dot"></span><span class="dot-dot"></span><span class="dot-dot"></span>
          </span>
          <span v-else-if="step.toolCall.status === 'success'" class="status-success">
            <el-icon :size="12"><CircleCheck /></el-icon>
          </span>
          <span v-else-if="step.toolCall.status === 'error'" class="status-error">x</span>
        </span>

      </div>

      <div class="react-step__collapse" :data-open="!isCollapsed(step.id)">
        <div class="react-step__collapse-inner">
          <div v-if="step.toolCall?.args && Object.keys(step.toolCall.args).length > 0" class="react-step__params">
            <code v-for="(val, key) in step.toolCall.args" :key="key" class="react-step__param-tag">
              {{ key }}: {{ JSON.stringify(val) }}
            </code>
          </div>

          <div class="react-step__content">
            <template v-if="isProgressivePlanStep(step)">
              <div
                v-if="getStepProgressiveLeading(step)"
                class="json-leading"
                v-html="renderText(getStepProgressiveLeading(step))"
              ></div>

              <div class="json-plan">
                <div v-if="getStepPlanReasoning(step)" class="json-line" :class="{ 'json-line--optimistic': isStepPlanReasoningOptimistic(step) }">
                  <span class="json-key">思考</span>
                  <span class="json-val">
                    <StreamFadeText :text="getStepPlanReasoning(step)" :streaming="step.streaming" />
                  </span>
                </div>

                <div v-if="getStepPlanAction(step)" class="json-line" :class="{ 'json-line--optimistic': isStepPlanActionOptimistic(step) }">
                  <span class="json-key">行动</span>
                  <span class="json-val">
                    <StreamFadeText :text="getStepPlanAction(step)" :streaming="step.streaming" />
                  </span>
                </div>

                <div
                  v-if="getStepPlanOutline(step).length"
                  class="json-list-block"
                >
                  <div class="json-key">回答大纲</div>
                  <ul class="json-list">
                    <li
                      v-for="(item, idx) in getStepPlanOutline(step)"
                      :key="`outline_p_${idx}`"
                      :class="{ 'json-item--optimistic': isStepPlanOutlineOptimistic(step) }"
                    >
                      <StreamFadeText :text="item" :streaming="step.streaming" />
                    </li>
                  </ul>
                </div>

                <div
                  v-if="getStepPlanToolCalls(step).length"
                  class="json-list-block"
                >
                  <div class="json-key">计划调用工具</div>
                  <ul class="json-list">
                    <li
                      v-for="(call, idx) in getStepPlanToolCalls(step)"
                      :key="`tool_call_p_${idx}`"
                      class="json-tool-item"
                      :class="{ 'json-item--optimistic': isStepPlanToolCallsOptimistic(step) }"
                    >
                      <div class="json-line">
                        <span class="json-key">工具</span>
                        <span class="json-val">
                          <StreamFadeText :text="String(call?.tool || call?.name || 'unknown')" :streaming="step.streaming" />
                        </span>
                      </div>
                      <div v-if="call?.reasoning" class="json-line">
                        <span class="json-key">原因</span>
                        <span class="json-val">
                          <StreamFadeText :text="String(call.reasoning || '')" :streaming="step.streaming" />
                        </span>
                      </div>
                      <div v-if="call?.parameters" class="json-line json-line-block">
                        <span class="json-key">参数</span>
                        <pre class="json-pre">{{ JSON.stringify(call.parameters, null, 2) }}</pre>
                      </div>
                    </li>
                  </ul>
                </div>
              </div>

            </template>

            <template v-else-if="isJsonStep(step)">
              <div
                v-if="getStepParsedLeading(step)"
                class="json-leading"
                v-html="renderText(getStepParsedLeading(step))"
              ></div>

              <div v-if="isPlanData(getStepParsedData(step))" class="json-plan">
                <div v-if="(getStepParsedData(step) as any)?.reasoning" class="json-line">
                  <span class="json-key">思考</span>
                  <span class="json-val">
                    <StreamFadeText :text="String((getStepParsedData(step) as any)?.reasoning || '')" :streaming="step.streaming" />
                  </span>
                </div>

                <div v-if="(getStepParsedData(step) as any)?.action" class="json-line">
                  <span class="json-key">行动</span>
                  <span class="json-val">
                    <StreamFadeText :text="String((getStepParsedData(step) as any)?.action || '')" :streaming="step.streaming" />
                  </span>
                </div>

                <div
                  v-if="getStepParsedOutline(step).length"
                  class="json-list-block"
                >
                  <div class="json-key">回答大纲</div>
                  <ul class="json-list">
                    <li v-for="(item, idx) in getStepParsedOutline(step)" :key="`outline_${idx}`">
                      <StreamFadeText :text="item" :streaming="step.streaming" />
                    </li>
                  </ul>
                </div>

                <div
                  v-if="getStepParsedToolCalls(step).length"
                  class="json-list-block"
                >
                  <div class="json-key">计划调用工具</div>
                  <ul class="json-list">
                    <li
                      v-for="(call, idx) in getStepParsedToolCalls(step)"
                      :key="`tool_call_${idx}`"
                      class="json-tool-item"
                    >
                      <div class="json-line">
                        <span class="json-key">工具</span>
                        <span class="json-val">
                          <StreamFadeText :text="String(call?.tool || call?.name || 'unknown')" :streaming="step.streaming" />
                        </span>
                      </div>
                      <div v-if="call?.reasoning" class="json-line">
                        <span class="json-key">原因</span>
                        <span class="json-val">
                          <StreamFadeText :text="String(call.reasoning || '')" :streaming="step.streaming" />
                        </span>
                      </div>
                      <div v-if="call?.parameters" class="json-line json-line-block">
                        <span class="json-key">参数</span>
                        <pre class="json-pre">{{ JSON.stringify(call.parameters, null, 2) }}</pre>
                      </div>
                    </li>
                  </ul>
                </div>
              </div>

              <div v-else-if="getStepParsedArray(step)" class="json-array">
                <div
                  v-for="(item, idx) in getStepParsedArray(step)"
                  :key="`arr_${idx}`"
                  class="json-card"
                >
                  <template v-if="isRecord(item)">
                    <div v-for="(val, key) in item" :key="`kv_${idx}_${String(key)}`" class="json-line">
                      <span class="json-key">{{ String(key) }}</span>
                      <span class="json-val">{{ formatValue(val) }}</span>
                    </div>
                  </template>
                  <template v-else>
                    <span class="json-val">
                      <StreamFadeText :text="formatValue(item)" :streaming="step.streaming" />
                    </span>
                  </template>
                </div>
              </div>

              <div v-else-if="getStepParsedObject(step)" class="json-object">
                <div
                  v-for="(val, key) in (getStepParsedObject(step) || {})"
                  :key="`obj_${String(key)}`"
                  class="json-line"
                >
                  <span class="json-key">{{ String(key) }}</span>
                  <span class="json-val">
                    <StreamFadeText :text="formatValue(val)" :streaming="step.streaming" />
                  </span>
                </div>
              </div>

              <div v-else class="json-line">
                <span class="json-val">
                  <StreamFadeText :text="formatValue(getStepParsedData(step))" :streaming="step.streaming" />
                </span>
              </div>
            </template>

            <template v-else>
              <StreamFadeText :text="step.content" :streaming="step.streaming" />
            </template>
          </div>

          <div v-if="step.type === 'tool_call' && step.toolCall?.status === 'calling' && !step.streaming" class="react-step__loading">
            <span class="breathing-dots">
              <span></span><span></span><span></span>
            </span>
            <span>等待工具返回</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { CircleCheck } from '@element-plus/icons-vue'
import type { ReActStep } from '../../types/agent-chat'
import { createStepJsonParser } from './stepJsonParser'
import StreamFadeText from './StreamFadeText.vue'

const props = defineProps<{
  steps: ReActStep[]
  finalStarted?: boolean
}>()

const collapsedIds = ref<Set<string>>(new Set())
const knownStepIds = ref<Set<string>>(new Set())
const manuallyExpandedIds = ref<Set<string>>(new Set())
const previousStepIds = ref<string[]>([])

watch(
  () => props.steps.map(step => `${step.id}:${step.streaming ? '1' : '0'}`).join('|'),
  () => {
    const currentStepIds = props.steps.map(step => step.id)
    const currentIdSet = new Set(currentStepIds)

    if (currentStepIds.length === 0) {
      collapsedIds.value = new Set()
      knownStepIds.value = new Set()
      manuallyExpandedIds.value = new Set()
      previousStepIds.value = []
      return
    }

    const prevStepIds = previousStepIds.value
    const newlyAddedIds = currentStepIds.filter(id => !prevStepIds.includes(id))

    collapsedIds.value = new Set([...collapsedIds.value].filter(id => currentIdSet.has(id)))
    knownStepIds.value = new Set([...knownStepIds.value].filter(id => currentIdSet.has(id)))
    manuallyExpandedIds.value = new Set([...manuallyExpandedIds.value].filter(id => currentIdSet.has(id)))

    for (const stepId of newlyAddedIds) {
      const stepIndex = currentStepIds.indexOf(stepId)
      const step = props.steps[stepIndex]

      knownStepIds.value.add(stepId)
      collapsedIds.value.add(stepId)
      if (step?.streaming) {
        collapsedIds.value.delete(stepId)
      }

      const previousStepId = stepIndex > 0 ? currentStepIds[stepIndex - 1] : null
      if (previousStepId && !manuallyExpandedIds.value.has(previousStepId)) {
        collapsedIds.value.add(previousStepId)
      }
    }

    for (const stepId of currentStepIds) {
      if (!knownStepIds.value.has(stepId)) {
        knownStepIds.value.add(stepId)
        collapsedIds.value.add(stepId)
      }
    }

    previousStepIds.value = currentStepIds
    collapsedIds.value = new Set(collapsedIds.value)
  },
  { immediate: true },
)

watch(
  () => !!props.finalStarted,
  (started, prevStarted) => {
    if (!started || prevStarted) return

    const lastStepId = props.steps[props.steps.length - 1]?.id
    if (!lastStepId) return

    collapsedIds.value.add(lastStepId)
    collapsedIds.value = new Set(collapsedIds.value)
  },
  { immediate: true },
)

function toggleCollapse(id: string) {
  if (collapsedIds.value.has(id)) {
    collapsedIds.value.delete(id)
    manuallyExpandedIds.value.add(id)
  } else {
    collapsedIds.value.add(id)
    manuallyExpandedIds.value.delete(id)
  }
  collapsedIds.value = new Set(collapsedIds.value)
}

function isCollapsed(id: string): boolean {
  return collapsedIds.value.has(id)
}

function stepTag(type: string): string {
  const map: Record<string, string> = {
    thought: '思考',
    tool_call: '调用工具',
    tool_result: '观察结果',
    action: '执行',
    final_answer: '回答',
  }
  return map[type] || type
}

function renderText(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>')
}

const stepParser = createStepJsonParser()

function getStepRenderState(step: ReActStep) {
  return stepParser.getStepRenderState(step)
}

function isProgressivePlanStep(step: ReActStep): boolean {
  return getStepRenderState(step).mode === 'progressive'
}

function isJsonStep(step: ReActStep): boolean {
  return getStepRenderState(step).mode === 'json'
}

function getStepProgressive(step: ReActStep) {
  const state = getStepRenderState(step)
  return state.mode === 'progressive' ? state.progressive || null : null
}

function getStepProgressiveLeading(step: ReActStep): string {
  return getStepProgressive(step)?.leading || ''
}

function getStepPlanReasoning(step: ReActStep): string {
  return stepParser.getPlanTextField(getStepProgressive(step), 'reasoning')
}

function getStepPlanAction(step: ReActStep): string {
  return stepParser.getPlanTextField(getStepProgressive(step), 'action')
}

function getStepPlanOutline(step: ReActStep): string[] {
  return stepParser.getPlanOutline(getStepProgressive(step))
}

function getStepPlanToolCalls(step: ReActStep): Array<Record<string, any>> {
  return stepParser.getPlanToolCalls(getStepProgressive(step))
}

function isStepPlanReasoningOptimistic(step: ReActStep): boolean {
  return stepParser.isOptimisticField(getStepProgressive(step), 'reasoning')
}

function isStepPlanActionOptimistic(step: ReActStep): boolean {
  return stepParser.isOptimisticField(getStepProgressive(step), 'action')
}

function isStepPlanOutlineOptimistic(step: ReActStep): boolean {
  return stepParser.isOptimisticField(getStepProgressive(step), 'outline')
}

function isStepPlanToolCallsOptimistic(step: ReActStep): boolean {
  return stepParser.isOptimisticField(getStepProgressive(step), 'tool_calls')
}

function getStepParsed(step: ReActStep) {
  const state = getStepRenderState(step)
  return state.mode === 'json' ? state.parsed || null : null
}

function getStepParsedLeading(step: ReActStep): string {
  return getStepParsed(step)?.leading || ''
}

function getStepParsedData(step: ReActStep): unknown {
  return getStepParsed(step)?.data
}

function getStepParsedOutline(step: ReActStep): string[] {
  const data = getStepParsedData(step) as Record<string, unknown> | undefined
  const outline = data?.outline
  if (!Array.isArray(outline)) return []
  return outline.map(item => String(item ?? ''))
}

function getStepParsedToolCalls(step: ReActStep): Array<Record<string, any>> {
  const data = getStepParsedData(step) as Record<string, unknown> | undefined
  const calls = data?.tool_calls
  if (!Array.isArray(calls)) return []
  return calls.filter(item => !!item && typeof item === 'object') as Array<Record<string, any>>
}

function getStepParsedArray(step: ReActStep): unknown[] | null {
  const data = getStepParsedData(step)
  return Array.isArray(data) ? data : null
}

function getStepParsedObject(step: ReActStep): Record<string, unknown> | null {
  const data = getStepParsedData(step)
  return isRecord(data) ? data : null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function isPlanData(value: unknown): boolean {
  if (!isRecord(value)) return false
  return (
    'reasoning' in value ||
    'action' in value ||
    'tool_calls' in value ||
    'outline' in value
  )
}

function formatValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (value === null || typeof value === 'undefined') return ''
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}
</script>

<style scoped>
.react-steps {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.react-step__row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}

.react-step__row:hover {
  background: rgba(0, 0, 0, 0.02);
}

.react-step__chevron {
  color: #b0b3b8;
  transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  flex-shrink: 0;
}

.react-step__chevron.is-expanded {
  transform: rotate(90deg);
}

.react-step__tag {
  font-size: 12px;
  font-weight: 500;
  border-radius: 4px;
  padding: 1px 7px;
  flex-shrink: 0;
}

.react-step__tag--thought {
  background: rgba(124, 77, 255, 0.08);
  color: #7c4dff;
}

.react-step__tag--tool_call {
  background: rgba(255, 109, 0, 0.08);
  color: #e65100;
}

.react-step__tag--tool_result {
  background: rgba(0, 188, 212, 0.08);
  color: #00838f;
}

.react-step__tag--action {
  background: rgba(76, 175, 80, 0.08);
  color: #2e7d32;
}

.react-step__tag--final_answer {
  background: rgba(33, 150, 243, 0.08);
  color: #1565c0;
}

.react-step__tool-name {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 11px;
  color: #909399;
}

.react-step__status {
  display: flex;
  align-items: center;
  margin-left: 2px;
}

.status-calling {
  display: flex;
  gap: 2px;
}

.status-calling .dot-dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #ff9800;
  animation: dot-bounce 1.2s ease-in-out infinite;
}

.status-calling .dot-dot:nth-child(2) { animation-delay: 0.15s; }
.status-calling .dot-dot:nth-child(3) { animation-delay: 0.3s; }

.status-success {
  display: inline-flex;
  align-items: center;
  color: #43a047;
}

.status-error {
  color: #e53935;
  font-size: 12px;
  font-weight: 600;
}

.breathing-dots {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: 4px;
}

.breathing-dots span {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #409eff;
  animation: breathe 1.4s ease-in-out infinite;
}

.breathing-dots span:nth-child(2) { animation-delay: 0.2s; }
.breathing-dots span:nth-child(3) { animation-delay: 0.4s; }

.react-step__collapse {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.react-step__collapse[data-open="true"] {
  grid-template-rows: 1fr;
}

.react-step__collapse-inner {
  overflow: hidden;
  min-height: 0;
}

.react-step__params {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  padding: 6px 0 4px 32px;
}

.react-step__param-tag {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 4px;
  background: #f5f5f7;
  color: #909399;
}

.react-step__content {
  padding: 4px 0 8px 32px;
  font-size: 13px;
  line-height: 1.75;
  color: #a8a8b0;
  white-space: pre-wrap;
  word-break: break-word;
}

.react-step__content-fade {
  display: block;
}

.react-step__content :deep(strong) {
  color: #b8b8c0;
  font-weight: 600;
}

.react-step__content :deep(code) {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 11px;
  padding: 1px 5px;
  background: #f5f5f7;
  border-radius: 3px;
  color: #909399;
}

.json-leading {
  margin-bottom: 6px;
}

.json-plan,
.json-array,
.json-object {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.json-card {
  border: 1px solid #eceff5;
  background: #fafbfe;
  border-radius: 6px;
  padding: 6px 8px;
}

.json-line {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.json-line--optimistic .json-val {
  color: #6f7d95;
  font-style: italic;
}

.json-item--optimistic {
  color: #6f7d95;
}

.json-line-block {
  flex-direction: column;
  gap: 4px;
}

.json-key {
  min-width: 56px;
  color: #6b778c;
  font-weight: 600;
  font-size: 12px;
}

.json-val {
  color: #505d73;
  font-size: 12.5px;
  line-height: 1.7;
  word-break: break-word;
}

.json-list-block {
  margin-top: 2px;
}

.json-list {
  margin: 4px 0 0;
  padding-left: 18px;
  color: #505d73;
}

.json-tool-item {
  margin-bottom: 8px;
}

.json-pre {
  margin: 0;
  padding: 6px 8px;
  background: #f4f6fb;
  border: 1px solid #e7ebf3;
  border-radius: 6px;
  color: #5a6478;
  font-size: 11px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-all;
}

.react-step__loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0 8px 32px;
  font-size: 12px;
  color: #b8b8c0;
}

@keyframes dot-bounce {
  0%, 80%, 100% { transform: scale(0.4); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

@keyframes breathe {
  0%, 100% { opacity: 0.25; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.2); }
}
</style>
