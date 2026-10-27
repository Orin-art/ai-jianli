<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, salary } from './api'

type StudentChoice = { id: number; name: string; education?: string; major?: string }
const props = defineProps<{ modelValue: boolean; job: any; initialStudent: StudentChoice | null }>()
const emit = defineEmits(['update:modelValue', 'recommended'])
const query = ref(''), page = ref(1), total = ref(0), loading = ref(false), saving = ref(false)
const students = ref<StudentChoice[]>([]), selected = ref<StudentChoice | null>(null), error = ref('')
let requestId = 0
async function search(reset = false) {
  if (reset) page.value = 1
  const id = ++requestId
  loading.value = true; error.value = ''
  try {
    const data = await api(`/students?q=${encodeURIComponent(query.value)}&page=${page.value}`)
    if (id === requestId) { students.value = data.items; total.value = data.total }
  } catch (e: any) {
    if (id === requestId) { students.value = []; total.value = 0; error.value = e.message }
  } finally { if (id === requestId) loading.value = false }
}
watch(() => props.modelValue, open => {
  if (open) {
    selected.value = props.initialStudent ? { ...props.initialStudent } : null
    query.value = ''; page.value = 1; students.value = []; total.value = 0
    search()
  } else { requestId++; selected.value = null; students.value = []; error.value = '' }
})
async function recommend() {
  if (!selected.value || !props.job || saving.value) return
  const student = selected.value
  saving.value = true
  try {
    await api(`/students/${student.id}/recommendations`, { method: 'POST', body: JSON.stringify({ job_id: props.job.id }) })
    ElMessage.success(`已推荐给${student.name}，已保存岗位快照`)
    emit('recommended', student)
    emit('update:modelValue', false)
  } catch (e: any) { ElMessage.error(e.message) } finally { saving.value = false }
}
</script>

<template>
  <el-dialog :model-value="modelValue" title="推荐给学员" width="640px" append-to-body destroy-on-close :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" @update:model-value="emit('update:modelValue', $event)">
    <div v-if="job" class="recommend-card"><strong>{{ job.title }}</strong><p>{{ job.company }} · {{ job.city }}</p><span class="salary">{{ salary(job) }}</span></div>
    <form class="inline-search recommend-search" @submit.prevent="search(true)"><el-input v-model="query" aria-label="搜索学员" placeholder="搜索学员姓名、专业或意向岗位" clearable /><el-button native-type="submit" :disabled="saving">搜索</el-button></form>
    <p class="hint">仅列出你有权访问的学员；同名学员可通过编号区分。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-loading="loading" class="recommend-options student-options">
      <label v-for="s in students" :key="s.id" class="recommend-option"><input type="radio" name="recommend-student" :checked="selected?.id === s.id" :disabled="loading || saving" :aria-label="`${s.name}（学员编号${s.id}）`" @change="selected = s"><div><strong>{{ s.name }} <small>#{{ s.id }}</small></strong><p>{{ s.education }} · {{ s.major || '专业未填写' }}</p></div></label>
      <el-empty v-if="!loading && !students.length && !error" description="没有找到学员，可调整搜索条件或先新增学员" :image-size="70" />
    </div>
    <div class="pagination"><el-pagination v-model:current-page="page" :disabled="saving" :total="total" :page-size="20" layout="total, prev, pager, next" @current-change="search(false)" /></div>
    <p v-if="selected" class="recommend-target">推荐对象：<strong>{{ selected.name }}</strong>（学员编号 {{ selected.id }}）</p>
    <template #footer><el-button :disabled="saving" @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :disabled="!selected || loading || job?.effective_status !== '有效'" :loading="saving" @click="recommend">{{ selected ? `推荐给${selected.name}` : '请选择学员' }}</el-button></template>
  </el-dialog>
</template>
