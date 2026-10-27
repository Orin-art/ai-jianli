<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, educations } from './api'
const props = defineProps<{ modelValue: boolean; resumeId: number | null; extraction: any; student: any }>()
const emit = defineEmits(['update:modelValue', 'applied'])
const labels: Record<string, string> = { name: '姓名', phone: '电话', school: '学校', major: '专业', education: '学历' }
const rows = ref<any[]>([]), saving = ref(false)
const selectedCount = computed(() => rows.value.filter(r => r.selected).length)
watch(() => props.modelValue, open => {
  if (open) rows.value = Object.entries(labels).filter(([key]) => props.extraction?.fields?.[key]).map(([key, label]) => {
    const detected = props.extraction.fields[key]
    const current = props.student?.[key] || ''
    return { key, label, current, value: detected.value, evidence: detected.evidence, selected: !current }
  })
  else rows.value = []
})
async function apply() {
  const selected = rows.value.filter(r => r.selected)
  if (!selected.length || !props.resumeId || saving.value) return
  if (selected.some(r => !r.value?.trim())) return ElMessage.warning('请填写选中字段的值，或取消勾选该字段')
  saving.value = true
  try {
    await api(`/resumes/${props.resumeId}/apply`, { method: 'POST', body: JSON.stringify({ changes: selected.map(r => ({ field: r.key, value: r.value, expected: r.current })) }) })
    ElMessage.success(`已更新 ${selected.length} 个学员资料字段`)
    emit('applied')
    emit('update:modelValue', false)
  } catch (e: any) { ElMessage.error(e.message) } finally { saving.value = false }
}
</script>
<template>
  <el-dialog :model-value="modelValue" title="确认简历识别信息" width="790px" append-to-body destroy-on-close :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" @update:model-value="emit('update:modelValue', $event)">
    <el-alert title="简历已保存。识别结果需核对后填入，已有信息默认不勾选；勾选已有字段表示替换原值。" type="info" :closable="false" />
    <p v-if="extraction?.method === 'ocr' || extraction?.method === 'mixed'" class="hint">已使用本地 OCR 读取图片文字，请重点核对姓名、电话号码和学校名称。</p>
    <p v-for="(warning, i) in extraction?.warnings || []" :key="i" class="extraction-warning">{{ warning }}</p>
    <div v-for="row in rows" :key="row.key" class="extraction-row">
      <div class="extraction-choice"><el-checkbox v-model="row.selected" :disabled="saving" :aria-label="`填入${row.label}`">{{ row.label }}</el-checkbox><el-tag v-if="row.current && row.current !== row.value" size="small" type="warning">勾选将替换</el-tag></div>
      <div class="extraction-current"><small>当前资料</small><p>{{ row.current || '未填写' }}</p></div>
      <div class="extraction-value"><label :for="`extracted-${row.key}`">识别结果（可修改）</label><el-select v-if="row.key === 'education'" :id="`extracted-${row.key}`" v-model="row.value" :disabled="saving"><el-option v-for="e in educations" :key="e" :value="e" /></el-select><el-input v-else :id="`extracted-${row.key}`" v-model="row.value" :disabled="saving" :maxlength="row.key === 'phone' ? 40 : row.key === 'name' ? 80 : 200" /><small class="extraction-evidence">原文：{{ row.evidence }}</small></div>
    </div>
    <el-empty v-if="!rows.length" description="未识别到可填补的字段，可继续手动编辑学员资料" :image-size="80" />
    <template #footer><el-button :disabled="saving" @click="emit('update:modelValue', false)">暂不填入</el-button><el-button type="primary" :disabled="!selectedCount" :loading="saving" @click="apply">填入已选字段（{{ selectedCount }}）</el-button></template>
  </el-dialog>
</template>
