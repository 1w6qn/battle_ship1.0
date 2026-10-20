import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

/**
 * Shell-wide UI state (ticket #42): the three themes, the reduced-motion
 * preference, the single-overlay stack and the global notice queue.
 *
 * The store is the only place that touches localStorage and <html> attributes,
 * so a theme flip reaches every screen that uses the design tokens, and the
 * overlay contract (one layer at a time, match-found above everything) is
 * enforced in one place instead of by z-index guesses in each component.
 */

export type ThemeName = 'chart' | 'journal' | 'night'
export type MotionPreference = 'auto' | 'reduced'
export type ContrastPreference = 'auto' | 'high'
export type FontScale = 'normal' | 'large' | 'xlarge'
export type AuthRequestMode = 'login' | 'register'

const THEME_KEY = 'battleship.ui.theme'
const MOTION_KEY = 'battleship.ui.motion'
const CONTRAST_KEY = 'battleship.ui.contrast'
const FONT_SCALE_KEY = 'battleship.ui.fontScale'

export const FONT_SCALE_LABELS: Record<FontScale, string> = {
  normal: '标准',
  large: '大',
  xlarge: '特大',
}

const THEMES: ThemeName[] = ['chart', 'journal', 'night']

export const THEME_LABELS: Record<ThemeName, string> = {
  chart: '航图',
  journal: '航海日志',
  night: '夜航',
}

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

function readTheme(): ThemeName {
  try {
    const raw = storage()?.getItem(THEME_KEY)
    if (raw && (THEMES as string[]).includes(raw)) return raw as ThemeName
  } catch {
    // Private mode: fall through to the default.
  }
  // No stored choice: the system colour scheme decides the first default.
  try {
    if (typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: light)').matches) {
      return 'journal'
    }
  } catch {
    // Fall through to the chart theme.
  }
  return 'chart'
}

function readMotion(): MotionPreference {
  try {
    return storage()?.getItem(MOTION_KEY) === 'reduced' ? 'reduced' : 'auto'
  } catch {
    return 'auto'
  }
}

function readContrast(): ContrastPreference {
  try {
    return storage()?.getItem(CONTRAST_KEY) === 'high' ? 'high' : 'auto'
  } catch {
    return 'auto'
  }
}

function readFontScale(): FontScale {
  try {
    const raw = storage()?.getItem(FONT_SCALE_KEY)
    if (raw === 'large' || raw === 'xlarge') return raw
  } catch {
    // Private mode: fall through to the default.
  }
  return 'normal'
}

/** Apply every persisted appearance preference before the app mounts (main.ts). */
export function applyStoredTheme(): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.dataset.theme = readTheme()
  if (readMotion() === 'reduced') root.dataset.motion = 'reduced'
  else delete root.dataset.motion
  if (readContrast() === 'high') root.dataset.contrast = 'high'
  else delete root.dataset.contrast
  const scale = readFontScale()
  if (scale !== 'normal') root.dataset.fontScale = scale
  else delete root.dataset.fontScale
}

export interface NoticeInput {
  /** Stable code used for the 3-second dedupe and for the error mapping. */
  code: string
  message?: string
  tone?: 'info' | 'success' | 'warning' | 'error'
  /** What the player can do next; shown under the message for failures. */
  next?: string
  /** Milliseconds before the notice leaves the queue. */
  ttl?: number
}

export interface Notice {
  id: number
  code: string
  message: string
  next: string
  tone: 'info' | 'success' | 'warning' | 'error'
  createdAt: number
}

/**
 * Error codes the backend already returns (error frames / ack payloads) mapped
 * to player language. A missing code falls back to the server text, never to a
 * raw technical string. The table grows as later tickets surface more codes.
 */
const ERROR_LANGUAGE: Record<string, { message: string; next?: string }> = {
  not_logged_in: { message: '需要先登录才能继续。', next: '从右上角头像菜单登录。' },
  already_queued: { message: '你已经在匹配队列里了。', next: '等待匹配，或先取消排队。' },
  not_in_queue: { message: '当前没有在排队。', next: '从首页或大厅重新开始匹配。' },
  room_not_found: { message: '房间已经不存在了。', next: '回到大厅看看其他房间。' },
  room_full: { message: '这个房间已经坐满了。', next: '换一桌，或自己开一间。' },
  server_busy: { message: '服务器正忙，刚才的操作没有完成。', next: '稍等几秒再试一次。' },
  network_error: { message: '网络不稳定，操作没有送达。', next: '检查网络后重试。' },
}

export function errorLanguage(code: string, fallback = ''): { message: string; next: string } {
  const mapped = ERROR_LANGUAGE[code]
  if (mapped) return { message: mapped.message, next: mapped.next || '' }
  return { message: fallback || '操作没有成功。', next: fallback ? '' : '稍后重试，或刷新页面。' }
}

interface DialogEntry {
  id: string
  priority: number
}

export const useUiStore = defineStore('ui', () => {
  // ------------------------------------------------------------- theme ----
  const theme = ref<ThemeName>(readTheme())
  const motion = ref<MotionPreference>(readMotion())
  const contrast = ref<ContrastPreference>(readContrast())
  const fontScale = ref<FontScale>(readFontScale())

  function setTheme(next: ThemeName): void {
    theme.value = THEMES.includes(next) ? next : 'chart'
    if (typeof document !== 'undefined') document.documentElement.dataset.theme = theme.value
    try {
      storage()?.setItem(THEME_KEY, theme.value)
    } catch {
      // Preferences are best effort; the theme still applies for this session.
    }
  }

  function setMotion(next: MotionPreference): void {
    motion.value = next === 'reduced' ? 'reduced' : 'auto'
    if (typeof document !== 'undefined') {
      if (motion.value === 'reduced') document.documentElement.dataset.motion = 'reduced'
      else delete document.documentElement.dataset.motion
    }
    try {
      storage()?.setItem(MOTION_KEY, motion.value)
    } catch {
      // Best effort, same as the theme.
    }
  }

  function setContrast(next: ContrastPreference): void {
    contrast.value = next === 'high' ? 'high' : 'auto'
    if (typeof document !== 'undefined') {
      if (contrast.value === 'high') document.documentElement.dataset.contrast = 'high'
      else delete document.documentElement.dataset.contrast
    }
    try {
      storage()?.setItem(CONTRAST_KEY, contrast.value)
    } catch {
      // Best effort, same as the theme.
    }
  }

  function setFontScale(next: FontScale): void {
    fontScale.value = next === 'large' || next === 'xlarge' ? next : 'normal'
    if (typeof document !== 'undefined') {
      if (fontScale.value !== 'normal') document.documentElement.dataset.fontScale = fontScale.value
      else delete document.documentElement.dataset.fontScale
    }
    try {
      storage()?.setItem(FONT_SCALE_KEY, fontScale.value)
    } catch {
      // Best effort, same as the theme.
    }
  }

  /**
   * Ask for the app-level login overlay (ticket #44 listens for the window
   * event). Screens use this instead of linking to the dead /login route.
   */
  function requestLogin(mode: AuthRequestMode = 'login', reason = ''): void {
    if (typeof window === 'undefined') return
    window.dispatchEvent(new CustomEvent('bs:auth-required', { detail: { mode, reason } }))
  }

  // ----------------------------------------------------------- overlays ----
  // Exactly one dialog is open. A new dialog may only replace one of a strictly
  // lower priority, so the match-found result can never be covered by the card
  // archive opened during matchmaking.
  const activeDialog = ref<DialogEntry | null>(null)
  const closeHandlers = new Map<string, () => void>()

  function registerDialogClose(id: string, close: () => void): void {
    closeHandlers.set(id, close)
  }

  function unregisterDialogClose(id: string): void {
    closeHandlers.delete(id)
  }

  function claimDialog(id: string, priority: number): boolean {
    const current = activeDialog.value
    if (!current) {
      activeDialog.value = { id, priority }
      return true
    }
    if (current.id === id) {
      current.priority = priority
      return true
    }
    if (priority <= current.priority) return false
    closeHandlers.get(current.id)?.()
    activeDialog.value = { id, priority }
    return true
  }

  function releaseDialog(id: string): void {
    if (activeDialog.value?.id === id) activeDialog.value = null
  }

  /** Route switches close every overlay: nothing stacks on the next screen. */
  function closeAllDialogs(): void {
    const ids = [...closeHandlers.keys()]
    for (const id of ids) closeHandlers.get(id)?.()
    activeDialog.value = null
  }

  /** Exit confirmation for the immersive match screens. */
  const exitConfirmOpen = ref(false)
  function requestExit(): void {
    exitConfirmOpen.value = true
  }
  function cancelExit(): void {
    exitConfirmOpen.value = false
  }

  // ------------------------------------------------------------ notices ----
  const notices = ref<Notice[]>([])
  const lastByCode = new Map<string, number>()
  let noticeId = 0
  const timers = new Map<number, ReturnType<typeof setTimeout>>()

  function dismissNotice(id: number): void {
    notices.value = notices.value.filter((item) => item.id !== id)
    const timer = timers.get(id)
    if (timer) timers.delete(id)
    clearTimeout(timer)
  }

  function notify(input: NoticeInput): void {
    const now = Date.now()
    const dedupeWindow = 3000
    const last = lastByCode.get(input.code)
    if (last !== undefined && now - last < dedupeWindow) return
    lastByCode.set(input.code, now)

    const tone = input.tone || (input.code.startsWith('error') ? 'error' : 'info')
    const notice: Notice = {
      id: ++noticeId,
      code: input.code,
      message: input.message || input.code,
      next: input.next || '',
      tone,
      createdAt: now,
    }
    notices.value = [...notices.value.slice(-2), notice]
    noticeId += 0
    timers.set(notice.id, setTimeout(() => dismissNotice(notice.id), input.ttl ?? 4000))
  }

  function notifyError(code: string, fallback = ''): void {
    const language = errorLanguage(code, fallback)
    notify({ code, message: language.message, next: language.next, tone: 'error', ttl: 6000 })
  }

  function clearNotices(): void {
    for (const timer of timers.values()) clearTimeout(timer)
    timers.clear()
    notices.value = []
    lastByCode.clear()
  }

  const hasNotices = computed(() => notices.value.length > 0)

  return {
    theme,
    motion,
    contrast,
    fontScale,
    setTheme,
    setMotion,
    setContrast,
    setFontScale,
    requestLogin,
    activeDialog,
    claimDialog,
    releaseDialog,
    registerDialogClose,
    unregisterDialogClose,
    closeAllDialogs,
    exitConfirmOpen,
    requestExit,
    cancelExit,
    notices,
    hasNotices,
    notify,
    notifyError,
    dismissNotice,
    clearNotices,
  }
})
