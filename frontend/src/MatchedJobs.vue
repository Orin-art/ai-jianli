<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, salary } from './api'

const props = defineProps<{ student: { id: number; name: string } }>()
const emit = defineEmits(['recommended'])
const items = ref<any[]>([]), total = ref(0), missing = ref<string[]>([])
const loading = ref(false), error = ref(''), saving = ref(false)
const selected = ref<any>(null), detailOpen = ref(false)
let requestId = 0
async function load() {
  const id = ++requestId
  loading.value = true; error.value = ''; items.value = []
  try {
    const data = await api(`/students/${props.student.id}/matched-jobs`)
    if (id !== requestId) return
    items.value = data.items; total.value = data.total; missing.value = data.missing_fields
  } catch (e: any) { if (id === requestId) { error.value = e.message; total.value = 0 } }
  finally { if (id === requestId) loading.value = false }
}
watch(() => props.student, () => { selected.value = null; detailOpen.value = false; load() }, { immediate: true })
onBeforeUnmount(() => requestId++)
function show(job: any) { selected.value = job; detailOpen.value = true }
async function recommend() {
  if (!selected.value || saving.value) return
  saving.value = true
  try {
    await api(`/students/${props.student.id}/recommendations`, { method: 'POST', body: JSON.stringify({ job_id: selected.value.id }) })
    ElMessage.success(`已推荐给${props.student.name}，已保存岗位快照`)
    detailOpen.value = false
    emit('recommended')
  } catch (e: any) { ElMessage.error(e.message); await load() }
  finally { saving.value = false }
}
</script>

<template>
  <section class="matched-jobs" aria-label="学员匹配岗位">
    <div class="section-head"><h3>匹配岗位 <small>本次 {{ items.length }} 个候选 · 最多 5 个</small></h3><el-button :loading="loading" :disabled="saving" @click="load()">刷新匹配</el-button></div>
    <p class="hint">城市、意向岗位、学历和专业通过规则筛选后，仅展示排序最靠前的 5 个；不足 5 个不补凑。岗位专业未填写或条件无法核实时不入选。每次只确认推荐 1 个，推荐后补入下一候选。</p>
    <p class="hint">学员经验、期望薪资尚未记录，未参与筛选；确认推荐前仍需核对岗位原文。候选列表不会自动生成推荐记录。</p>
    <p v-if="!loading && !error && total > 5" class="hint">共有 {{ total }} 个岗位通过规则筛选，本次只展示前 5 个。</p>
    <p v-if="!loading && !error && missing.length" class="extraction-warning">建议完善：{{ missing.join('、') }}。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-loading="loading" class="match-results">
      <article v-for="job in items" :key="job.id" class="recommend-card match-card">
        <div class="split"><strong>{{ job.title }}</strong><el-button type="primary" plain @click="show(job)">查看并推荐</el-button></div>
        <p>{{ job.company }} · {{ job.city }} · {{ job.education }} · {{ job.experience }}</p>
        <span class="salary">{{ salary(job) }}</span>
        <div class="match-reasons"><el-tag v-for="reason in job.reasons" :key="reason" type="success" effect="plain">{{ reason }}</el-tag></div>
        <ul class="match-warnings"><li v-for="warning in job.warnings" :key="warning">待核对：{{ warning }}</li></ul>
      </article>
      <div v-if="!loading && !error && !items.length" class="empty-inline">暂无候选岗位，可完善学员意向、导入新岗位，或前往共享岗位库人工查找。</div>
    </div>
    <el-dialog v-model="detailOpen" title="核对匹配岗位" width="640px" append-to-body destroy-on-close :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
      <template v-if="selected">
        <h3>{{ selected.title }}</h3><p class="note-text">{{ selected.company }} · {{ selected.city }}</p><span class="salary">{{ salary(selected) }}</span>
        <div class="info-grid"><div><label>学历要求</label><p>{{ selected.education }}</p></div><div><label>经验要求</label><p>{{ selected.experience }}</p></div><div><label>专业要求</label><p>{{ selected.major || '未填写' }}</p></div><div><label>截止日期</label><p>{{ selected.expires_on || '未填写' }}</p></div></div>
        <h4>岗位描述</h4><p class="description-text">{{ selected.description || '暂无描述，请核对岗位职责。' }}</p>
        <h4>信息来源</h4><p class="note-text">{{ selected.source || '未填写' }}</p>
        <ul class="match-warnings"><li v-for="warning in selected.warnings" :key="warning">待核对：{{ warning }}</li></ul>
        <p class="recommend-target">推荐对象：<strong>{{ student.name }}</strong>（学员编号 {{ student.id }}）</p>
      </template>
      <template #footer><el-button :disabled="saving" @click="detailOpen = false">取消</el-button><el-button type="primary" :loading="saving" @click="recommend">确认推荐给{{ student.name }}</el-button></template>
    </el-dialog>
  </section>
</template>
