<template>
  <section class="page" data-module="outbound">
    <header class="page-head">
      <div>
        <h2>出库管理管理</h2>
        <p class="page-desc">维护出库单，围绕出库单号、客户名称、货物名称、批次号做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记出库单</button>
        <button class="btn" type="button" @click="exportRows">导出出库管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>出库单号</span>
        <input v-model="keyword" placeholder="按出库单号检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      <button
        class="btn primary"
        type="button"
        :disabled="!selectedEligibleCount || submitting"
        @click="batchShip"
      >
        {{ submitting ? '提交中…' : `安排发运（${selectedEligibleCount}）` }}
      </button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th class="select-cell">
            <input
              type="checkbox"
              :checked="allVisibleSelected"
              :indeterminate.prop="someVisibleSelected"
              :disabled="!eligibleRows.length"
              aria-label="全选可发运出库单"
              @change="toggleVisible"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody v-for="status in groupedStatuses" :key="status">
        <tr class="group-row">
          <td :colspan="columns.length + 3">{{ status }}（{{ groupedRows[status].length }}）</td>
        </tr>
        <tr v-for="row in groupedRows[status]" :key="String(row.id)">
          <td class="select-cell">
            <input
              type="checkbox"
              :checked="selectedIds.has(Number(row.id))"
              :disabled="row.status !== '已拣货'"
              aria-label="选择已拣货出库单"
              @change="toggleRow(row)"
            />
          </td>
          <td v-for="(column, index) in columns" :key="column">
            <RouterLink v-if="index === 0" :to="`/outbound/${row.id}`">{{ row[column] ?? '—' }}</RouterLink>
            <span v-else>{{ row[column] ?? '—' }}</span>
          </td>
          <td><span :class="['status-badge', statusClass(String(row.status))]">{{ row.status }}</span></td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              :disabled="submitting"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
      </tbody>
      <tbody v-if="!rows.length">
        <tr>
          <td :colspan="columns.length + 3" class="empty-state">暂无出库管理数据，可先登记出库单</td>
        </tr>
      </tbody>
    </table>

    <div v-if="batchSummary" class="result-panel" :class="batchSummary.ok ? 'is-ok' : 'is-error'">
      <strong>{{ batchSummary.message }}</strong>
      <ul>
        <li v-for="item in batchResults" :key="item.id" :class="item.ok ? 'is-ok' : 'is-error'">
          {{ resultCode(item) }}：{{ item.message }}
        </li>
      </ul>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条出库管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type ActionName = '确认拣货' | '安排发运' | '取消出库'
type StatusName = '待拣货' | '已拣货' | '已发运' | '已取消'

type BatchResultItem = {
  id: number
  code?: string | null
  ok: boolean
  message: string
  entry: Row | null
}

type BatchSummary = {
  ok: boolean
  action: string
  total: number
  success_count: number
  failure_count: number
  message: string
  results: BatchResultItem[]
}

const ENDPOINT = '/api/outbound'
const columns = ["出库单号", "客户名称", "货物名称", "批次号", "出库数量", "出库温度", "拣货人", "出库时间"]
const statuses: StatusName[] = ["待拣货", "已拣货", "已发运", "已取消"]
const nextActions: Partial<Record<StatusName, ActionName[]>> = {
  待拣货: ['确认拣货', '取消出库'],
  已拣货: ['安排发运', '取消出库'],
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const selectedIds = ref<Set<number>>(new Set())
const submitting = ref(false)
const batchSummary = ref<BatchSummary | null>(null)

const stats = computed(() => {
  const picked = rows.value.filter(row => row.status === '已拣货').length
  const shortage = rows.value.filter(row => row.abnormal === true).length
  return [
    { label: "今日出库单", value: rows.value.length },
    { label: "待发运单", value: picked },
    { label: "缺货行数", value: shortage },
  ]
})

const groupedRows = computed<Record<StatusName, Row[]>>(() => {
  const groups = Object.fromEntries(statuses.map(status => [status, [] as Row[]])) as Record<StatusName, Row[]>
  rows.value.forEach((row) => {
    const status = String(row.status) as StatusName
    groups[status]?.push(row)
  })
  return groups
})

const groupedStatuses = computed(() => statuses.filter(status => groupedRows.value[status].length))
const eligibleRows = computed(() => rows.value.filter(row => row.status === '已拣货'))
const selectedEligibleCount = computed(() => eligibleRows.value.filter(row => selectedIds.value.has(Number(row.id))).length)
const allVisibleSelected = computed(() => eligibleRows.value.length > 0 && eligibleRows.value.every(row => selectedIds.value.has(Number(row.id))))
const someVisibleSelected = computed(() => !allVisibleSelected.value && eligibleRows.value.some(row => selectedIds.value.has(Number(row.id))))
const batchResults = computed(() => batchSummary.value?.results ?? [])

function availableActions(row: Row): ActionName[] {
  return nextActions[String(row.status) as StatusName] ?? []
}

function statusClass(status: string) {
  return {
    待拣货: 'status-pending',
    已拣货: 'status-picked',
    已发运: 'status-shipped',
    已取消: 'status-cancelled',
  }[status] ?? ''
}

function resultCode(item: BatchResultItem) {
  return item.code || item.entry?.['出库单号'] || `出库单 ${item.id}`
}

function queryString() {
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (statusFilter.value) params.set('status', statusFilter.value)
  return params.toString()
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  selectedIds.value = new Set()
  void reload()
}

function toggleVisible(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  selectedIds.value = new Set(checked ? eligibleRows.value.map(row => Number(row.id)) : [])
}

function toggleRow(row: Row) {
  const id = Number(row.id)
  const next = new Set(selectedIds.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  selectedIds.value = next
}

function exportRows() {
  const query = queryString()
  window.open(`${ENDPOINT}/export${query ? `?${query}` : ''}`, '_blank')
}

function openCreate() {
  errorMessage.value = '出库单登记入口尚未接入审批流'
}

async function batchShip() {
  if (!selectedEligibleCount.value || submitting.value) return
  errorMessage.value = ''
  batchSummary.value = null
  submitting.value = true
  try {
    const selectedIdsForSubmit = eligibleRows.value
      .map(row => Number(row.id))
      .filter(id => selectedIds.value.has(id))
    const response = await request(`${ENDPOINT}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action: '安排发运', ids: selectedIdsForSubmit }),
    })
    const payload = await response.json().catch(() => null) as BatchSummary | null
    if (!response.ok || !payload) {
      throw new Error('批量安排发运未生效，请稍后重试')
    }
    batchSummary.value = payload
    statusFilter.value = ''
    await reload()
    batchSummary.value = payload
    selectedIds.value = new Set()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量安排发运失败'
  } finally {
    submitting.value = false
  }
}

async function runAction(action: ActionName, row: Row) {
  errorMessage.value = ''
  batchSummary.value = null
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json().catch(() => null) as { ok?: boolean, message?: string } | null
    if (!response.ok || !payload) {
      throw new Error('出库管理动作未生效，请稍后重试')
    }
    if (!payload.ok) {
      errorMessage.value = payload.message || '出库管理操作失败'
      return
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '出库管理操作失败'
  } finally {
    submitting.value = false
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}?${queryString()}`)
    if (!response.ok) {
      throw new Error('出库单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    const visibleIds = new Set(rows.value.map(row => Number(row.id)))
    selectedIds.value = new Set([...selectedIds.value].filter(id => visibleIds.has(id)))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '出库管理列表读取失败'
  }
}

onMounted(reload)
</script>
