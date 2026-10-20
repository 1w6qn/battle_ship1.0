import './styles/tokens.css'
import './styles/base.css'
import { createApp, type Component } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { createTestRoot, installTestHooks } from './test-hooks'

const app = createApp((__BS_TEST_HOOKS__ ? createTestRoot(App as Component) : App) as Component)
const pinia = createPinia()

app.use(pinia)
app.use(router)

app.config.errorHandler = (error, _instance, info) => {
  // Last resort: log without tearing the page down. Screen-local failures are
  // already contained by ScreenBoundary.
  console.error('[app] unhandled error', info, error)
}

// Compile-time constant: the call (and the test-hook module) disappears from
// production bundles.
if (__BS_TEST_HOOKS__) {
  installTestHooks(router, pinia)
}

app.mount('#app')
