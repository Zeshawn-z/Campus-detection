<template>
  <span class="stream-fade-text" :class="{ 'stream-fade-text--block': block }">
    <template v-if="!streaming">{{ text }}</template>
    <template v-else>
      <span>{{ settledText }}</span>
      <span
        v-for="seg in enteringSegments"
        :key="seg.id"
        class="stream-fade-text__seg"
        :class="{ 'is-entered': seg.entered }"
      >{{ seg.text }}</span>
    </template>
  </span>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'

interface Segment {
  id: number
  text: string
  entered: boolean
}

const props = withDefaults(defineProps<{
  text: string
  streaming?: boolean
  block?: boolean
  pieceSize?: number
  pieceDelay?: number
}>(), {
  streaming: false,
  block: false,
  pieceSize: 2,
  pieceDelay: 18,
})

const settledText = ref('')
const enteringSegments = ref<Segment[]>([])

let idSeq = 0
let previousText = ''
let queue: string[] = []
let queueTimer: ReturnType<typeof setTimeout> | null = null

function clearQueueTimer() {
  if (queueTimer) {
    clearTimeout(queueTimer)
    queueTimer = null
  }
}

function clearState(text = '') {
  clearQueueTimer()
  queue = []
  enteringSegments.value = []
  settledText.value = text
  previousText = text
}

function flushOldSegments() {
  if (enteringSegments.value.length < 60) return
  const stable = enteringSegments.value.filter(seg => seg.entered)
  if (stable.length === 0) return
  settledText.value += stable.map(seg => seg.text).join('')
  enteringSegments.value = enteringSegments.value.filter(seg => !seg.entered)
}

function pushSegment(text: string) {
  if (!text) return
  const seg: Segment = {
    id: ++idSeq,
    text,
    entered: false,
  }
  enteringSegments.value.push(seg)

  requestAnimationFrame(() => {
    const target = enteringSegments.value.find(item => item.id === seg.id)
    if (target) {
      target.entered = true
    }
    flushOldSegments()
  })
}

function splitPieces(delta: string): string[] {
  const result: string[] = []
  const size = Math.max(1, props.pieceSize)
  for (let i = 0; i < delta.length; i += size) {
    result.push(delta.slice(i, i + size))
  }
  return result
}

function pumpQueue() {
  if (queue.length === 0) {
    queueTimer = null
    return
  }

  const piece = queue.shift() || ''
  pushSegment(piece)
  queueTimer = setTimeout(() => {
    pumpQueue()
  }, Math.max(8, props.pieceDelay))
}

function enqueueDelta(delta: string) {
  if (!delta) return
  queue.push(...splitPieces(delta))
  if (!queueTimer) {
    pumpQueue()
  }
}

watch(
  () => props.text,
  (next) => {
    const nextText = next || ''

    if (!props.streaming) {
      clearState(nextText)
      return
    }

    if (nextText.startsWith(previousText)) {
      const delta = nextText.slice(previousText.length)
      previousText = nextText
      enqueueDelta(delta)
      return
    }

    clearState(nextText)
  },
  { immediate: true },
)

watch(
  () => props.streaming,
  (streaming) => {
    if (!streaming) {
      clearState(props.text || '')
    }
  },
)

onBeforeUnmount(() => {
  clearQueueTimer()
})
</script>

<style scoped>
.stream-fade-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.stream-fade-text--block {
  display: block;
}

.stream-fade-text__seg {
  display: inline;
  opacity: 0;
  transform: translateY(2px);
  transition: opacity 0.22s ease-out, transform 0.22s ease-out;
}

.stream-fade-text__seg.is-entered {
  opacity: 1;
  transform: translateY(0);
}

@media (prefers-reduced-motion: reduce) {
  .stream-fade-text__seg {
    transition: none;
    opacity: 1;
    transform: none;
  }
}
</style>