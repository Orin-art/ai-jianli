<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import { download } from './api'

type ExportJob = { id: number; title: string; company: string; city: string }
const props = defineProps<{ student: { id: number; name: string }; jobs: ExportJob[]; label?: string }>()
const opened = ref(false), exporting = ref(false), table = ref<any>(null)
const rows = ref<ExportJob[]>([]), selected = ref<ExportJob[]>([])
watch(() => props.student.id, () => { opened.value = false; selected.value = []; rows.value = [] })
async function open() {
  rows.value = [...props.jobs]; selected.value = []; opened.value = true
  await nextTick()
  table.value?.clearSelection()
  rows.value.forEach(row => table.value?.toggleRowSelection(row, true))
}
async function exportSelected() {
  if (!selected.value.length || exporting.value) return
  const student = { ...props.student }
  const ids = selected.value.map(job => job.id)
  const date = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date())
  const name = student.name.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_')
  exporting.value = true
  try {
    await download(`/students/${student.id}/jobs/export`, `${name}_筛选岗位_${date}.xlsx`, { method: 'POST', body: JSON.stringify({ job_ids: ids }) })
    opened.value = false
    ElMessage.success(`已导出${student.name}的 ${ids.length} 个岗位`)
  } catch (e: any) { ElMessage.error(e.message) }
  finally { exporting.value = false }
}
</script>

<template>
  <el-button :icon="Download" :disabled="!jobs.length || exporting" @click="open">{{ label || '导出岗位（原表格式）' }}</el-button>
  <el-dialog v-model="opened" title="导出学员岗位" width="min(760px, 96vw)" append-to-body destroy-on-close :close-on-click-modal="!exporting" :close-on-press-escape="!exporting" :show-close="!exporting">
    <p>导出对象：<strong>{{ student.name }}</strong> · 已选 {{ selected.length }} / {{ rows.length }} 个岗位</p>
    <p class="hint">按导入时的岗位原文导出，保留原表列顺序、列宽、行高、单元格样式、日期格式和链接。不同来源文件分工作表保存。</p>
    <p class="hint">历史未留存原文件的岗位按已有字段生成模板，无法恢复原文件样式。导出不会自动保存推荐记录。</p>
    <el-table ref="table" :data="rows" row-key="id" max-height="400" @selection-change="selected = $event">
      <el-table-column type="selection" width="48" :selectable="() => !exporting" />
      <el-table-column prop="title" label="招聘岗位" min-width="180" show-overflow-tooltip />
      <el-table-column prop="company" label="公司" min-width="160" show-overflow-tooltip />
      <el-table-column prop="city" label="工作地点" min-width="130" show-overflow-tooltip />
    </el-table>
    <p v-if="rows.length > 2000" class="extraction-warning">每次最多导出 2,000 个岗位，请减少勾选数量。</p>
    <template #footer><el-button :disabled="exporting" @click="opened = false">取消</el-button><el-button type="primary" :loading="exporting" :disabled="!selected.length || selected.length > 2000" @click="exportSelected">下载 Excel（{{ selected.length }} 个岗位）</el-button></template>
  </el-dialog>
</template>
