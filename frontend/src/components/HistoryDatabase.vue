<template>
  <div 
    class="history-database"
    :class="{ 'no-projects': projects.length === 0 && !loading }"
    ref="historyContainer"
  >
    <!-- 背景装饰: Skill术Network格线 (只在has项目 hour显Example)  -->
    <div v-if="projects.length > 0 || loading" class="tech-grid-bg">
      <div class="grid-pattern"></div>
      <div class="gradient-overlay"></div>
    </div>

    <!-- 标题区域 -->
    <div class="section-header">
      <div class="section-line"></div>
      <span class="section-title">{{ $t('history.title') }}</span>
      <div class="section-line"></div>
    </div>

    <!-- 卡片容Device (只在has项目 hour显Example)  -->
    <div v-if="projects.length > 0" class="cards-container" :class="{ expanded: isExpanded }" :style="containerStyle">
      <div 
        v-for="(project, index) in projects" 
        :key="project.simulation_id"
        class="project-card"
        :class="{ expanded: isExpanded, hovering: hoveringCard === index }"
        :style="getCardStyle(index)"
        @mouseenter="hoveringCard = index"
        @mouseleave="hoveringCard = null"
        @click="navigateToProject(project)"
      >
        <!-- 卡片头部: simulation_id  and  功能可Use状态 -->
        <div class="card-header">
          <span class="card-id">{{ formatSimulationId(project.simulation_id) }}</span>
          <div class="card-status-icons">
            <span 
              class="status-icon" 
              :class="{ available: project.project_id, unavailable: !project.project_id }"
              :title="$t('history.graphBuild')"
            >◇</span>
            <span 
              class="status-icon available" 
              :title="$t('history.envSetup')"
            >◈</span>
            <span 
              class="status-icon" 
              :class="{ available: project.report_id, unavailable: !project.report_id }"
              :title="$t('history.analysisReport')"
            >◆</span>
          </div>
        </div>

        <!-- 文件列表区域 -->
        <div class="card-files-wrapper">
          <!-- Corner decoration - Viewfinder style -->
          <div class="corner-mark top-left-only"></div>
          
          <!-- 文件列表 -->
          <div class="files-list" v-if="project.files && project.files.length > 0">
            <div 
              v-for="(file, fileIndex) in project.files.slice(0, 3)" 
              :key="fileIndex"
              class="file-item"
            >
              <span class="file-tag" :class="getFileType(file.filename)">{{ getFileTypeLabel(file.filename) }}</span>
              <span class="file-name">{{ truncateFilename(file.filename, 20) }}</span>
            </div>
            <!-- Show Prompt If More Files Exist -->
            <div v-if="project.files.length > 3" class="files-more">
              {{ $t('history.moreFiles', { count: project.files.length - 3 }) }}
            </div>
          </div>
          <!-- Placeholder when no file is present -->
          <div class="files-empty" v-else>
            <span class="empty-file-icon">◇</span>
            <span class="empty-file-text">{{ $t('history.noFiles') }}</span>
          </div>
        </div>

        <!-- 卡片标题 (使Use模Draft需Request的before 20字作为标题)  -->
        <h3 class="card-title">{{ getSimulationTitle(project.simulation_requirement) }}</h3>

        <!-- 卡片描Description (模Draft需Request完整DisplayExample)  -->
        <p class="card-desc">{{ truncateText(project.simulation_requirement, 55) }}</p>

        <!-- 卡片底部 -->
        <div class="card-footer">
          <div class="card-datetime">
            <span class="card-date">{{ formatDate(project.created_at) }}</span>
            <span class="card-time">{{ formatTime(project.created_at) }}</span>
          </div>
          <span class="card-progress" :class="getProgressClass(project)">
            <span class="status-dot">●</span> {{ formatRounds(project) }}
          </span>
        </div>
        
        <!-- 底部装饰线 (hover hourDisplay开) -->
        <div class="card-bottom-line"></div>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="loading-state">
      <span class="loading-spinner"></span>
      <span class="loading-text">{{ $t('history.loadingText') }}</span>
    </div>

    <!-- 历史回Release详情弹Window -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="selectedProject" class="modal-overlay" @click.self="closeModal">
          <div class="modal-content">
            <!-- 弹Window头部 -->
            <div class="modal-header">
              <div class="modal-title-section">
                <span class="modal-id">{{ formatSimulationId(selectedProject.simulation_id) }}</span>
                <span class="modal-progress" :class="getProgressClass(selectedProject)">
                  <span class="status-dot">●</span> {{ formatRounds(selectedProject) }}
                </span>
                <span class="modal-create-time">{{ formatDate(selectedProject.created_at) }} {{ formatTime(selectedProject.created_at) }}</span>
              </div>
              <button class="modal-close" @click="closeModal">×</button>
            </div>

            <!-- 弹Window内容 -->
            <div class="modal-body">
              <!-- 模Draft需Request -->
              <div class="modal-section">
                <div class="modal-label">{{ $t('history.simRequirement') }}</div>
                <div class="modal-requirement">{{ selectedProject.simulation_requirement || $t('common.none') }}</div>
              </div>

              <!-- 文件列表 -->
              <div class="modal-section">
                <div class="modal-label">{{ $t('history.relatedFiles') }}</div>
                <div class="modal-files" v-if="selectedProject.files && selectedProject.files.length > 0">
                  <div v-for="(file, index) in selectedProject.files" :key="index" class="modal-file-item">
                    <span class="file-tag" :class="getFileType(file.filename)">{{ getFileTypeLabel(file.filename) }}</span>
                    <span class="modal-file-name">{{ file.filename }}</span>
                  </div>
                </div>
                <div class="modal-empty" v-else>{{ $t('history.noRelatedFiles') }}</div>
              </div>
            </div>

            <!-- PushPerform回Release minCut线 -->
            <div class="modal-divider">
              <span class="divider-line"></span>
              <span class="divider-text">{{ $t('history.replayTitle') }}</span>
              <span class="divider-line"></span>
            </div>

            <!-- 导航按钮 -->
            <div class="modal-actions">
              <button 
                class="modal-btn btn-project" 
                @click="goToProject"
                :disabled="!selectedProject.project_id"
              >
                <span class="btn-step">Step1</span>
                <span class="btn-icon">◇</span>
                <span class="btn-text">{{ $t('history.step1Button') }}</span>
              </button>
              <button 
                class="modal-btn btn-simulation" 
                @click="goToSimulation"
              >
                <span class="btn-step">Step2</span>
                <span class="btn-icon">◈</span>
                <span class="btn-text">{{ $t('history.step2Button') }}</span>
              </button>
              <button 
                class="modal-btn btn-report" 
                @click="goToReport"
                :disabled="!selectedProject.report_id"
              >
                <span class="btn-step">Step4</span>
                <span class="btn-icon">◆</span>
                <span class="btn-text">{{ $t('history.step4Button') }}</span>
              </button>
            </div>
            <!-- 不可回Release提Example -->
            <div class="modal-playback-hint">
              <span class="hint-text">{{ $t('history.replayHint') }}</span>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, onActivated, watch, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getSimulationHistory } from '../api/simulation'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()

// 状态
const projects = ref([])
const loading = ref(true)
const isExpanded = ref(false)
const hoveringCard = ref(null)
const historyContainer = ref(null)
const selectedProject = ref(null)  // 当before 选in 的项目 (Use于弹Window) 
let observer = null
let isAnimating = false  // 动画锁, 防止闪Sparkle
let expandDebounceTimer = null  // 防抖定 hourDevice
let pendingState = null  // Record target state pending execution

// 卡片布局配置 - Invoke整为更宽的比例
const CARDS_PER_ROW = 4
const CARD_WIDTH = 280  
const CARD_HEIGHT = 280 
const CARD_GAP = 24

// 动态计算容Device高度样式
const containerStyle = computed(() => {
  if (!isExpanded.value) {
    // 折叠态: 固定高度
    return { minHeight: '420px' }
  }
  
  // Display开态: 根据卡片数量动态计算高度
  const total = projects.value.length
  if (total === 0) {
    return { minHeight: '280px' }
  }
  
  const rows = Math.ceil(total / CARDS_PER_ROW)
  // 计算实际需要的高度: 行数 * 卡片高度 + (行数-1) * 间距 + 少量底部间距
  const expandedHeight = rows * CARD_HEIGHT + (rows - 1) * CARD_GAP + 10
  
  return { minHeight: `${expandedHeight}px` }
})

// 获取卡片样式
const getCardStyle = (index) => {
  const total = projects.value.length
  
  if (isExpanded.value) {
    // Display开态: Network格布局
    const transition = 'transform 700ms cubic-bezier(0.23, 1, 0.32, 1), opacity 700ms cubic-bezier(0.23, 1, 0.32, 1), box-shadow 0.3s ease, border-color 0.3s ease'

    const col = index % CARDS_PER_ROW
    const row = Math.floor(index / CARDS_PER_ROW)
    
    // Calculate the number of cards in the current line to ensure centering
    const currentRowStart = row * CARDS_PER_ROW
    const currentRowCards = Math.min(CARDS_PER_ROW, total - currentRowStart)
    
    const rowWidth = currentRowCards * CARD_WIDTH + (currentRowCards - 1) * CARD_GAP
    
    const startX = -(rowWidth / 2) + (CARD_WIDTH / 2)
    const colInRow = index % CARDS_PER_ROW
    const x = startX + colInRow * (CARD_WIDTH + CARD_GAP)
    
    // 向under Display开, 增加 and 标题的间距
    const y = 20 + row * (CARD_HEIGHT + CARD_GAP)

    return {
      transform: `translate(${x}px, ${y}px) rotate(0deg) scale(1)`,
      zIndex: 100 + index,
      opacity: 1,
      transition: transition
    }
  } else {
    // 折叠态: 扇形Heap叠
    const transition = 'transform 700ms cubic-bezier(0.23, 1, 0.32, 1), opacity 700ms cubic-bezier(0.23, 1, 0.32, 1), box-shadow 0.3s ease, border-color 0.3s ease'

    const centerIndex = (total - 1) / 2
    const offset = index - centerIndex
    
    const x = offset * 35
    // Invoke整起Start位置, 靠近标题但保持适当间距
    const y = 25 + Math.abs(offset) * 8
    const r = offset * 3
    const s = 0.95 - Math.abs(offset) * 0.05
    
    return {
      transform: `translate(${x}px, ${y}px) rotate(${r}deg) scale(${s})`,
      zIndex: 10 + index,
      opacity: 1,
      transition: transition
    }
  }
}

// 根据 rounds数进度获取样式Class
const getProgressClass = (simulation) => {
  const current = simulation.current_round || 0
  const total = simulation.total_rounds || 0
  
  if (total === 0 || current === 0) {
    // not 开Start
    return 'not-started'
  } else if (current >= total) {
    // Completed
    return 'completed'
  } else {
    // 进行in 
    return 'in-progress'
  }
}

// FormatTransform day期 (只显Example day期部 min) 
const formatDate = (dateStr) => {
  if (!dateStr) return ''
  try {
    const date = new Date(dateStr)
    // Use local date components (like formatTime below) so the displayed day
    // matches the displayed time. toISOString() converts to UTC and can show
    // the wrong day for non-UTC clients near midnight.
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  } catch {
    return dateStr?.slice(0, 10) || ''
  }
}

// FormatTransform hour间 (显Example hour: min) 
const formatTime = (dateStr) => {
  if (!dateStr) return ''
  try {
    const date = new Date(dateStr)
    const hours = date.getHours().toString().padStart(2, '0')
    const minutes = date.getMinutes().toString().padStart(2, '0')
    return `${hours}:${minutes}`
  } catch {
    return ''
  }
}

// 截断文本
const truncateText = (text, maxLength) => {
  if (!text) return ''
  return text.length > maxLength ? text.slice(0, maxLength) + '...' : text
}

// 从模Draft需Request生成标题 (取before 20字) 
const getSimulationTitle = (requirement) => {
  if (!requirement) return t('history.untitledSimulation')
  const title = requirement.slice(0, 20)
  return requirement.length > 20 ? title + '...' : title
}

// FormatTransform simulation_id 显Example (截取before 6位) 
const formatSimulationId = (simulationId) => {
  if (!simulationId) return 'SIM_UNKNOWN'
  const prefix = simulationId.replace('sim_', '').slice(0, 6)
  return `SIM_${prefix.toUpperCase()}`
}

// FormatTransform rounds数显Example (当before  rounds/总 rounds数) 
const formatRounds = (simulation) => {
  const current = simulation.current_round || 0
  const total = simulation.total_rounds || 0
  if (total === 0) return t('history.notStarted')
  return t('history.roundsProgress', { current, total })
}

// 获取文件Class型 (Use于样式) 
const getFileType = (filename) => {
  if (!filename) return 'other'
  const ext = filename.split('.').pop()?.toLowerCase()
  const typeMap = {
    'pdf': 'pdf',
    'doc': 'doc', 'docx': 'doc',
    'xls': 'xls', 'xlsx': 'xls', 'csv': 'xls',
    'ppt': 'ppt', 'pptx': 'ppt',
    'txt': 'txt', 'md': 'txt', 'json': 'code',
    'jpg': 'img', 'jpeg': 'img', 'png': 'img', 'gif': 'img',
    'zip': 'zip', 'rar': 'zip', '7z': 'zip'
  }
  return typeMap[ext] || 'other'
}

// 获取文件Class型标签文本
const getFileTypeLabel = (filename) => {
  if (!filename) return 'FILE'
  const ext = filename.split('.').pop()?.toUpperCase()
  return ext || 'FILE'
}

// 截断文件名 (保留扩Display名) 
const truncateFilename = (filename, maxLength) => {
  if (!filename) return t('history.unknownFile')
  if (filename.length <= maxLength) return filename
  
  const ext = filename.includes('.') ? '.' + filename.split('.').pop() : ''
  const nameWithoutExt = filename.slice(0, filename.length - ext.length)
  const truncatedName = nameWithoutExt.slice(0, maxLength - ext.length - 3) + '...'
  return truncatedName + ext
}

// 打开项目详情弹Window
const navigateToProject = (simulation) => {
  selectedProject.value = simulation
}

// Close popup
const closeModal = () => {
  selectedProject.value = null
}

// 导航到图谱构建页面 (Project) 
const goToProject = () => {
  if (selectedProject.value?.project_id) {
    router.push({
      name: 'Process',
      params: { projectId: selectedProject.value.project_id }
    })
    closeModal()
  }
}

// 导航到环境配置页面 (Simulation) 
const goToSimulation = () => {
  if (selectedProject.value?.simulation_id) {
    router.push({
      name: 'Simulation',
      params: { simulationId: selectedProject.value.simulation_id }
    })
    closeModal()
  }
}

// 导航到 min析报告页面 (Report) 
const goToReport = () => {
  if (selectedProject.value?.report_id) {
    router.push({
      name: 'Report',
      params: { reportId: selectedProject.value.report_id }
    })
    closeModal()
  }
}

// 加载历史项目
const loadHistory = async () => {
  try {
    loading.value = true
    const response = await getSimulationHistory(20)
    if (response.success) {
      projects.value = response.data || []
    }
  } catch (error) {
    console.error('Failed to load historical projects:', error)
    projects.value = []
  } finally {
    loading.value = false
  }
}

// 初StartTransform IntersectionObserver
const initObserver = () => {
  if (observer) {
    observer.disconnect()
  }
  
  observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        const shouldExpand = entry.isIntersecting
        
        // 更新Pending执行的目标状态 (none论is no在动画in 都要记录最新的目标状态) 
        pendingState = shouldExpand
        
        // 清除之before 的防抖定 hourDevice (新的Scroll动意图会覆Cover旧的) 
        if (expandDebounceTimer) {
          clearTimeout(expandDebounceTimer)
          expandDebounceTimer = null
        }
        
        // 如果正在动画in , 只记录状态, 等动画结Bundleafter Location理
        if (isAnimating) return
        
        // 如果目标状态 and 当before 状态相Same, 不需要Location理
        if (shouldExpand === isExpanded.value) {
          pendingState = null
          return
        }
        
        // 使Use防抖延迟状态切换, 防止快速闪Sparkle
        // Display开 hour延迟relatively短(50ms), 收起 hour延迟relatively长(200ms)以增加稳定性
        const delay = shouldExpand ? 50 : 200
        
        expandDebounceTimer = setTimeout(() => {
          // 检查is no正在动画
          if (isAnimating) return
          
          // 检查Pending执行状态is no仍需要执行 (可能already 被after 续Scroll动覆Cover) 
          if (pendingState === null || pendingState === isExpanded.value) return
          
          // Set animation lock
          isAnimating = true
          isExpanded.value = pendingState
          pendingState = null
          
          // 动画完成after 解除锁定, 并检查is nohasPendingLocation理的状态ChangeTransform
          setTimeout(() => {
            isAnimating = false
            
            // 动画结Bundleafter , 检查is nohas新的Pending执行状态
            if (pendingState !== null && pendingState !== isExpanded.value) {
              // 延迟一小Segment hour间再执行, 避免Too快切换
              expandDebounceTimer = setTimeout(() => {
                if (pendingState !== null && pendingState !== isExpanded.value) {
                  isAnimating = true
                  isExpanded.value = pendingState
                  pendingState = null
                  setTimeout(() => {
                    isAnimating = false
                  }, 750)
                }
              }, 100)
            }
          }, 750)
        }, delay)
      })
    },
    {
      // 使Use多阈值, 使检测更平滑
      threshold: [0.4, 0.6, 0.8],
      // Invoke整 rootMargin, 视口底部向on 收缩, 需要Scroll动更多才Trigger发Display开
      rootMargin: '0px 0px -150px 0px'
    }
  )
  
  // 开Start观Observe
  if (historyContainer.value) {
    observer.observe(historyContainer.value)
  }
}

// 监听路由ChangeTransform, 当Return首页 hour重新加载数据
watch(() => route.path, (newPath) => {
  if (newPath === '/') {
    loadHistory()
  }
})

onMounted(async () => {
  // 确保 DOM 渲Color完成after 再加载数据
  await nextTick()
  await loadHistory()
  
  // 等Pending DOM 渲Colorafter 初StartTransform观ObserveDevice
  setTimeout(() => {
    initObserver()
  }, 100)
})

// 如果使Use keep-alive, 在组件激活 hour重新加载数据
onActivated(() => {
  loadHistory()
})

onUnmounted(() => {
  // 清理 Intersection Observer
  if (observer) {
    observer.disconnect()
    observer = null
  }
  // 清理防抖定 hourDevice
  if (expandDebounceTimer) {
    clearTimeout(expandDebounceTimer)
    expandDebounceTimer = null
  }
})
</script>

<style scoped>
/* 容Device */
.history-database {
  position: relative;
  width: 100%;
  min-height: 280px;
  margin-top: 40px;
  padding: 35px 0 40px;
  overflow: visible;
}

/* none项目 hour简Transform显Example */
.history-database.no-projects {
  min-height: auto;
  padding: 40px 0 20px;
}

/* Skill术Network格背景 */
.tech-grid-bg {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  overflow: hidden;
  pointer-events: none;
}

/* 使UseCSS背景图案Create固定间距的正方形Network格 */
.grid-pattern {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-image: 
    linear-gradient(to right, rgba(0, 0, 0, 0.05) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(0, 0, 0, 0.05) 1px, transparent 1px);
  background-size: 50px 50px;
  /* 从左on 角开Start定位, 高度ChangeTransform hour只在底部扩Display, 不影响already hasNetwork格位置 */
  background-position: top left;
}

.gradient-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: 
    linear-gradient(to right, rgba(255, 255, 255, 0.9) 0%, transparent 15%, transparent 85%, rgba(255, 255, 255, 0.9) 100%),
    linear-gradient(to bottom, rgba(255, 255, 255, 0.8) 0%, transparent 20%, transparent 80%, rgba(255, 255, 255, 0.8) 100%);
  pointer-events: none;
}

/* 标题区域 */
.section-header {
  position: relative;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 24px;
  margin-bottom: 24px;
  font-family: 'JetBrains Mono', 'SF Mono', monospace;
  padding: 0 40px;
}

.section-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, #E5E7EB, transparent);
  max-width: 300px;
}

.section-title {
  font-size: 0.8rem;
  font-weight: 500;
  color: #9CA3AF;
  letter-spacing: 3px;
  text-transform: uppercase;
}

/* 卡片容Device */
.cards-container {
  position: relative;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 0 40px;
  transition: min-height 700ms cubic-bezier(0.23, 1, 0.32, 1);
  /* min-height 由 JS 动态计算, 根据卡片数量自适应 */
}

/* Project card */
.project-card {
  position: absolute;
  width: 280px;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 0;
  padding: 14px;
  cursor: pointer;
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
  transition: box-shadow 0.3s ease, border-color 0.3s ease, transform 700ms cubic-bezier(0.23, 1, 0.32, 1), opacity 700ms cubic-bezier(0.23, 1, 0.32, 1);
}

.project-card:hover {
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
  border-color: rgba(0, 0, 0, 0.4);
  z-index: 1000 !important;
}

.project-card.hovering {
  z-index: 1000 !important;
}

/* 卡片头部 */
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #F3F4F6;
  font-family: 'JetBrains Mono', 'SF Mono', monospace;
  font-size: 0.7rem;
}

.card-id {
  color: #6B7280;
  letter-spacing: 0.5px;
  font-weight: 500;
}

/* 功能状态图标组 */
.card-status-icons {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-icon {
  font-size: 0.75rem;
  transition: all 0.2s ease;
  cursor: default;
}

.status-icon.available {
  opacity: 1;
}

/* 不Same功能的颜Color */
.status-icon:nth-child(1).available { color: #3B82F6; } /* 图谱构建 - 蓝Color */
.status-icon:nth-child(2).available { color: #F59E0B; } /* 环境Setup建 - 橙Color */
.status-icon:nth-child(3).available { color: #10B981; } /*  min析报告 - 绿Color */

.status-icon.unavailable {
  color: #D1D5DB;
  opacity: 0.5;
}

/*  rounds数进度显Example */
.card-progress {
  display: flex;
  align-items: center;
  gap: 6px;
  letter-spacing: 0.5px;
  font-weight: 600;
  font-size: 0.65rem;
}

.status-dot {
  font-size: 0.5rem;
}

/* Progress Status Color */
.card-progress.completed { color: #10B981; }    /* Completed - 绿Color */
.card-progress.in-progress { color: #F59E0B; }  /* 进行in  - 橙Color */
.card-progress.not-started { color: #9CA3AF; }  /* not 开Start - 灰Color */
.card-status.pending { color: #9CA3AF; }

/* 文件列表区域 */
.card-files-wrapper {
  position: relative;
  width: 100%;
  min-height: 48px;
  max-height: 110px;
  margin-bottom: 12px;
  padding: 8px 10px;
  background: linear-gradient(135deg, #f8f9fa 0%, #f1f3f4 100%);
  border-radius: 4px;
  border: 1px solid #e8eaed;
  overflow: hidden;
}

.files-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* 更多文件提Example */
.files-more {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 3px 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.6rem;
  color: #6B7280;
  background: rgba(255, 255, 255, 0.5);
  border-radius: 3px;
  letter-spacing: 0.3px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 6px;
  background: rgba(255, 255, 255, 0.7);
  border-radius: 3px;
  transition: all 0.2s ease;
}

.file-item:hover {
  background: rgba(255, 255, 255, 1);
  transform: translateX(2px);
  border-color: #e5e7eb;
}

/* Minimalist File Tag Style */
.file-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 16px;
  padding: 0 4px;
  border-radius: 2px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.55rem;
  font-weight: 600;
  line-height: 1;
  text-transform: uppercase;
  letter-spacing: 0.2px;
  flex-shrink: 0;
  min-width: 28px;
}

/* 低饱 and 度配Color方案 - MorandiColorSystem */
.file-tag.pdf { background: #f2e6e6; color: #a65a5a; }
.file-tag.doc { background: #e6eff5; color: #5a7ea6; }
.file-tag.xls { background: #e6f2e8; color: #5aa668; }
.file-tag.ppt { background: #f5efe6; color: #a6815a; }
.file-tag.txt { background: #f0f0f0; color: #757575; }
.file-tag.code { background: #eae6f2; color: #815aa6; }
.file-tag.img { background: #e6f2f2; color: #5aa6a6; }
.file-tag.zip { background: #f2f0e6; color: #a69b5a; }
.file-tag.other { background: #f3f4f6; color: #6b7280; }

.file-name {
  font-family: 'Inter', sans-serif;
  font-size: 0.7rem;
  color: #4b5563;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  letter-spacing: 0.1px;
}

/* Placeholder when no file is present */
.files-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 48px;
  color: #9CA3AF;
}

.empty-file-icon {
  font-size: 1rem;
  opacity: 0.5;
}

.empty-file-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  letter-spacing: 0.5px;
}

/* 悬停 hour文件区域效果 */
.project-card:hover .card-files-wrapper {
  border-color: #d1d5db;
  background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%);
}

/* Corner decoration */
.corner-mark.top-left-only {
  position: absolute;
  top: 6px;
  left: 6px;
  width: 8px;
  height: 8px;
  border-top: 1.5px solid rgba(0, 0, 0, 0.4);
  border-left: 1.5px solid rgba(0, 0, 0, 0.4);
  pointer-events: none;
  z-index: 10;
}

/* 卡片标题 */
.card-title {
  font-family: 'Inter', -apple-system, sans-serif;
  font-size: 0.9rem;
  font-weight: 700;
  color: #111827;
  margin: 0 0 6px 0;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: color 0.3s ease;
}

.project-card:hover .card-title {
  color: #2563EB;
}

/* 卡片描Description */
.card-desc {
  font-family: 'Inter', sans-serif;
  font-size: 0.75rem;
  color: #6B7280;
  margin: 0 0 16px 0;
  line-height: 1.5;
  height: 34px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* 卡片底部 */
.card-footer {
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 12px;
  border-top: 1px solid #F3F4F6;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.65rem;
  color: #9CA3AF;
  font-weight: 500;
}

/*  day期 hour间组合 */
.card-datetime {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 底部 rounds数进度显Example */
.card-footer .card-progress {
  display: flex;
  align-items: center;
  gap: 6px;
  letter-spacing: 0.5px;
  font-weight: 600;
  font-size: 0.65rem;
}

.card-footer .status-dot {
  font-size: 0.5rem;
}

/* Progress Status Color - 底部 */
.card-footer .card-progress.completed { color: #10B981; }
.card-footer .card-progress.in-progress { color: #F59E0B; }
.card-footer .card-progress.not-started { color: #9CA3AF; }

/* 底部装饰线 */
.card-bottom-line {
  position: absolute;
  bottom: 0;
  left: 0;
  height: 2px;
  width: 0;
  background-color: #000;
  transition: width 0.5s cubic-bezier(0.23, 1, 0.32, 1);
  z-index: 20;
}

.project-card:hover .card-bottom-line {
  width: 100%;
}

/* 空状态 */
.empty-state, .loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  padding: 48px;
  color: #9CA3AF;
}

.empty-icon {
  font-size: 2rem;
  opacity: 0.5;
}

.loading-spinner {
  width: 24px;
  height: 24px;
  border: 2px solid #E5E7EB;
  border-top-color: #6B7280;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 响应式 */
@media (max-width: 1200px) {
  .project-card {
    width: 240px;
  }
}

@media (max-width: 768px) {
  .cards-container {
    padding: 0 20px;
  }
  .project-card {
    width: 200px;
  }
}

/* ===== 历史回Release详情弹Window样式 ===== */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  backdrop-filter: blur(4px);
}

.modal-content {
  background: #FFFFFF;
  width: 560px;
  max-width: 90vw;
  max-height: 85vh;
  overflow-y: auto;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
}

/* 动画过Cross */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.3s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .modal-content {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.modal-leave-active .modal-content {
  transition: all 0.2s ease-in;
}

.modal-enter-from .modal-content {
  transform: scale(0.95) translateY(10px);
  opacity: 0;
}

.modal-leave-to .modal-content {
  transform: scale(0.95) translateY(10px);
  opacity: 0;
}

/* 弹Window头部 */
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 32px;
  border-bottom: 1px solid #F3F4F6;
  background: #FFFFFF;
}

.modal-title-section {
  display: flex;
  align-items: center;
  gap: 16px;
}

.modal-id {
  font-family: 'JetBrains Mono', monospace;
  font-size: 1rem;
  font-weight: 600;
  color: #111827;
  letter-spacing: 0.5px;
}

.modal-progress {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 4px;
  background: #F9FAFB;
}

.modal-progress.completed { color: #10B981; background: rgba(16, 185, 129, 0.1); }
.modal-progress.in-progress { color: #F59E0B; background: rgba(245, 158, 11, 0.1); }
.modal-progress.not-started { color: #9CA3AF; background: #F3F4F6; }

.modal-create-time {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  color: #9CA3AF;
  letter-spacing: 0.3px;
}

.modal-close {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  font-size: 1.5rem;
  color: #9CA3AF;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  border-radius: 6px;
}

.modal-close:hover {
  background: #F3F4F6;
  color: #111827;
}

/* 弹Window内容 */
.modal-body {
  padding: 24px 32px;
}

.modal-section {
  margin-bottom: 24px;
}

.modal-section:last-child {
  margin-bottom: 0;
}

.modal-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  color: #6B7280;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 10px;
  font-weight: 500;
}

.modal-requirement {
  font-size: 0.95rem;
  color: #374151;
  line-height: 1.6;
  padding: 16px;
  background: #F9FAFB;
  border: 1px solid #F3F4F6;
  border-radius: 8px;
}

.modal-files {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 200px;
  overflow-y: auto;
  padding-right: 4px;
}

/* 自定义Scroll动 items样式 */
.modal-files::-webkit-scrollbar {
  width: 4px;
}

.modal-files::-webkit-scrollbar-track {
  background: #F3F4F6;
  border-radius: 2px;
}

.modal-files::-webkit-scrollbar-thumb {
  background: #D1D5DB;
  border-radius: 2px;
}

.modal-files::-webkit-scrollbar-thumb:hover {
  background: #9CA3AF;
}

.modal-file-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  transition: all 0.2s ease;
}

.modal-file-item:hover {
  border-color: #D1D5DB;
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
}

.modal-file-name {
  font-size: 0.85rem;
  color: #4B5563;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.modal-empty {
  font-size: 0.85rem;
  color: #9CA3AF;
  padding: 16px;
  background: #F9FAFB;
  border: 1px dashed #E5E7EB;
  border-radius: 6px;
  text-align: center;
}

/* PushPerform回Release minCut线 */
.modal-divider {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 32px 0;
  background: #FFFFFF;
}

.divider-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, #E5E7EB, transparent);
}

.divider-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  color: #9CA3AF;
  letter-spacing: 2px;
  text-transform: uppercase;
  white-space: nowrap;
}

/* 导航按钮 */
.modal-actions {
  display: flex;
  gap: 16px;
  padding: 20px 32px;
  background: #FFFFFF;
}

.modal-btn {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  background: #FFFFFF;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
  overflow: hidden;
}

.modal-btn:hover:not(:disabled) {
  border-color: #000000;
  transform: translateY(-2px);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}

.modal-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background: #F9FAFB;
}

.btn-step {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.6rem;
  font-weight: 500;
  color: #9CA3AF;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.btn-icon {
  font-size: 1.4rem;
  line-height: 1;
  transition: color 0.2s ease;
}

.btn-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.5px;
  color: #4B5563;
}

.modal-btn.btn-project .btn-icon { color: #3B82F6; }
.modal-btn.btn-simulation .btn-icon { color: #F59E0B; }
.modal-btn.btn-report .btn-icon { color: #10B981; }

.modal-btn:hover:not(:disabled) .btn-text {
  color: #111827;
}

/* 不可回Release提Example */
.modal-playback-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 32px 20px;
  background: #FFFFFF;
}

.hint-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  color: #9CA3AF;
  letter-spacing: 0.3px;
  text-align: center;
  line-height: 1.5;
}
</style>
