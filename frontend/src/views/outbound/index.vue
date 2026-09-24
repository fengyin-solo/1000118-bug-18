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
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="filters['状态']">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div class="batch-bar">
      <label class="batch-check">
        <input
          type="checkbox"
          :checked="allVisibleSelected"
          :indeterminate.prop="someVisibleSelected && !allVisibleSelected"
          @change="toggleAllVisible"
        />
        全选当前分组结果（已选 {{ selectedIds.length }} 张）
      </label>
      <button
        class="btn primary"
        type="button"
        :disabled="!selectedIds.length || batchLoading"
        @click="batchShip"
      >
        {{ batchLoading ? '提交中…' : '批量安排发运' }}
      </button>
      <span class="batch-hint">仅「已拣货」的出库单可安排发运；整组有不满足条件的单据时会全部保留原状。</span>
    </div>

    <div v-if="batchResult" class="result-panel" :class="batchResult.ok ? 'result-ok' : 'result-fail'">
      <div class="result-head">
        <strong>{{ batchResult.ok ? '批量发运成功' : '批量发运未生效' }}</strong>
        <span>{{ batchResult.message }}</span>
        <button class="link" type="button" @click="batchResult = null">关闭</button>
      </div>
      <ul class="result-list">
        <li v-for="item in batchResult.items" :key="String(item.id)">
          <span class="result-tag" :class="item.ok ? 'tag-ok' : 'tag-fail'">{{ item.ok ? '成功' : '失败' }}</span>
          <span class="result-code">{{ item.code || item.id }}</span>
          <span class="result-msg">{{ item.message }}</span>
        </li>
      </ul>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="col-check">选择</th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody v-for="status in visibleStatuses" :key="status">
        <tr class="group-row">
          <td :colspan="columns.length + 3">{{ status }}（{{ groupCounts[status] || 0 }} 张）</td>
        </tr>
        <tr v-for="row in rowsByStatus(status)" :key="String(row.id)">
          <td class="col-check">
            <input
              type="checkbox"
              :value="Number(row.id)"
              v-model="selectedIds"
            />
          </td>
          <td v-for="column in columns" :key="column">
            <button v-if="column === columns[0]" class="link" type="button" @click="openDetail(row)">
              {{ row[column] ?? '—' }}
            </button>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td>
            <span class="status-tag" :class="`status-${statusIndex(status)}`">{{ statusText(row) }}</span>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
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

    <footer class="page-foot">
      <span>共 {{ total }} 条出库管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detail" class="drawer-mask" @click.self="closeDetail">
      <aside class="drawer">
        <header class="drawer-head">
          <strong>出库单明细</strong>
          <button class="link" type="button" @click="closeDetail">关闭</button>
        </header>
        <dl class="detail-list">
          <div v-for="column in detailColumns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ detail.row[column] ?? '—' }}</dd>
          </div>
          <div>
            <dt>状态</dt>
            <dd>
              <span class="status-tag" :class="`status-${statusIndex(statusText(detail.row))}`">{{ statusText(detail.row) }}</span>
            </dd>
          </div>
        </dl>
        <p v-if="detail.errorMessage" class="error-text">{{ detail.errorMessage }}</p>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

interface BatchItemResult {
  id: number
  code: string | null
  ok: boolean
  message: string
}

interface BatchResult {
  ok: boolean
  message: string
  action: string | null
  total: number
  success_count: number
  failure_count: number
  items: BatchItemResult[]
}

interface ActionResponse {
  ok: boolean
  message: string
  entry: Row | null
}

interface DetailState {
  row: Row
  errorMessage: string
}

const ENDPOINT = '/api/outbound'
const columns = ["出库单号", "客户名称", "货物名称", "批次号", "出库数量", "出库温度", "拣货人", "出库时间"]
const detailColumns = ["id", ...columns]
const actions = ["确认拣货", "安排发运", "取消出库"]
const statuses = ["待拣货", "已拣货", "已发运", "已取消"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({ '状态': '' })
const filterFields = columns.slice(0, 3)
const selectedIds = ref<number[]>([])
const batchLoading = ref(false)
const batchResult = ref<BatchResult | null>(null)
const detail = ref<DetailState | null>(null)

const visibleStatuses = computed(() => {
  const current = filters.value['状态']
  return current ? statuses.filter((status) => status === current) : statuses
})

const stats = computed(() => {
  const countBy = (predicate: (row: Row) => boolean) => rows.value.filter(predicate).length
  return [
    { label: "当前页出库单", value: rows.value.length },
    { label: "待发运单", value: countBy((row) => statusText(row) === '已拣货') },
    { label: "待拣货单", value: countBy((row) => statusText(row) === '待拣货') },
  ]
})

const groupCounts = computed<Record<string, number>>(() => {
  const counts: Record<string, number> = {}
  for (const row of rows.value) {
    const status = statusText(row)
    counts[status] = (counts[status] ?? 0) + 1
  }
  return counts
})

const visibleIds = computed(() =>
  rows.value.map((row) => Number(row.id)).filter((id) => Number.isFinite(id)),
)
const allVisibleSelected = computed(
  () => visibleIds.value.length > 0 && visibleIds.value.every((id) => selectedIds.value.includes(id)),
)
const someVisibleSelected = computed(() =>
  visibleIds.value.some((id) => selectedIds.value.includes(id)),
)

function statusText(row: Row): string {
  const status = row['status']
  return typeof status === 'string' ? status : ''
}

function statusIndex(status: string): number {
  const index = statuses.indexOf(status)
  return index < 0 ? 0 : index
}

function rowsByStatus(status: string): Row[] {
  return rows.value.filter((row) => statusText(row) === status)
}

function toggleAllVisible(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  const next = new Set(checked ? visibleIds.value : [])
  for (const id of selectedIds.value) {
    if (!visibleIds.value.includes(id) || checked) {
      next.add(id)
    }
  }
  selectedIds.value = [...next]
}

function resetFilters() {
  filters.value = { '状态': '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '出库单登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json()) as ActionResponse
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '出库管理动作未生效，请稍后重试')
    }
    await reload()
    if (detail.value && detail.value.row.id === row.id && payload.entry) {
      detail.value = { row: payload.entry, errorMessage: '' }
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '出库管理操作失败'
  }
}

async function batchShip() {
  if (!selectedIds.value.length || batchLoading.value) {
    return
  }
  batchLoading.value = true
  errorMessage.value = ''
  batchResult.value = null
  try {
    const response = await request(`${ENDPOINT}/batch-actions`, {
      method: 'POST',
      body: JSON.stringify({ action: '安排发运', ids: selectedIds.value }),
    })
    const payload = (await response.json()) as BatchResult
    if (!response.ok) {
      throw new Error('批量安排发运未送达，请稍后重试')
    }
    // 列表、详情、导出都以接口返回的这份结论为准；成功后用同一份数据刷新列表。
    batchResult.value = payload
    selectedIds.value = []
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量安排发运失败'
  } finally {
    batchLoading.value = false
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('出库单明细读取失败')
    }
    const entry = (await response.json()) as Row
    detail.value = { row: entry, errorMessage: '' }
  } catch (error) {
    // 详情读不出来时至少展示列表行的数据，错误原因单独标注，保证三处口径不互相覆盖。
    detail.value = {
      row,
      errorMessage: error instanceof Error ? error.message : '出库单明细读取失败',
    }
  }
}

function closeDetail() {
  detail.value = null
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters.value)) {
    if (value) {
      params.set(key, value)
    }
  }
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('出库单列表读取失败')
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    const visibleSet = new Set(visibleIds.value)
    selectedIds.value = selectedIds.value.filter((id) => visibleSet.has(id))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '出库管理列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.batch-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.batch-check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.batch-hint {
  color: var(--muted);
  font-size: 12px;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.col-check {
  width: 42px;
  text-align: center;
}
.group-row td {
  background: #f5f7fa;
  font-weight: 600;
}
.status-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  background: #eef1f5;
  color: #4b5563;
}
.status-0 { background: #fdf2e2; color: #b45309; }
.status-1 { background: #e6f0ff; color: #1d4ed8; }
.status-2 { background: #e5f6ec; color: #15803d; }
.status-3 { background: #f1f1f1; color: #6b7280; }
.result-panel {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
  background: #fff;
}
.result-ok { border-color: #9ad8b3; background: #f1faf4; }
.result-fail { border-color: #f0b8b8; background: #fdf3f3; }
.result-head {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  margin-bottom: 6px;
}
.result-head span {
  flex: 1;
  color: var(--muted);
}
.result-list {
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: 13px;
  max-height: 180px;
  overflow: auto;
}
.result-list li {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 2px 0;
}
.result-code {
  min-width: 110px;
  font-weight: 600;
}
.result-msg {
  color: var(--muted);
}
.result-tag {
  font-size: 12px;
  padding: 1px 8px;
  border-radius: 10px;
}
.tag-ok { background: #d5efdf; color: #15803d; }
.tag-fail { background: #f7dada; color: #b91c1c; }
.drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.35);
  display: flex;
  justify-content: flex-end;
  z-index: 20;
}
.drawer {
  width: 380px;
  max-width: 90vw;
  background: #fff;
  height: 100%;
  padding: 16px;
  overflow: auto;
}
.drawer-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.detail-list {
  margin: 0;
}
.detail-list div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px dashed var(--border);
  font-size: 13px;
}
.detail-list dt {
  color: var(--muted);
}
.detail-list dd {
  margin: 0;
  text-align: right;
}
</style>
