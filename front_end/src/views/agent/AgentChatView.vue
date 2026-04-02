<template>
  <div class="agent-chat">
    <aside class="chat-sidebar" :class="{ 'chat-sidebar--collapsed': sidebarCollapsed }">
      <div class="sidebar-header">
        <div class="sidebar-brand">
          <div class="sidebar-logo">
            <el-icon :size="18" color="#fff"><Monitor /></el-icon>
          </div>
          <span v-if="!sidebarCollapsed" class="sidebar-title">慧感云瞻</span>
        </div>
        <el-button
          v-if="!sidebarCollapsed"
          type="primary"
          :icon="Plus"
          circle
          size="small"
          class="new-chat-btn"
          @click="startNewChat"
        />
      </div>

      <div v-if="!sidebarCollapsed" class="sidebar-sessions">
        <div
          v-for="session in sessions"
          :key="session.id"
          class="session-item"
          :class="{ 'session-item--active': currentSessionId === session.id }"
          @click="switchSession(session.id)"
        >
          <el-icon :size="14"><ChatDotRound /></el-icon>
          <span class="session-title">{{ session.title }}</span>
          <el-icon class="session-delete" :size="14" @click.stop="deleteSession(session.id)">
            <Delete />
          </el-icon>
        </div>
      </div>

      <div v-if="!sidebarCollapsed" class="sidebar-apps">
        <div class="sidebar-apps-title">AI分析</div>
        <div
          v-for="app in sidebarApps"
          :key="app.id"
          class="sidebar-app-item"
          :class="{ 'sidebar-app-item--loading': appLoadingId === app.id }"
          @click="triggerSidebarApp(app.id)"
        >
          <span class="app-item-main">
            <el-icon :size="14"><component :is="getAppIcon(app.id)" /></el-icon>
            <span class="app-item-name">{{ app.name }}</span>
          </span>
          <el-icon v-if="appLoadingId === app.id" class="app-item-loading" :size="14"><Loading /></el-icon>
        </div>
      </div>

      <div v-if="!sidebarCollapsed" class="sidebar-footer">
        <div class="sidebar-tips">
          <el-icon :size="12"><InfoFilled /></el-icon>
          <span>ReAct 流式推理与工具调用</span>
        </div>
      </div>
    </aside>

    <main class="chat-main">
      <header class="chat-header">
        <el-button
          :icon="sidebarCollapsed ? Expand : Fold"
          text
          size="small"
          @click="sidebarCollapsed = !sidebarCollapsed"
        />
        <span class="chat-header-title">{{ currentSession?.title || '新对话' }}</span>
        <div class="chat-header-right">
          <el-tag size="small" type="success" effect="plain" round>
            <div class="agent-status-tag">
              <el-icon :size="12" class="agent-status-icon"><CircleCheck /></el-icon>
              <span>智能体在线</span>
            </div>
          </el-tag>
        </div>
      </header>

      <div ref="scrollRef" class="chat-messages">
        <div v-if="currentMessages.length === 0" class="welcome-screen">
          <div class="welcome-icon">
            <div class="welcome-icon-ring"></div>
            <el-icon :size="48" color="#409eff"><Monitor /></el-icon>
          </div>
          <h2 class="welcome-title">慧感云瞻智能助手</h2>
          <p class="welcome-desc">基于校园实时数据与 ReAct 框架，支持工具调用、逐步推理与流式回复</p>

          <div class="quick-prompts">
            <div class="quick-prompt" @click="sendQuickPrompt('推荐3个当前人少的自习区域')">
              <el-icon :size="18" color="#409eff"><OfficeBuilding /></el-icon>
              <div class="quick-prompt-text">
                <strong>推荐空闲区域</strong>
                <span>按人流与容量推荐可用地点</span>
              </div>
            </div>
            <div class="quick-prompt" @click="sendQuickPrompt('查询正心11最近24小时人流趋势')">
              <el-icon :size="18" color="#67c23a"><DataLine /></el-icon>
              <div class="quick-prompt-text">
                <strong>趋势分析</strong>
                <span>查看区域历史变化与极值</span>
              </div>
            </div>
            <div class="quick-prompt" @click="sendQuickPrompt('查询终端2当前运行状态')">
              <el-icon :size="18" color="#e6a23c"><SetUp /></el-icon>
              <div class="quick-prompt-text">
                <strong>终端状态诊断</strong>
                <span>查看 CPU、内存和模型状态</span>
              </div>
            </div>
            <div class="quick-prompt" @click="sendQuickPrompt('给我图书馆相关服务入口')">
              <el-icon :size="18" color="#909399"><Link /></el-icon>
              <div class="quick-prompt-text">
                <strong>资源导航</strong>
                <span>检索校内服务与链接</span>
              </div>
            </div>
          </div>
        </div>

        <div v-for="turn in messageTurns" :key="turn.id" class="message-turn">
          <div v-if="turn.user" class="message message--user">
            <div class="message-user">
              <div class="message-user-bubble">{{ turn.user.content }}</div>
              <div class="message-avatar message-avatar--user">
                <el-icon :size="16"><User /></el-icon>
              </div>
            </div>
          </div>

          <div v-if="turn.assistant" class="message message--assistant">
            <div class="message-assistant">
              <div class="message-avatar message-avatar--bot">
                <el-icon :size="16" color="#fff"><Monitor /></el-icon>
              </div>
              <div class="message-assistant-body">
                <ReActSteps
                  v-if="turn.assistant.steps.length > 0"
                  :steps="turn.assistant.steps"
                  :final-started="showFinalAnswer(turn.assistant)"
                />
                <div
                  v-if="showFinalAnswer(turn.assistant)"
                  class="message-assistant-content"
                  :class="{ 'message-assistant-content--streaming': turn.assistant.streaming }"
                >
                  <MarkdownRender :content="turn.assistant.content" />
                  <span v-if="turn.assistant.streaming && turn.assistant.content" class="streaming-breath">
                    <span></span>
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="chat-input-area">
        <div class="chat-input-wrapper">
          <el-input
            ref="inputRef"
            v-model="inputText"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 5 }"
            placeholder="输入你的问题，例如：帮我分析正心11当前状态"
            resize="none"
            class="chat-input"
            :disabled="isGenerating"
            @keydown.enter.exact.prevent="handleSend"
          />
          <el-button
            type="primary"
            :icon="Promotion"
            circle
            class="send-btn"
            :disabled="!inputText.trim() || isGenerating"
            :loading="isGenerating"
            @click="handleSend"
          />
        </div>
        <div class="model-hint-row">
          <div class="model-switcher">
            <button
              class="model-chip"
              :class="{ active: selectedModelType === 'analysis' }"
              :disabled="isGenerating"
              @click="selectModel('analysis')"
            >分析</button>
            <button
              class="model-chip"
              :class="{ active: selectedModelType === 'fast' }"
              :disabled="isGenerating"
              @click="selectModel('fast')"
            >快速</button>
            <button
              class="model-chip"
              :class="{ active: selectedModelType === 'reasoning' }"
              :disabled="isGenerating"
              @click="selectModel('reasoning')"
            >思考</button>
            <button
              class="model-chip"
              :class="{ active: selectedModelType === 'deep_reasoning' }"
              :disabled="isGenerating"
              @click="selectModel('deep_reasoning')"
            >深度推理</button>
          </div>
          <div class="input-hint">按 Enter 发送，Shift + Enter 换行</div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useAgentChat } from '../../composables/useAgentChat'
import ReActSteps from './ReActSteps.vue'
import MarkdownRender from './MarkdownRender.vue'
import {
  Monitor, Plus, ChatDotRound, Delete, Fold, Expand,
  CircleCheck, InfoFilled, Promotion, User,
  OfficeBuilding, DataLine, SetUp, Link,
  DataAnalysis, Bell, Document, Loading,
} from '@element-plus/icons-vue'

const {
  sessions, currentSessionId, currentSession, currentMessages,
  sidebarCollapsed, sidebarApps, appLoadingId,
  selectedModelType,
  inputText, inputRef, scrollRef, isGenerating,
  showFinalAnswer, handleSend, sendQuickPrompt,
  startNewChat, switchSession, deleteSession, triggerSidebarApp,
  selectModel, init,
} = useAgentChat()

function getAppIcon(appId: string) {
  if (appId === 'area-analysis') return DataAnalysis
  if (appId === 'usage-pattern') return DataLine
  if (appId === 'alert-analysis') return Bell
  if (appId === 'generate-notice') return Document
  return Monitor
}

const messageTurns = computed(() => {
  const turns: Array<{
    id: string
    user?: (typeof currentMessages.value)[number]
    assistant?: (typeof currentMessages.value)[number]
  }> = []

  for (const msg of currentMessages.value) {
    if (msg.role === 'user') {
      turns.push({ id: `turn_${msg.id}`, user: msg })
      continue
    }

    const lastTurn = turns[turns.length - 1]
    if (lastTurn && lastTurn.user && !lastTurn.assistant) {
      lastTurn.assistant = msg
    } else {
      turns.push({ id: `turn_${msg.id}`, assistant: msg })
    }
  }

  return turns
})

onMounted(init)
</script>

<style scoped>
.agent-chat {
  display: flex;
  height: calc(100dvh - 72px);
  min-height: 0;
  margin: 0;
  background: #f7f8fa;
  overflow: hidden;
}

.chat-sidebar {
  width: 240px;
  border-right: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
  background: #fff;
  transition: width 0.25s;
  flex-shrink: 0;
}
.chat-sidebar--collapsed {
  width: 0;
  overflow: hidden;
  border-right: none;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 12px;
  border-bottom: 1px solid #ebeef5;
  min-height: 56px;
}
.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  overflow: hidden;
}
.sidebar-logo {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: linear-gradient(135deg, #409eff, #2c6fbb);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.sidebar-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  white-space: nowrap;
}
.new-chat-btn { flex-shrink: 0; }

.sidebar-sessions {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
.session-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
  margin-bottom: 2px;
  font-size: 13px;
  color: #606266;
}
.session-item:hover { background: #ecf5ff; color: #409eff; }
.session-item--active { background: #d9ecff; color: #409eff; font-weight: 500; }
.session-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-delete { opacity: 0; transition: opacity 0.15s; color: #c0c4cc; }
.session-item:hover .session-delete { opacity: 1; }
.session-delete:hover { color: #f56c6c; }

.sidebar-footer {
  padding: 10px 12px;
  border-top: 1px solid #ebeef5;
  height: 37px;
}

.sidebar-apps {
  border-top: 1px solid #eef1f6;
  padding: 10px 8px;
}

.sidebar-apps-title {
  font-size: 12px;
  font-weight: 600;
  color: #8a94a6;
  padding: 0 4px 6px;
}

.sidebar-app-item {
  width: 100%;
  justify-content: space-between;
  display: flex;
  align-items: center;
  gap: 8px;
  height: auto;
  padding: 8px 10px;
  margin-bottom: 4px;
  border-radius: 8px;
  color: #50607c;
  cursor: pointer;
  user-select: none;
}

.sidebar-app-item:hover {
  background: #f3f8ff;
}

.sidebar-app-item--loading {
  opacity: 0.7;
  pointer-events: none;
}

.app-item-main {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
}

.app-item-name {
  color: #344259;
}

.app-item-loading {
  color: #6a86b8;
  animation: spin 0.9s linear infinite;
}

.sidebar-tips {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #c0c4cc;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: #fff;
}
.chat-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-bottom: 1px solid #f0f2f5;
  min-height: 48px;
  flex-shrink: 0;
}
.chat-header-title {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chat-header-right { display: flex; align-items: center; gap: 8px; }
.agent-status-tag { display: inline-flex; align-items: center; white-space: nowrap; line-height: 12px; }
.agent-status-icon { margin-right: 2px; }

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 0 24px 24px;
  scroll-behavior: smooth;
}

.welcome-screen {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100%;
  padding: 40px 20px;
}
.welcome-icon { position: relative; margin-bottom: 20px; }
.welcome-icon-ring {
  position: absolute;
  inset: -12px;
  border-radius: 50%;
  background: linear-gradient(135deg, rgba(64,158,255,0.15), rgba(44,111,187,0.05));
  animation: ring-pulse 3s ease-in-out infinite;
}
.welcome-title { font-size: 24px; font-weight: 700; color: #303133; margin-bottom: 8px; }
.welcome-desc { font-size: 14px; color: #909399; margin-bottom: 36px; text-align: center; }

.quick-prompts {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  max-width: 560px;
  width: 100%;
}
.quick-prompt {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid #ebeef5;
  cursor: pointer;
  transition: all 0.2s;
  background: #fafbfc;
}
.quick-prompt:hover {
  border-color: #409eff;
  box-shadow: 0 2px 12px rgba(64,158,255,0.1);
  transform: translateY(-1px);
}
.quick-prompt-text { display: flex; flex-direction: column; gap: 2px; }
.quick-prompt-text strong { font-size: 13px; color: #303133; font-weight: 600; }
.quick-prompt-text span { font-size: 12px; color: #909399; }

.message-turn {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
}
.message { margin-bottom: 18px; }
.message--assistant { margin-bottom: 0; }

.message-user {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  justify-content: flex-end;
}
.message-user-bubble {
  max-width: 65%;
  padding: 10px 14px;
  background: #409eff;
  color: #fff;
  border-radius: 14px 4px 14px 14px;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}

.message-assistant {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.message-assistant-body { flex: 1; min-width: 0; }

.message-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.message-avatar--user {
  background: #ecf5ff;
  color: #409eff;
  order: 1;
}
.message-avatar--bot {
  background: linear-gradient(135deg, #409eff, #2c6fbb);
}

.message-assistant-content {
  font-size: 14px;
  line-height: 1.7;
  color: #303133;
  padding: 4px 0;
}

.message-assistant-content--streaming :deep(.markdown-render) {
  display: inline;
}
.message-assistant-content--streaming :deep(.markdown-render > *) {
  display: inline;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  font-size: inherit;
  font-weight: inherit;
  line-height: inherit;
}

.streaming-breath {
  display: inline-block;
  margin-left: 2px;
  vertical-align: middle;
  line-height: 1;
}
.streaming-breath span {
  display: inline-block;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #409eff;
  animation: breathe 1.4s ease-in-out infinite;
}

.chat-input-area {
  padding: 12px 24px 12px;
  border-top: 1px solid #f0f2f5;
  flex-shrink: 0;
  background: #fff;
}
.chat-input-wrapper {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid #dcdfe6;
  border-radius: 24px;
  transition: border-color 0.2s, box-shadow 0.2s;
  background: #fafbfc;
}
.chat-input-wrapper:focus-within {
  border-color: #409eff;
  box-shadow: 0 0 0 3px rgba(64,158,255,0.1);
  background: #fff;
}
.chat-input :deep(.el-textarea__inner) {
  margin-left: 10px;
  border: none !important;
  box-shadow: none !important;
  background: transparent !important;
  padding: 0 !important;
  font-size: 14px;
  line-height: 1.6;
  resize: none;
  overflow-y: hidden !important;
}
.chat-input :deep(.el-textarea__inner:focus) {
  border: none !important;
  box-shadow: none !important;
}
.chat-input :deep(.el-textarea__inner::-webkit-scrollbar) {
  width: 0;
  height: 0;
}
.send-btn { flex-shrink: 0; }

.model-hint-row {
  margin-top: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.model-switcher {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.model-chip {
  border: 1px solid #d8e1f0;
  background: #f6f9ff;
  color: #4e5b72;
  border-radius: 999px;
  font-size: 12px;
  line-height: 1;
  padding: 6px 10px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.model-chip:hover {
  border-color: #7ea8e6;
  color: #2f4f7e;
}

.model-chip.active {
  background: #eaf2ff;
  border-color: #4f86d9;
  color: #2358a8;
  font-weight: 600;
}

.model-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.input-hint {
  text-align: right;
  font-size: 11px;
  color: #c0c4cc;
  white-space: nowrap;
}

@keyframes breathe {
  0%, 100% { opacity: 0.25; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.2); }
}
@keyframes ring-pulse {
  0%, 100% { transform: scale(1); opacity: 0.6; }
  50% { transform: scale(1.1); opacity: 0.3; }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@media (max-width: 768px) {
  .agent-chat {
    margin: 0;
    height: calc(100dvh - 64px);
  }
  .chat-sidebar {
    position: absolute;
    z-index: 10;
    height: 100%;
    box-shadow: 2px 0 12px rgba(0,0,0,0.1);
  }
  .chat-sidebar--collapsed { width: 0; }
  .quick-prompts { grid-template-columns: 1fr; }
  .message-user-bubble { max-width: 85%; }
  .model-hint-row {
    align-items: flex-start;
    flex-direction: column;
  }
  .input-hint {
    text-align: left;
    white-space: normal;
  }
}
</style>
