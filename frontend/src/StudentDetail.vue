<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, download, salary, stages, time } from './api'
import ResumeExtraction from './ResumeExtraction.vue'
import MatchedJobs from './MatchedJobs.vue'
import AiMatchedJobs from './AiMatchedJobs.vue'
const props = defineProps<{ studentId: number | null }>()
const emit = defineEmits(['edit', 'changed', 'browse-jobs'])
const student = ref<any>(null), loading = ref(false), busy = ref(false)
const identifying = ref(false), ocrStatus = ref<any>(null)
const extractionOpen = ref(false), extraction = ref<any>(null), extractionResume = ref<number | null>(null)
const form = ref<any>({ recommendation_id: null, stage: '沟通', content: '', next_date: null })
async function load() {
  if (!props.studentId) return
  loading.value = true
  if (student.value?.id !== props.studentId) student.value = null
  try {
    const [profile, ocr] = await Promise.all([api(`/students/${props.studentId}`), api('/ocr/status').catch(() => null)])
    student.value = profile; ocrStatus.value = ocr
  } catch (e: any) { ElMessage.error(e.message) } finally { loading.value = false }
}
watch(() => props.studentId, load, { immediate: true })
async function upload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]; if (!file) return
  if (file.size > 5 * 1024 * 1024) { ElMessage.error('简历不能超过 5MB'); input.value = ''; return }
  busy.value = true
  identifying.value = true
  try {
    const data = new FormData(); data.append('file', file)
    const resume = await api(`/students/${props.studentId}/resumes`, { method: 'POST', body: data })
    ElMessage.success('简历已上传并保留历史版本'); await load()
    if (student.value) { extractionResume.value = resume.id; extraction.value = resume.extraction; extractionOpen.value = true }
  } catch (e: any) { ElMessage.error(e.message) } finally { busy.value = false; identifying.value = false; input.value = '' }
}
async function saveFollowup() {
  if (!form.value.content.trim()) return ElMessage.warning('请填写跟进内容')
  busy.value = true
  try {
    await api(`/students/${props.studentId}/followups`, { method: 'POST', body: JSON.stringify(form.value) })
    form.value = { recommendation_id: null, stage: '沟通', content: '', next_date: null }
    ElMessage.success('跟进已记录'); await load(); emit('changed')
  } catch (e: any) { ElMessage.error(e.message) } finally { busy.value = false }
}
async function getResume(r: any) { try { await download(`/resumes/${r.id}/download`, r.filename) } catch (e: any) { ElMessage.error(e.message) } }
async function cancelRecommendation(r: any) {
  if (busy.value) return
  busy.value = true
  try {
    const confirmed = await ElMessageBox.confirm(
      `确定取消推荐「${r.snapshot.title} · ${r.snapshot.company}」吗？取消后将从推荐列表移除，已有跟进内容和提醒日期保留。该岗位之后可以重新推荐。`,
      '取消岗位推荐', { confirmButtonText: '确认取消推荐', cancelButtonText: '保留推荐', type: 'warning' },
    ).then(() => true).catch(() => false)
    if (!confirmed) return
    await api(`/students/${props.studentId}/recommendations/${r.id}`, { method: 'DELETE' })
    if (form.value.recommendation_id === r.id) { form.value.recommendation_id = null; form.value.stage = '沟通' }
    ElMessage.success('已取消推荐，跟进记录已保留')
    await load(); emit('changed')
  } catch (e: any) { ElMessage.error(e.message) } finally { busy.value = false }
}
async function deleteResume(r: any) {
  if (busy.value) return
  const confirmed = await ElMessageBox.confirm(
    `确定删除「${r.filename}」及其识别缓存吗？删除后无法从工作台恢复，已填入的学员资料和推荐、跟进记录会保留。`,
    '删除简历', { confirmButtonText: '确认删除', cancelButtonText: '保留简历', type: 'warning' },
  ).then(() => true).catch(() => false)
  if (!confirmed) return
  busy.value = true
  try {
    await api(`/resumes/${r.id}`, { method: 'DELETE' })
    if (extractionResume.value === r.id) { extractionOpen.value = false; extraction.value = null; extractionResume.value = null }
    ElMessage.success('简历及识别缓存已删除')
    await load()
  } catch (e: any) { ElMessage.error(e.message) } finally { busy.value = false }
}
async function identifyResume(r: any) {
  busy.value = true
  identifying.value = true
  try {
    const result = await api(`/resumes/${r.id}/extraction`)
    await load()
    if (student.value) { extractionResume.value = r.id; extraction.value = result; extractionOpen.value = true }
  } catch (e: any) { ElMessage.error(e.message) } finally { busy.value = false; identifying.value = false }
}
async function profileApplied() { await load(); emit('changed') }
</script>
<template>
  <div v-loading="loading" class="student-detail">
    <template v-if="student">
      <div class="detail-hero"><div class="avatar large">{{ student.name.slice(0, 1) }}</div><div><h2>{{ student.name }}</h2><p>{{ student.education }} · {{ student.major || '专业未填写' }}</p></div><el-button class="push-right" @click="emit('edit', student)">编辑资料</el-button></div>
      <div class="info-grid"><div><label>学校</label><p>{{ student.school || '未填写' }}</p></div><div><label>专业</label><p>{{ student.major || '未填写' }}</p></div><div><label>联系电话</label><p>{{ student.phone || '未填写' }}</p></div><div><label>意向城市</label><p>{{ student.target_city || '未填写' }}</p></div><div><label>意向岗位</label><p>{{ student.target_role || '未填写' }}</p></div><div><label>服务状态</label><p>{{ student.status }}</p></div></div>
      <p v-if="student.notes" class="note-text">{{ student.notes }}</p>
      <AiMatchedJobs :student="student" @recommended="profileApplied" />
      <MatchedJobs :student="student" @recommended="profileApplied" />
      <div class="section-head"><h3>简历档案 <small>{{ student.resumes.length }} 个版本</small></h3><label class="file-button" :class="{ disabled: busy }">{{ identifying ? "正在识别…" : "上传简历" }}<input aria-label="上传简历" :disabled="busy" type="file" accept=".pdf,.docx,.jpg,.jpeg,.png" @change="upload"></label></div>
      <p class="hint">PDF / DOCX / JPG / PNG，每份不超过 5MB。扫描 PDF 最多识别 5 页；识别后请核对确认。</p>
      <p v-if="identifying" class="hint" role="status">正在本地识别简历，首次加载模型可能较慢，请稍候。</p><p v-else-if="ocrStatus && !ocrStatus.available" class="extraction-warning">当前后端 OCR 尚未就绪，文字简历可正常解析；扫描件与图片可先保存。</p>
      <div v-for="r in student.resumes" :key="r.id" class="file-row"><div><strong>{{ r.filename }}</strong><small>{{ time(r.created_at) }}</small></div><div class="file-actions"><el-button text type="primary" :disabled="busy" @click="identifyResume(r)">识别信息</el-button><el-button text type="primary" @click="getResume(r)">下载</el-button><el-button text type="danger" :disabled="busy" @click="deleteResume(r)">删除</el-button></div></div>
      <div v-if="!student.resumes.length" class="empty-inline">尚未上传简历</div>
      <div class="section-head"><h3>岗位推荐 <small>{{ student.recommendations.length }} 条</small></h3><el-button type="primary" plain @click="emit('browse-jobs', student)">去共享岗位库推荐</el-button></div>
      <p class="hint">下列信息为推荐时的岗位快照。</p>
      <div v-for="r in student.recommendations" :key="r.id" class="recommend-card"><div class="split"><strong>{{ r.snapshot.title }}</strong><el-tag :type="r.stage === '已录用' ? 'success' : 'info'">{{ r.stage }}</el-tag></div><p>{{ r.snapshot.company }} · {{ r.snapshot.city }}</p><span class="salary">{{ salary(r.snapshot) }}</span><small>{{ time(r.created_at) }}</small><div class="drawer-actions"><el-button text type="danger" :disabled="busy" @click="cancelRecommendation(r)">取消推荐</el-button></div></div>
      <div v-if="!student.recommendations.length" class="empty-inline">还没有岗位推荐，从共享岗位库选择一个合适的机会。</div>
      <div class="section-head"><h3>记录跟进</h3></div>
      <el-form label-position="top" @submit.prevent="saveFollowup">
        <div class="form-grid"><el-form-item label="关联推荐"><el-select v-model="form.recommendation_id" clearable placeholder="普通沟通（不关联岗位）" @change="form.stage = form.recommendation_id ? '已推荐' : '沟通'"><el-option v-for="r in student.recommendations" :key="r.id" :value="r.id" :label="`${r.snapshot.title} · ${r.snapshot.company}`" /></el-select></el-form-item><el-form-item label="进展状态"><el-select v-model="form.stage"><el-option v-for="s in form.recommendation_id ? stages : ['沟通']" :key="s" :value="s" :label="s" /></el-select></el-form-item></div>
        <el-form-item label="跟进内容" required><el-input v-model="form.content" type="textarea" :rows="3" maxlength="5000" placeholder="记录沟通结果、学员反馈或下一步安排" /></el-form-item>
        <div class="split"><el-form-item label="下一次跟进日期"><el-date-picker v-model="form.next_date" type="date" value-format="YYYY-MM-DD" placeholder="不设置提醒" /></el-form-item><el-button type="primary" native-type="submit" :loading="busy">保存跟进</el-button></div>
      </el-form>
      <div class="section-head"><h3>跟进时间线</h3></div>
      <el-timeline v-if="student.followups.length"><el-timeline-item v-for="f in student.followups" :key="f.id" :timestamp="time(f.created_at)" placement="top"><div class="timeline-card"><el-tag size="small" type="info">{{ f.stage }}</el-tag><p class="note-text">{{ f.content }}</p><small v-if="f.next_date">下一次跟进：{{ f.next_date }}</small></div></el-timeline-item></el-timeline>
      <div v-else class="empty-inline">暂无跟进记录</div>
    </template>
    <ResumeExtraction v-model="extractionOpen" :resume-id="extractionResume" :extraction="extraction" :student="student" @applied="profileApplied" />
  </div>
</template>
