<template>
  <div ref="rootRef" class="markdown-render" v-html="rendered"></div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = defineProps<{
  content: string
  streaming?: boolean
}>()

const rootRef = ref<HTMLElement | null>(null)
let previousLength = 0

function cleanupResidualFades() {
  const root = rootRef.value
  if (!root) return
  const spans = root.querySelectorAll('span.md-chunk-fade')
  for (const span of spans) {
    const parent = span.parentNode
    if (!parent) continue
    parent.replaceChild(document.createTextNode(span.textContent || ''), span)
    parent.normalize()
  }
}

function findLastTextNode(root: HTMLElement): Text | null {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let last: Text | null = null
  let current = walker.nextNode() as Text | null
  while (current) {
    if ((current.textContent || '').trim().length > 0) {
      last = current
    }
    current = walker.nextNode() as Text | null
  }
  return last
}

function animateDeltaTail(deltaLength: number) {
  const root = rootRef.value
  if (!root || deltaLength <= 0) return

  cleanupResidualFades()

  const lastText = findLastTextNode(root)
  if (!lastText) return

  const full = lastText.textContent || ''
  if (!full) return

  const take = Math.min(Math.max(1, deltaLength), Math.max(1, full.length), 42)
  const splitAt = full.length - take
  if (splitAt < 0) return

  const head = full.slice(0, splitAt)
  const tail = full.slice(splitAt)
  const parent = lastText.parentNode
  if (!parent) return

  lastText.textContent = head

  const fadeSpan = document.createElement('span')
  fadeSpan.className = 'md-chunk-fade'
  fadeSpan.textContent = tail
  parent.insertBefore(fadeSpan, lastText.nextSibling)

  requestAnimationFrame(() => {
    fadeSpan.classList.add('is-entered')
  })

  const finish = () => {
    const host = fadeSpan.parentNode
    if (!host) return
    host.replaceChild(document.createTextNode(tail), fadeSpan)
    host.normalize()
  }

  fadeSpan.addEventListener('transitionend', finish, { once: true })
}

watch(
  () => props.content,
  async (next, prev) => {
    const nextText = next || ''
    const prevText = prev || ''

    if (!props.streaming) {
      previousLength = nextText.length
      return
    }

    const deltaLen = nextText.startsWith(prevText)
      ? nextText.length - prevText.length
      : Math.max(1, nextText.length - previousLength)

    previousLength = nextText.length
    await nextTick()
    animateDeltaTail(deltaLen)
  },
  { flush: 'post' },
)

watch(
  () => props.streaming,
  (active) => {
    if (!active) {
      cleanupResidualFades()
      previousLength = (props.content || '').length
    }
  },
)

onBeforeUnmount(() => {
  cleanupResidualFades()
})

const rendered = computed(() => {
  const source = props.content ?? ''
  try {
    const raw = marked.parse(source) as string
    return DOMPurify.sanitize(raw)
  } catch {
    return escapeHtml(source).replace(/\n/g, '<br>')
  }
})

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}
</script>

<style scoped>
.markdown-render {
  line-height: 1.75;
  word-break: break-word;
}

.markdown-render :deep(.md-chunk-fade) {
  opacity: 0;
  transform: translateY(2px);
  transition: opacity 0.24s ease-out, transform 0.24s ease-out;
}

.markdown-render :deep(.md-chunk-fade.is-entered) {
  opacity: 1;
  transform: translateY(0);
}

.markdown-render :deep(p) {
  margin: 6px 0;
}

.markdown-render :deep(h2) {
  font-size: 18px;
  font-weight: 700;
  margin: 16px 0 8px;
  color: #303133;
  padding-bottom: 6px;
  border-bottom: 1px solid #ebeef5;
}

.markdown-render :deep(h3) {
  font-size: 15px;
  font-weight: 600;
  margin: 12px 0 6px;
  color: #303133;
}

.markdown-render :deep(strong) {
  color: #303133;
  font-weight: 600;
}

.markdown-render :deep(ul),
.markdown-render :deep(ol) {
  margin: 6px 0;
  padding-left: 20px;
}

.markdown-render :deep(li) {
  margin: 3px 0;
}

.markdown-render :deep(blockquote) {
  margin: 8px 0;
  padding: 8px 12px;
  border-left: 3px solid #409eff;
  background: #f4f7ff;
  border-radius: 0 6px 6px 0;
  color: #606266;
  font-size: 13px;
}

.markdown-render :deep(code) {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
  padding: 1px 6px;
  background: #f0f2f5;
  border-radius: 4px;
  color: #e6a23c;
}

.markdown-render :deep(pre) {
  margin: 10px 0;
  padding: 12px;
  background: #1e1e2e;
  border-radius: 8px;
  overflow-x: auto;
}

.markdown-render :deep(pre code) {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 13px;
  line-height: 1.6;
  color: #cdd6f4;
  white-space: pre;
  padding: 0;
  background: transparent;
  border-radius: 0;
}

.markdown-render :deep(table) {
  margin: 10px 0;
  display: block;
  overflow-x: auto;
  border-radius: 8px;
  border: 1px solid #ebeef5;
  border-collapse: collapse;
  font-size: 13px;
}

.markdown-render :deep(th) {
  background: #f5f7fa;
  font-weight: 600;
  text-align: left;
  padding: 8px 12px;
  border-bottom: 2px solid #ebeef5;
  color: #303133;
}

.markdown-render :deep(td) {
  padding: 7px 12px;
  border-bottom: 1px solid #f0f2f5;
  color: #606266;
}

.markdown-render :deep(tbody tr:hover) {
  background: #fafafa;
}
</style>
