<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, salary, time } from './api'
import ExportJobs from './ExportJobs.vue'

const props = defineProps<{ student: any }>()
const emit = defineEmits(['recommended'])
const service = ref<any>(null), setupError = ref(''), error = ref('')
const resumeId = ref<number | null>(null), consent = ref(false), generating = ref(false), saving = ref(false)
const result = ref<any>(null), selected = ref<any>(null), detailOpen = ref(false)
const dismissed = ref<{ job: any; position: number }[]>([])
let requestId = 0, alive = true
async function loadStatus() {
  setupError.value = ''
  try { const data = await api('/ai/status'); if (alive) service.value = data }
  catch (e: any) { if (alive) setupError.value = e.message }
}
loadStatus()
function clear() { requestId++; result.value = null; dismissed.value = []; error.value = ''; selected.value = null; detailOpen.value = false; generating.value = false; consent.value = false }
watch(() => JSON.stringify([props.student.id, props.student.target_city, props.student.target_role, props.student.education, props.student.major]), clear)
watch(() => props.student.resumes.map((r: any) => r.id).join(','), () => {
  if (!props.student.resumes.some((r: any) => r.id === resumeId.value)) { clear(); resumeId.value = props.student.resumes[0]?.id ?? null }
}, { immediate: true })
watch(resumeId, clear)
watch(() => props.student.recommendations.map((r: any) => r.job_id).join(','), () => {
  if (result.value) result.value.items = result.value.items.filter((j: any) => !props.student.recommendations.some((r: any) => r.job_id === j.id))
  dismissed.value = dismissed.value.filter(({ job }) => !props.student.recommendations.some((r: any) => r.job_id === job.id))
})
onBeforeUnmount(() => { alive = false; requestId++ })
async function generate() {
  if (!resumeId.value || !consent.value || generating.value) return
  const id = ++requestId
  generating.value = true; error.value = ''; result.value = null; dismissed.value = []
  try {
    const data = await api(`/students/${props.student.id}/ai-matched-jobs`, { method: 'POST', body: JSON.stringify({ resume_id: resumeId.value, consent: true }) })
    if (id === requestId) { result.value = data; await loadStatus() }
  } catch (e: any) { if (id === requestId) error.value = e.message }
  finally { if (id === requestId) generating.value = false }
}
function show(job: any) { selected.value = job; detailOpen.value = true }
function decline(job: any) {
  if (!result.value || !job || saving.value || generating.value) return
  const position = result.value.items.findIndex((item: any) => item.id === job.id)
  if (position < 0) return
  dismissed.value.push({ job, position })
  result.value.items.splice(position, 1)
  if (selected.value?.id === job.id) { detailOpen.value = false; selected.value = null }
}
function undoDecline() {
  if (!result.value || saving.value || generating.value) return
  const last = dismissed.value.pop()
  if (last) result.value.items.splice(last.position, 0, last.job)
}
async function recommend() {
  if (!selected.value || saving.value) return
  saving.value = true
  try {
    await api(`/students/${props.student.id}/recommendations`, { method: 'POST', body: JSON.stringify({ job_id: selected.value.id }) })
    result.value.items = result.value.items.filter((job: any) => job.id !== selected.value.id)
    detailOpen.value = false; ElMessage.success('推荐已保存，岗位快照已记录'); emit('recommended')
  } catch (e: any) { ElMessage.error(e.message) }
  finally { saving.value = false }
}
</script>

<template>
  <section class="matched-jobs ai-matched-jobs" aria-label="AI简历岗位推荐">
    <div class="section-head"><h3>AI 简历推荐 <small>DeepSeek · 最多 5 个</small></h3></div>
    <p class="hint">结合简历中的技能、项目和工作经历理解岗位职责。已保存的城市和求职意向优先；仅从有效且未推荐的岗位中生成建议，逐条确认后才保存推荐。</p>
    <el-alert v-if="setupError" :title="setupError" type="error" :closable="false" />
    <el-button v-if="setupError" @click="loadStatus">重试连接</el-button>
    <el-alert v-if="service && !service.configured" title="AI 服务尚未配置，请管理员配置 DeepSeek API Key 后启用。现有规则匹配仍可使用。" type="info" :closable="false" />
    <el-alert v-if="service?.retrieval?.ready === false" :title="service.retrieval.message || '向量检索正在准备，请稍后重试。'" type="warning" :closable="false" />
    <p v-if="service?.retrieval?.ready" class="hint">Qdrant 语义检索已就绪 · 已索引 {{ service.retrieval.indexed_jobs }} 个岗位。岗位先在本地检索，最多 40 个候选交给 DeepSeek 精读。</p>
    <el-button v-if="service?.retrieval?.ready === false" @click="loadStatus">刷新检索状态</el-button>
    <div v-if="!student.resumes.length" class="empty-inline">先上传一份简历，再使用 AI 分析推荐。</div>
    <template v-else>
      <el-form label-position="top" @submit.prevent="generate">
        <el-form-item label="选择分析的简历"><el-select v-model="resumeId" aria-label="选择分析的简历" :disabled="generating || saving"><el-option v-for="r in student.resumes" :key="r.id" :value="r.id" :label="`${r.filename} · ${time(r.created_at)}`" /></el-select></el-form-item>
        <p class="hint">本地提取文字后，会遮盖已知姓名、手机号、邮箱和证件号；其余简历文字、求职意向及候选岗位资料将发送给 DeepSeek，不上传原文件。每次生成会调用付费模型服务，结果需顾问核对。</p>
        <el-checkbox v-model="consent" :disabled="generating || saving">同意将上述内容发送给 DeepSeek 分析</el-checkbox>
        <div class="drawer-actions"><el-button type="primary" native-type="submit" :loading="generating" :disabled="!consent || !resumeId || !service?.configured || service?.retrieval?.ready === false || saving">{{ result ? '重新生成 AI 推荐' : '分析简历并推荐岗位' }}</el-button></div>
      </el-form>
      <p v-if="generating" class="hint" role="status">正在提取简历、分析经历并匹配岗位，请稍候。此次操作不会自动保存推荐记录。</p>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
    </template>
    <div v-if="result" class="ai-result">
      <ExportJobs v-if="result.items.length" :student="student" :jobs="result.items" label="导出 AI 候选岗位" />
      <p class="hint">{{ result.model }} · {{ time(result.generated_at) }} · 本次考察 {{ result.considered }} 个岗位 · 剩余 {{ result.items.length }} 个候选</p>
      <p v-if="result.retrieval" class="hint">{{ result.retrieval.engine }} 从 {{ result.retrieval.eligible_jobs }} 个符合基本条件的岗位中召回 {{ result.retrieval.retrieved_jobs }} 个；简历向量不保存。</p>
      <p class="note-text">{{ result.analysis.summary }}</p>
      <details><summary>查看简历分析依据</summary><div v-for="(fact, index) in [...result.analysis.skills, ...result.analysis.experience]" :key="index" class="timeline-card"><strong>{{ fact.value }}</strong><p class="note-text">{{ fact.evidence }}</p></div><p v-if="result.analysis.education" class="note-text">学历：{{ result.analysis.education.value }}（{{ result.analysis.education.evidence }}）</p><p v-if="result.analysis.major" class="note-text">专业：{{ result.analysis.major.value }}（{{ result.analysis.major.evidence }}）</p></details>
      <p class="note-text">{{ result.explanation }}</p>
      <ul class="match-warnings"><li v-for="(warning, index) in [...result.warnings, ...result.analysis.warnings]" :key="index">{{ warning }}</li></ul>
      <article v-for="job in result.items" :key="job.id" class="recommend-card match-card ai-card">
        <div class="split"><strong>{{ job.title }}</strong><el-button type="primary" plain :disabled="saving" @click="show(job)">核对 AI 推荐</el-button></div>
        <p>{{ job.company }} · {{ job.city }} · {{ job.education }} · {{ job.experience }}</p><span class="salary">{{ salary(job) }}</span>
        <p class="note-text">{{ job.reason }}</p>
        <p class="note-text"><b>简历依据：</b>{{ job.resume_evidence }}</p><p class="note-text"><b>岗位依据：</b>{{ job.job_evidence }}</p>
        <ul class="match-warnings"><li v-for="gap in job.gaps" :key="gap">待核对：{{ gap }}</li></ul>
        <div class="drawer-actions"><el-button text type="info" :disabled="saving || generating" @click="decline(job)">不采用</el-button></div>
      </article>
      <div v-if="dismissed.length" class="split"><p class="hint" role="status">本次已不采用 {{ dismissed.length }} 个岗位，仅从本次候选中移除；重新生成时可能再次出现。</p><el-button text type="primary" :disabled="saving || generating" @click="undoDecline">撤销上一次</el-button></div>
      <div v-if="!result.items.length" class="empty-inline">当前没有可确认的 AI 候选，可检查意向、补充岗位或更换简历后重新生成。</div>
    </div>
    <el-dialog v-model="detailOpen" title="核对 AI 推荐" width="640px" append-to-body destroy-on-close :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
      <template v-if="selected">
        <h3>{{ selected.title }}</h3><p class="note-text">{{ selected.company }} · {{ selected.city }} · {{ selected.education }} · {{ selected.experience }}</p><span class="salary">{{ salary(selected) }}</span>
        <p class="note-text">专业要求：{{ selected.major || '未填写' }}</p><p class="description-text">{{ selected.description || '暂无岗位描述' }}</p><p class="note-text">来源：{{ selected.source || '未填写' }} · 截止日期：{{ selected.expires_on || '未填写' }}</p>
        <p class="note-text">AI 理由：{{ selected.reason }}</p><p class="note-text">简历依据：{{ selected.resume_evidence }}</p><p class="note-text">岗位依据：{{ selected.job_evidence }}</p>
        <ul class="match-warnings"><li v-for="gap in selected.gaps" :key="gap">待核对：{{ gap }}</li></ul>
        <p class="recommend-target">推荐对象：<strong>{{ student.name }}</strong>（学员编号 {{ student.id }}）</p>
      </template>
      <template #footer><el-button text type="info" :disabled="saving" @click="decline(selected)">不采用</el-button><el-button :disabled="saving" @click="detailOpen = false">取消</el-button><el-button type="primary" :loading="saving" @click="recommend">确认推荐给{{ student.name }}</el-button></template>
    </el-dialog>
  </section>
</template>
