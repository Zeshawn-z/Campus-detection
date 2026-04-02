<template>
  <div class="markdown-render" v-html="rendered"></div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = defineProps<{
  content: string
}>()

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
