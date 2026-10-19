import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

/**
 * Home-screen view model (ticket #26).
 *
 * Every number on the home screen comes from a server read or a server frame:
 *
 * * `/api/home_stats`   online / casual queue / ranked queue / joinable rooms
 * * `/api/online_count` the header pill (same presence table, CLAUDE #17)
 * * `/api/profile`      the commander card (rank / level / record)
 * * `/api/changelog`    the announcements column
 * * `match_queued` / `match_canceled` / `error` socket frames
 *
 * The store only shapes payloads (nulls stay null, arrays are copied); it never
 * recomputes a rank, a level or a queue rule. Missing values stay `null` and the
 * screen renders an em dash instead of inventing a zero.
 */
export type JsonObject = Record<string, unknown>

export interface HomeStats {
  onlineCount: number | null
  queueCasual: number | null
  queueRanked: number | null
  lobbyRooms: number | null
}

export interface ChangelogEntry {
  /** Server date string; also the stable business id (unique by contract). */
  date: string
  items: string[]
}

export type HomeMode = 'casual' | 'ranked'

export interface HomeFetchResult {
  ok: boolean
  status: number
  body: unknown
}

function asObject(value: unknown): JsonObject | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonObject)
    : null
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function emptyStats(): HomeStats {
  return { onlineCount: null, queueCasual: null, queueRanked: null, lobbyRooms: null }
}

async function getJson(url: string): Promise<HomeFetchResult> {
  try {
    const response = await fetch(url, {
      headers: { accept: 'application/json' },
      credentials: 'same-origin',
    })
    let body: unknown = null
    try {
      body = await response.json()
    } catch {
      body = null
    }
    return { ok: response.ok, status: response.status, body }
  } catch {
    return { ok: false, status: 0, body: null }
  }
}

export const useHomeStore = defineStore('home', () => {
  const stats = ref<HomeStats>(emptyStats())
  const statsLoaded = ref(false)
  const statsFailed = ref(false)
  const onlinePill = ref<number | null>(null)
  const profile = ref<JsonObject | null>(null)
  const profileLoaded = ref(false)
  const profileFailed = ref(false)
  const changelog = ref<ChangelogEntry[]>([])
  const changelogLatest = ref('')
  const changelogLoaded = ref(false)
  const changelogFailed = ref(false)
  /** Pending matchmaking mode announced by `match_queued`. */
  const queueMode = ref<HomeMode | null>(null)
  /** A find_match/create_ai_room hand-off is being prepared (client guard). */
  const pendingAction = ref<'casual' | 'ranked' | 'ai' | null>(null)
  /** Last user-facing server refusal (`error` frame or an error ack). */
  const notice = ref('')
  /** True once a match/room hand-off is expected to move us to placement. */
  const awaitingPlacement = ref(false)
  /**
   * Monotonic counter bumped by every `game_state{placing_ships}` frame. The
   * screen watches this instead of the state value: after one match the store
   * already says placing_ships, so a value watcher would never fire again.
   */
  const placementSignal = ref(0)
  const socketConnected = ref(false)

  const queuePending = computed(() => queueMode.value !== null)
  const busy = computed(() => queuePending.value || pendingAction.value !== null)

  function applyHomeStats(payload: JsonObject | null | undefined): void {
    const data = asObject(payload)
    if (!data) {
      statsFailed.value = true
      statsLoaded.value = true
      return
    }
    const queue = asObject(data.queue)
    stats.value = {
      onlineCount: asNumber(data.online_count),
      queueCasual: asNumber(queue?.casual),
      queueRanked: asNumber(queue?.ranked),
      lobbyRooms: asNumber(data.lobby_rooms),
    }
    statsLoaded.value = true
    statsFailed.value = false
  }

  function applyOnlineCount(payload: JsonObject | null | undefined): void {
    const data = asObject(payload)
    const value = asNumber(data?.online_count)
    if (value !== null) onlinePill.value = value
  }

  function applyProfile(payload: JsonObject | null | undefined): void {
    const data = asObject(payload)
    const body = asObject(data?.profile)
    if (!body) {
      profile.value = null
      profileLoaded.value = true
      profileFailed.value = true
      return
    }
    profile.value = body
    profileLoaded.value = true
    profileFailed.value = false
  }

  function markGuest(): void {
    profile.value = null
    profileLoaded.value = true
    profileFailed.value = false
  }

  function applyChangelog(payload: JsonObject | null | undefined): void {
    const data = asObject(payload)
    if (!data) {
      changelogFailed.value = true
      changelogLoaded.value = true
      return
    }
    const rows = Array.isArray(data.entries) ? data.entries : []
    const entries: ChangelogEntry[] = []
    for (const row of rows) {
      const item = asObject(row)
      if (!item) continue
      entries.push({
        date: asString(item.date),
        items: Array.isArray(item.items) ? item.items.map(asString) : [],
      })
    }
    changelog.value = entries
    changelogLatest.value = asString(data.latest) || entries[0]?.date || ''
    changelogLoaded.value = true
    changelogFailed.value = false
  }

  function applyMatchQueued(payload: JsonObject | null | undefined): void {
    const data = asObject(payload)
    queueMode.value = data?.mode === 'ranked' ? 'ranked' : 'casual'
    pendingAction.value = null
    // A pair may be announced at any moment while we wait in the queue, so the
    // placement hand-off stays armed until we leave or cancel.
    awaitingPlacement.value = true
  }

  function applyMatchCanceled(): void {
    queueMode.value = null
    pendingAction.value = null
    awaitingPlacement.value = false
  }

  function beginAction(action: 'casual' | 'ranked' | 'ai'): void {
    pendingAction.value = action
    notice.value = ''
  }

  function endAction(): void {
    pendingAction.value = null
  }

  function expectPlacement(): void {
    awaitingPlacement.value = true
    pendingAction.value = null
    queueMode.value = null
  }

  function markPlacementFrame(): void {
    placementSignal.value += 1
  }

  function placementHandled(): void {
    awaitingPlacement.value = false
    queueMode.value = null
  }

  function notifyError(payload: JsonObject | null | undefined): void {
    const data = asObject(payload)
    const message = asString(data?.message) || asString(data?.error)
    if (message) notice.value = message
    pendingAction.value = null
  }

  function notifyMessage(message: string): void {
    if (message) notice.value = message
    pendingAction.value = null
  }

  function clearNotice(): void {
    notice.value = ''
  }

  function setSocketConnected(value: boolean): void {
    socketConnected.value = value
  }

  /** Read the read-only aggregate; both requests belong to the same panel. */
  async function loadStats(): Promise<void> {
    const [aggregate, counter] = await Promise.all([
      getJson('/api/home_stats'),
      getJson('/api/online_count'),
    ])
    if (aggregate.ok) applyHomeStats(asObject(aggregate.body))
    else applyHomeStats(null)
    if (counter.ok) applyOnlineCount(asObject(counter.body))
  }

  /** `/api/profile` answers 401 for guests; that is a state, not a failure. */
  async function loadProfile(): Promise<void> {
    const result = await getJson('/api/profile')
    if (result.status === 401) {
      markGuest()
      return
    }
    if (!result.ok) {
      profile.value = null
      profileLoaded.value = true
      profileFailed.value = true
      return
    }
    applyProfile(asObject(result.body))
  }

  async function loadChangelog(limit = 3): Promise<void> {
    const result = await getJson('/api/changelog?limit=' + limit)
    if (!result.ok) {
      applyChangelog(null)
      return
    }
    applyChangelog(asObject(result.body))
  }

  function reset(): void {
    stats.value = emptyStats()
    statsLoaded.value = false
    statsFailed.value = false
    onlinePill.value = null
    profile.value = null
    profileLoaded.value = false
    profileFailed.value = false
    changelog.value = []
    changelogLatest.value = ''
    changelogLoaded.value = false
    changelogFailed.value = false
    queueMode.value = null
    pendingAction.value = null
    notice.value = ''
    awaitingPlacement.value = false
    placementSignal.value = 0
  }

  return {
    stats,
    statsLoaded,
    statsFailed,
    onlinePill,
    profile,
    profileLoaded,
    profileFailed,
    changelog,
    changelogLatest,
    changelogLoaded,
    changelogFailed,
    queueMode,
    queuePending,
    pendingAction,
    busy,
    notice,
    awaitingPlacement,
    placementSignal,
    socketConnected,
    applyHomeStats,
    applyOnlineCount,
    applyProfile,
    markGuest,
    applyChangelog,
    applyMatchQueued,
    applyMatchCanceled,
    beginAction,
    endAction,
    expectPlacement,
    markPlacementFrame,
    placementHandled,
    notifyError,
    notifyMessage,
    clearNotice,
    setSocketConnected,
    loadStats,
    loadProfile,
    loadChangelog,
    reset,
  }
})
