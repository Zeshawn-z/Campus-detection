<template>
  <div class="info-list-container">
    <div class="tech-corners"></div>
    <div class="section-header">
      <h2>{{ title }}</h2>
      <div class="subtitle">{{ subtitle }}</div>
    </div>
    <div 
      class="list-wrapper" 
      ref="listWrapper"
      @mouseenter="isHovering = true"
      @mouseleave="isHovering = false"
      @wheel="handleWheel"
    >
      <!-- 骨架屏 Loading -->
      <div v-if="loading" class="skeleton-list">
        <div v-for="i in 5" :key="i" class="skeleton-item">
          <div class="skeleton-text w-60"></div>
          <div class="skeleton-text w-30"></div>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-else-if="items.length === 0" class="empty-state">
        暂无数据
      </div>

      <!-- 真实数据列表 -->
      <div 
        v-else
        class="list-content" 
        ref="listContent"
        :style="{ transform: `translateY(-${scrollOffset}px)` }"
      >
        <div 
          v-for="item in visibleItems" 
          :key="item.virtualIndex" 
          class="list-item"
          :class="{ 'active': selectedId !== undefined && selectedId !== null && item.data.id === selectedId }"
          :style="{ height: itemHeight + 'px' }"
          @click="emit('itemClick', item.data)"
          style="cursor: pointer;"
        >
          <slot name="item" :item="item.data"></slot>
        </div>
      </div>
    </div>
  </div>
</template>

<script lang="ts" setup>
import { ref, computed, onMounted, onUnmounted, toRefs, watch, nextTick } from 'vue';

interface ListItem {
  [key: string]: any;
}

const props = defineProps({
  title: {
    type: String,
    required: true,
  },
  subtitle: {
    type: String,
    required: true,
  },
  items: {
    type: Array as () => ListItem[],
    required: true,
  },
  itemHeight: {
    type: Number,
    default: 40, // 默认每项高度
  },
  scrollSpeed: {
    type: Number,
    default: 1, // 滚动速度
  },
  loading: {
    type: Boolean,
    default: false
  },
  selectedId: {
    type: [Number, String],
    default: null
  }
});

const emit = defineEmits(['itemClick']);

const { items, itemHeight, scrollSpeed, loading, selectedId } = toRefs(props);
const listWrapper = ref<HTMLElement | null>(null);
const listContent = ref<HTMLElement | null>(null);

// 交互状态
const isHovering = ref(false);

// 虚拟滚动状态
const scrollPosition = ref(0); // 当前虚拟滚动位置（无限累加）
const wrapperHeight = ref(300);
let animationFrameId: number;

// 缓冲区大小（在可视区域上下各多渲染几个项目）
const bufferSize = 3;

// 计算可见项目数量
const visibleCount = computed(() => {
  return Math.ceil(wrapperHeight.value / itemHeight.value) + bufferSize;
});

// 计算总虚拟高度（用于无限滚动）
const totalVirtualHeight = computed(() => {
  return items.value.length * itemHeight.value;
});

// 计算当前滚动偏移（用于 transform）
const scrollOffset = computed(() => {
  if (items.value.length === 0) return 0;
  // 计算当前在虚拟列表中的相对位置
  const relativePosition = scrollPosition.value % totalVirtualHeight.value;
  const startIndex = Math.floor(relativePosition / itemHeight.value);
  // 返回当前批次内的偏移
  return relativePosition - startIndex * itemHeight.value;
});

// 计算可见项目列表
const visibleItems = computed(() => {
  if (items.value.length === 0) return [];
  const itemCount = items.value.length;

  // 如果数量小于等于4，不需要滚动，直接展示所有数据
  if (itemCount <= 4) {
    return items.value.map((item, index) => ({
      virtualIndex: index,
      data: item
    }));
  }
  
  const result: { virtualIndex: number; data: ListItem }[] = [];
  
  // 计算起始索引（基于无限滚动位置）
  const relativePosition = scrollPosition.value % totalVirtualHeight.value;
  let startIndex = Math.floor(relativePosition / itemHeight.value);
  
  // 生成可见项目
  for (let i = 0; i < visibleCount.value; i++) {
    // 使用模运算实现循环
    const realIndex = (startIndex + i) % itemCount;
    result.push({
      virtualIndex: startIndex + i, // 使用虚拟索引作为 key，确保唯一性
      data: items.value[realIndex],
    });
  }
  
  return result;
});

// 更新容器高度
const updateWrapperHeight = () => {
  if (listWrapper.value) {
    wrapperHeight.value = listWrapper.value.offsetHeight;
  }
};

// 开始滚动动画
const startScrolling = () => {
  if (!listWrapper.value || items.value.length === 0) return;
  
  updateWrapperHeight();
  
  // 如果内容不足以滚动，或者数量小于等于4，则不启动动画
  if (items.value.length <= 4 || totalVirtualHeight.value <= wrapperHeight.value) {
    // 确保滚动位置重置为0，避免在切换数据时残留滚动位置
    scrollPosition.value = 0;
    return;
  }

  const scroll = () => {
    // 只有在鼠标不悬停时才自动滚动
    if (!isHovering.value) {
      scrollPosition.value += scrollSpeed.value;
      
      // 防止数值溢出，当位置过大时重置（保持相对位置不变）
      if (scrollPosition.value > totalVirtualHeight.value * 1000) {
        scrollPosition.value = scrollPosition.value % totalVirtualHeight.value;
      }
    }
    
    animationFrameId = requestAnimationFrame(scroll);
  };

  scroll();
};

// 处理鼠标滚轮事件
const handleWheel = (e: WheelEvent) => {
  if (items.value.length === 0) return;

  // 如果不用滚动，则直接返回，允许默认行为（虽然可能也没滚动条）
  if (items.value.length <= 4 || totalVirtualHeight.value <= wrapperHeight.value) return;
  
  // 阻止默认滚动行为，避免页面滚动
  e.preventDefault();
  
  // 更新滚动位置
  scrollPosition.value += e.deltaY * 0.5; // 添加系数调节滚动灵敏度

  // 处理负数情况（向上滚动）
  if (scrollPosition.value < 0) {
    // 使其变为正数的大值，保持循环效果
    // 找到一个 sufficiently large multiple of totalVirtualHeight
    const multiple = Math.ceil(Math.abs(scrollPosition.value) / totalVirtualHeight.value) + 1;
    scrollPosition.value += multiple * totalVirtualHeight.value;
  }
};

// 停止滚动
const stopScrolling = () => {
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId);
  }
};

// 重新初始化滚动
const reinitScroll = () => {
  stopScrolling();
  scrollPosition.value = 0;
  nextTick(() => {
    updateWrapperHeight();
    startScrolling();
  });
};

// 监听 items 变化
watch(items, () => {
  reinitScroll();
}, { deep: true });

// 窗口大小变化时更新
const handleResize = () => {
  updateWrapperHeight();
};

onMounted(() => {
  window.addEventListener('resize', handleResize);
  nextTick(() => {
    startScrolling();
  });
});

onUnmounted(() => {
  stopScrolling();
  window.removeEventListener('resize', handleResize);
});
</script>

<style scoped>
.info-list-container {
  border: 1px solid rgba(56, 189, 248, 0.3);
  padding: 12px;
  position: relative;
  overflow: hidden;
  height: 300px; /* Fixed height for the container */
}

.list-wrapper {
  height: calc(100% - 50px); /* Adjust based on header height */
  overflow: hidden;
  position: relative;
}

.list-content {
  will-change: transform;
  /* 移除 transition 以实现更流畅的虚拟滚动 */
}

.list-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-sizing: border-box;
  border-bottom: 1px solid rgba(56, 189, 248, 0.1);
  font-size: 14px;
  color: #e0f2fe;
  padding: 8px 0;
  transition: background-color 0.3s;
}

.list-item:hover {
  background-color: rgba(56, 189, 248, 0.1);
}

.list-item.active {
  background-color: rgba(56, 189, 248, 0.3);
  border-left: 3px solid #38bdf8;
  padding-left: 8px; /* Adjust padding to accommodate border */
}


.list-item:last-child {
  border-bottom: none;
}

/* Remove status-badge styles as they will be defined in the parent (DataScreen.vue) */

.section-header {
  margin-bottom: 10px;
}

h2 {
  color: #e0f2fe;
  font-size: 18px;
  margin: 0;
}

.subtitle {
  color: #94a3b8;
  font-size: 12px;
}

/* 骨架屏样式 */
.skeleton-list {
  padding: 10px 0;
  display: flex;
  flex-direction: column;
  gap: 15px;
}

.skeleton-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 5px 0;
}

.skeleton-text {
  height: 14px;
  background: linear-gradient(90deg, 
    rgba(56, 189, 248, 0.1) 25%, 
    rgba(56, 189, 248, 0.2) 37%, 
    rgba(56, 189, 248, 0.1) 63%
  );
  background-size: 400% 100%;
  border-radius: 4px;
  animation: skeleton-loading 1.4s ease infinite;
}

.w-60 { width: 60%; }
.w-30 { width: 30%; }

@keyframes skeleton-loading {
  0% { background-position: 100% 50%; }
  100% { background-position: 0 50%; }
}

.empty-state {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  font-size: 14px;
}
</style>
