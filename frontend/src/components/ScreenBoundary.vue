<script setup lang="ts">
import { onErrorCaptured, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

/**
 * Per-screen error boundary (spec story 44 / ticket #21).
 *
 * A render/setup error in one screen is caught here instead of escaping to the
 * app root, so the shell (nav, boundary fallback, other routes) stays usable.
 * The next navigation clears the error and tries the new screen normally.
 */
const route = useRoute()
const error = ref<Error | null>(null)

onErrorCaptured((caught) => {
  error.value = caught instanceof Error ? caught : new Error(String(caught))
  console.error('[screen-boundary]', caught)
  // Stop propagation: the app-level error handler should not treat this as a
  // fatal shell failure.
  return false
})

watch(
  () => route.fullPath,
  () => {
    error.value = null
  },
)

function retry(): void {
  error.value = null
}
</script>

<template>
  <div class="screen-boundary" data-testid="app-screen-boundary">
    <div v-if="error" class="screen-error" data-testid="app-screen-error" role="alert">
      <h2 class="screen-error__title">这一屏加载失败了</h2>
      <p class="screen-error__hint">其他界面仍可正常使用，可以重试或切换到别的屏。</p>
      <button type="button" class="button" data-testid="app-screen-error-retry" @click="retry">
        重试
      </button>
    </div>
    <slot v-else />
  </div>
</template>
