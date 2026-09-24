<template>
  <section class="page detail-page" data-module="outbound-detail">
    <header class="page-head detail-head">
      <div>
        <h2>出库单详情</h2>
        <p class="page-desc">详情页读取服务端最新记录，和列表页、导出入口使用同一份状态结论。</p>
      </div>
      <RouterLink class="btn" to="/outbound">返回列表</RouterLink>
    </header>

    <div v-if="entry" class="detail-card">
      <div class="detail-title-row">
        <strong>{{ entry['出库单号'] }}</strong>
        <span :class="['status-badge', statusClass(String(entry.status))]">{{ entry.status }}</span>
      </div>
      <dl class="detail-grid">
        <template v-for="field in detailFields" :key="field">
          <dt>{{ field }}</dt>
          <dd>{{ entry[field] ?? '—' }}</dd>
        </template>
        <dt>记录编号</dt>
        <dd>{{ entry.id }}</dd>
      </dl>
      <div class="detail-actions">
        <button
          v-for="action in availableActions"
          :key="action"
          class="btn primary"
          type="button"
          :disabled="submitting"
          @click="runAction(action)"
        >
          {{ action }}
        </button>
      </div>
      <p v-if="message" :class="messageOk ? 'success-text' : 'error-text'">{{ message }}</p>
    </div>

    <div v-else-if="!errorMessage" class="detail-card empty-state">正在加载出库单详情…</div>
    <div v-else class="detail-card">
      <p class="error-text">{{ errorMessage }}</p>
      <RouterLink class="btn" to="/outbound">返回列表</RouterLink>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type ActionName = '确认拣货' | '安排发运' | '取消出库'
type StatusName = '待拣货' | '已拣货' | '已发运' | '已取消'

const ENDPOINT = '/api/outbound'
const detailFields = ['客户名称', '货物名称', '批次号', '出库数量', '出库温度', '拣货人', '出库时间']
const nextActions: Partial<Record<StatusName, ActionName[]>> = {
  待拣货: ['确认拣货', '取消出库'],
  已拣货: ['安排发运', '取消出库'],
}

const route = useRoute()
const entry = ref<Row | null>(null)
const errorMessage = ref('')
const message = ref('')
const messageOk = ref(false)
const submitting = ref(false)

const entryId = computed(() => Number(route.params.id))
const availableActions = computed(() => {
  if (!entry.value) return []
  return nextActions[String(entry.value.status) as StatusName] ?? []
})

function statusClass(status: string) {
  return {
    待拣货: 'status-pending',
    已拣货: 'status-picked',
    已发运: 'status-shipped',
    已取消: 'status-cancelled',
  }[status] ?? ''
}

async function runAction(action: ActionName) {
  const currentEntry = entry.value
  if (!currentEntry || submitting.value) return
  message.value = ''
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/${currentEntry.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json().catch(() => null) as { ok?: boolean, message?: string } | null
    if (!response.ok || !payload) {
      throw new Error('出库管理动作未生效，请稍后重试')
    }
    messageOk.value = Boolean(payload.ok)
    message.value = payload.message || '出库管理操作完成'
    if (payload.ok) await loadEntry()
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '出库管理操作失败'
  } finally {
    submitting.value = false
  }
}

async function loadEntry() {
  errorMessage.value = ''
  if (!Number.isInteger(entryId.value) || entryId.value <= 0) {
    errorMessage.value = '出库单编号无效'
    entry.value = null
    return
  }
  try {
    const response = await request(`${ENDPOINT}/${entryId.value}`)
    if (!response.ok) {
      throw new Error('出库单详情读取失败')
    }
    entry.value = await response.json()
  } catch (error) {
    entry.value = null
    errorMessage.value = error instanceof Error ? error.message : '出库单详情读取失败'
  }
}

onMounted(loadEntry)
</script>
