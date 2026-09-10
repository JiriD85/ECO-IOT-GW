<template>
  <div v-if="allPoints.length" class="trend-chart" role="img" :aria-label="description" :title="description">
    <div class="trend-axis" aria-hidden="true"><span>{{ axis(maximum) }}</span><span>{{ axis(minimum) }}</span></div>
    <svg class="reading-trend" viewBox="0 0 180 32" preserveAspectRatio="none" aria-hidden="true"><path d="M2 3H178M2 29H178" class="trend-grid" fill="none" stroke="currentColor" stroke-width=".5" vector-effect="non-scaling-stroke"/><path v-for="(line, index) in lines" :key="index" :d="linePath(line.points)" :data-tone="line.tone" :class="{ 'trend-stale': line.stale }" fill="none" :stroke="line.tone ? 'var(--reading-color)' : 'currentColor'" stroke-width="1.8" stroke-linecap="round" vector-effect="non-scaling-stroke" /></svg>
  </div>
</template>
<script setup>
import { computed } from 'vue'
const props = defineProps({ points: { type: Array, default: () => [] }, unit: String, gap: Number, series: Array })
const lines = computed(() => props.series || [{ points: props.points }])
const allPoints = computed(() => lines.value.flatMap(line => line.points))
const minimum = computed(() => Math.min(...allPoints.value.map(p => p[1])))
const maximum = computed(() => Math.max(...allPoints.value.map(p => p[1])))
const axis = value => value.toLocaleString(undefined, { maximumFractionDigits: Math.min(12, Math.max(1, 2 - Math.floor(Math.log10(maximum.value - minimum.value || 1)))) })
const firstTime = computed(() => Math.min(...allPoints.value.map(p => p[0])))
const lastTime = computed(() => Math.max(...allPoints.value.map(p => p[0])))
const description = computed(() => `Browser history · ${Math.max(0,Math.round((lastTime.value-firstTime.value)/60000))} min · ${axis(minimum.value)}–${axis(maximum.value)} ${props.unit || ''}${props.series ? ' · ' + props.series.map((line, i) => `${i ? 'Teal' : 'Orange'}: ${line.label || (i ? 'return' : 'flow')}`).join('; ') : ''}`)
function linePath(p) {
  if (!p.length) return ''
  const min = minimum.value, range = maximum.value - min
  const span = Math.max(1, lastTime.value - firstTime.value)
  return p.map((v,i) => `${i && v[0]-p[i-1][0] <= (props.gap || 25)*1000 ? 'L' : 'M'}${(2+(v[0]-firstTime.value)/span*176).toFixed(1)},${(range ? 29-(v[1]-min)/range*26 : 16).toFixed(1)}l0 0`).join(' ')
}
</script>
