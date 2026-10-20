<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import MatchFoundOverlay from '../../components/MatchFoundOverlay.vue'
import StateSurface from '../../components/StateSurface.vue'
import { useAuthStore } from '../../stores/auth'
import { useCollectionStore } from '../../stores/collection'
import { useGameStore } from '../../stores/game'
import { useHomeStore } from '../../stores/home'
import { useUiStore } from '../../stores/ui'
import { AI_DIFFICULTY_KEY, aiDifficulty } from '../game-over/view'
import {
  acquireHomeChannel,
  createAiRoom,
  emitCancelMatch,
  emitFindMatch,
  homeSocket,
} from '../../realtime/home'
import {
  changelogKey,
  DIFFICULTY_OPTIONS,
  numberText,
  playerView,
  queueStatusText,
  statsText,
  waitedSeconds,
} from './view'

/**
 * Ticket #26: the three-column home screen.
 *
 * Reads only the home store; every value there either came from an HTTP read
 * (/api/home_stats, /api/online_count, /api/profile, /api/changelog) or from a
 * server socket frame (match_queued / match_canceled / error). The screen
 * formats those values and never recomputes a rank, level or queue rule.
 *
 * The seat is created here (find_match / create_ai_room), so the screen acquires
 * the shared socket with keepAlive: the route change to /placement must not
 * disconnect the connection the seat is bound to.
 */
const router = useRouter()
const auth = useAuthStore()
const home = useHomeStore()
const game = useGameStore()
const collection = useCollectionStore()
const ui = useUiStore()

const difficulty = ref<string>(aiDifficulty())
const difficultyOptions = DIFFICULTY_OPTIONS
let releaseChannel: (() => void) | null = null
let navigating = false
let waitTimer: number | null = null
/** Ticking queue wait, derived from the store's server-confirmed entry time. */
const queueSeconds = ref(0)

function tickQueue(): void {
  queueSeconds.value = waitedSeconds(home.queueStartedAt, Date.now())
}

function stopQueueTicker(): void {
  if (waitTimer !== null) {
    window.clearInterval(waitTimer)
    waitTimer = null
  }
}

watch(
  () => home.queuePending,
  (pending) => {
    if (pending) {
      tickQueue()
      if (waitTimer === null) waitTimer = window.setInterval(tickQueue, 1000)
      return
    }
    stopQueueTicker()
    queueSeconds.value = 0
  },
  { immediate: true },
)

onMounted(() => {
  releaseChannel = acquireHomeChannel(undefined, {
    onConnect: () => {
      // The online counter includes this very connection once it is up, so the
      // boot snapshot is not enough: refetch the authoritative counters.
      void home.loadStats(true)
    },
  })
  void home.loadStats()
  void home.loadProfile()
  void home.loadChangelog()
  maybeAdvance()
})

onBeforeUnmount(() => {
  releaseChannel?.()
  releaseChannel = null
  stopQueueTicker()
})

const player = computed(() => playerView(home.profile))
/** Identity and profile are separate reads; the guest card follows the session. */
/**
 * One name for the whole session (ticket #44): a logged-in account shows its
 * username, a guest shows the persisted 舰长1234. The same computed is what
 * find_match and create_ai_room submit, so the screen never promises a name the
 * server did not receive (spec story 9).
 */
const playerName = computed(() => (auth.isGuest ? auth.guestName : auth.displayName))
const stats = computed(() => statsText(home.stats))
const queueText = computed(() => queueStatusText(home.queueMode))
const pillText = computed(() => numberText(home.onlinePill))
const latestText = computed(() => {
  return home.changelogLatest
})
const entries = computed(() =>
  home.changelog.map((entry) => ({ ...entry, key: changelogKey(entry) })),
)
/** Async regions share the one StateSurface contract (ticket #42, story 57/90). */
const statsState = computed<'loading' | 'ready' | 'empty' | 'error'>(() => {
  if (home.statsFailed) return 'error'
  if (!home.statsLoaded) return 'loading'
  const counters = home.stats
  const allMissing = [counters.onlineCount, counters.queueCasual, counters.queueRanked, counters.lobbyRooms]
    .every((value) => value === null)
  return allMissing ? 'empty' : 'ready'
})

const profileState = computed<'loading' | 'ready' | 'error'>(() => {
  if (auth.isGuest) return 'ready'
  if (home.profileFailed) return 'error'
  return home.profileLoaded ? 'ready' : 'loading'
})

/** Ranked entry: the current tier and the "this changes rank" warning (story 16). */
const rankedDesc = computed(() => {
  if (auth.isGuest) return '登录后显示段位 · 结算会改变段位'
  return player.value.rankLabel
    ? '当前段位：' + player.value.rankLabel + ' · 结算会改变段位'
    : '结算会改变段位'
})

/** Loading / empty / error / ready for the announcement panel (ticket #42). */
const changelogState = computed<'loading' | 'ready' | 'empty' | 'error'>(() => {
  if (home.changelogFailed) return 'error'
  if (!home.changelogLoaded) return 'loading'
  return entries.value.length ? 'ready' : 'empty'
})

// The screen still renders its own notice line; the shell toast makes the same
// result visible from anywhere (one queue, same wording).
watch(
  () => home.notice,
  (message) => {
    if (message) ui.notify({ code: 'home-notice', tone: 'error', message })
  },
)
const actionsDisabled = computed(() => home.busy || home.awaitingPlacement)

/**
 * Hand-off to placement. A real matchmaking pair first shows the 匹配成功
 * overlay (five-second countdown, legacy screen) and navigates when it emits
 * done; AI/custom rooms have no matchFound entry and advance immediately.
 */
function advanceToPlacement(): void {
  if (navigating) return
  navigating = true
  home.placementHandled()
  home.clearMatchFound()
  void router.push({ name: 'placement' })
}

function onMatchFoundDone(): void {
  if (home.awaitingPlacement) advanceToPlacement()
}

function maybeAdvance(): void {
  if (navigating || !home.awaitingPlacement) return
  if (game.state.state !== 'placing_ships') return
  if (home.matchFound) return
  advanceToPlacement()
}

watch(() => game.state.state, maybeAdvance)
// A second match starts from an already-placing_ships store, so the state
// watcher alone would never fire: each placing frame ticks this counter.
watch(() => home.placementSignal, maybeAdvance)

function currentSocket() {
  const socket = homeSocket()
  if (!socket) {
    home.notifyMessage('实时连接还没就绪，请稍后再试')
    return null
  }
  return socket
}

async function startMatch(mode: 'casual' | 'ranked'): Promise<void> {
  // A guest cannot rank (server refuses it); open the login overlay instead of
  // spending the click on a refusal the player cannot act on (spec story 31).
  if (mode === 'ranked' && auth.isGuest) {
    home.notifyMessage('排位对战需要先登录')
    auth.open('login', '排位对战需要先登录，登录后会回到这里继续。')
    return
  }
  const socket = currentSocket()
  if (!socket) return
  home.clearNotice()
  home.beginAction(mode)
  try {
    const ack = await emitFindMatch(socket, playerName.value, mode)
    if (ack.status === 'error') home.notifyMessage(ack.message || '匹配请求被拒绝')
  } catch {
    home.notifyMessage('网络不稳定，请再试一次')
  } finally {
    home.endAction()
  }
}

async function cancelQueue(): Promise<void> {
  home.clearNotice()
  try {
    const socket = currentSocket()
    if (!socket) return
    const ack = await emitCancelMatch(socket)
    home.applyMatchCanceled()
    ui.notify({
      code: 'match-canceled',
      tone: ack.status === 'success' ? 'info' : 'warning',
      message: ack.status === 'success' ? '已取消匹配' : ack.message || '取消匹配没有送达',
      next: ack.status === 'success' ? '' : '检查网络后再试一次。',
    })
  } catch {
    home.notifyMessage('取消匹配失败，请再试一次')
  }
}

async function startAi(): Promise<void> {
  const socket = currentSocket()
  if (!socket) return
  home.clearNotice()
  // #48 reads this back for "再来一局" of an AI match; persist before the seat
  // is created so a failed request still remembers the choice (issue #45).
  try {
    window.localStorage.setItem(AI_DIFFICULTY_KEY, difficulty.value)
  } catch {
    // Private mode: the launch still works with the in-memory choice.
  }
  home.beginAction('ai')
  try {
    const result = await createAiRoom(socket, playerName.value, difficulty.value)
    if (!result.ok) {
      home.notifyMessage(result.message || '人机对战暂时不可用')
      return
    }
    home.expectPlacement()
    maybeAdvance()
  } catch {
    home.notifyMessage('网络不稳定，请再试一次')
  } finally {
    home.endAction()
  }
}
</script>

<template>
  <MatchFoundOverlay
    v-if="home.matchFound"
    :self-name="home.matchFound.playerName"
    :opponent-name="home.matchFound.opponentName"
    :mode="home.matchFound.mode"
    @done="onMatchFoundDone"
  />

  <section
    class="screen home-screen"
    data-screen="start"
    data-testid="screen-start"
    aria-labelledby="screen-start-title"
  >
    <header class="home-head">
      <div class="home-head__main">
        <p class="home-head__eyebrow">P4 · 出 海 指 挥 台</p>
        <h1 id="screen-start-title" class="home-head__title" data-testid="start-heading">首页</h1>
      </div>
      <div class="home-head__meta">
        <span class="home-pill" title="在线玩家（/api/online_count）">
          <span class="home-pill__label">在线</span>
          <b class="home-pill__value" data-testid="start-online-pill">{{ pillText }}</b>
          <span class="home-pill__unit">人</span>
        </span>
        <span
          class="home-conn"
          data-testid="start-connection-status"
          :data-connected="home.socketConnected ? 'true' : 'false'"
          role="status"
        >
          {{ home.socketConnected ? '实时连接已就绪' : '正在连接实时服务…' }}
        </span>
      </div>
    </header>

    <div class="home-grid">
      <!-- 主行动入口：DOM 第一位，窄屏收成单列时“先能开一局”。 -->
      <section class="home-panel home-actions" data-testid="start-actions" aria-labelledby="home-actions-title">
        <div class="home-actions__meta">
          <h2 id="home-actions-title" class="home-panel__title">开 一 局</h2>
          <p class="home-actions__lead">休闲与排位共用一个匹配队列；人机随时开局，不结算段位分。</p>
        </div>

        <button
          type="button"
          class="home-action home-action--primary"
          data-testid="start-primary-action"
          data-primary-action
          :disabled="actionsDisabled"
          @click="startMatch('casual')"
        >
          <span class="home-action__title">开始休闲匹配</span>
          <span class="home-action__desc">随机匹配一位在线玩家 · 不计段位分</span>
        </button>

        <div v-if="home.queuePending" class="home-queue" role="status">
          <p class="home-queue__text" data-testid="start-queue-status">
            {{ queueText }} · 已等待 <b data-testid="start-queue-waited">{{ queueSeconds }}</b> 秒
          </p>
          <button type="button" class="button home-queue__cancel" data-testid="start-queue-cancel" @click="cancelQueue">
            取消匹配
          </button>
        </div>

        <button
          type="button"
          class="home-action"
          data-testid="start-ranked-action"
          :disabled="actionsDisabled"
          @click="startMatch('ranked')"
        >
          <span class="home-action__title">开始排位对战</span>
          <span class="home-action__desc" data-testid="start-ranked-desc">{{ rankedDesc }}</span>
        </button>

        <div class="home-ai" data-testid="start-ai-difficulty" role="radiogroup" aria-label="电脑难度">
          <div class="home-ai__caps">
            <button
              v-for="option in difficultyOptions"
              :key="option.value"
              type="button"
              role="radio"
              class="home-ai__cap"
              :class="{ 'is-active': difficulty === option.value }"
              :aria-checked="difficulty === option.value"
              :title="option.hint"
              :data-testid="'start-ai-difficulty-' + option.value"
              :disabled="actionsDisabled"
              @click="difficulty = option.value"
            >
              <b>{{ option.label }}</b>
              <small>{{ option.hint }}</small>
            </button>
          </div>
          <button
            type="button"
            class="home-action home-ai__action"
            data-testid="start-ai-action"
            :disabled="actionsDisabled"
            @click="startAi"
          >
            <span class="home-action__title">开始人机对战</span>
            <span class="home-action__desc">当前难度：{{ difficultyOptions.find((o) => o.value === difficulty)?.label }}</span>
          </button>
        </div>

        <p v-if="home.notice" class="home-notice" role="alert" data-testid="start-notice">
          {{ home.notice }}
        </p>

        <nav class="home-links" aria-label="更多入口">
          <router-link class="home-link" :to="{ name: 'lobby' }" data-testid="start-lobby-link">游戏大厅</router-link>
          <router-link class="home-link" :to="{ name: 'leaderboard' }" data-testid="start-leaderboard-link">排行榜</router-link>
          <router-link class="home-link" :to="{ name: 'settings' }" data-testid="start-settings-link">设置</router-link>
          <button type="button" class="home-link home-link--button" data-testid="start-collection-link" @click="collection.open()">
            图鉴 / 卡库
          </button>
        </nav>
      </section>

      <!-- 玩家信息：/api/profile 的服务端字段，前端只排版。 -->
      <aside class="home-panel home-player" data-testid="start-player" aria-labelledby="home-player-title">
        <h2 id="home-player-title" class="home-panel__title">指 挥 官</h2>
        <div class="home-player__emblem" aria-hidden="true"><span>舰</span></div>
        <p class="home-player__name" data-testid="start-player-name">{{ playerName }}</p>

        <template v-if="auth.isGuest">
          <p v-if="home.profileFailed" class="home-player__note" data-testid="start-player-error">
            名片暂时取不到，刷新后再试。
          </p>
          <p v-else-if="home.profileLoaded" class="home-player__note" data-testid="start-player-guest">
            游客状态：登录后显示段位、等级与战绩。
          </p>
          <p v-else class="home-player__note" data-testid="start-player-loading">正在读取名片…</p>
          <div class="home-player__links">
            <button
              type="button"
              class="home-link home-link--button"
              data-testid="start-login-link"
              @click="auth.open('login')"
            >
              去登录
            </button>
            <router-link class="home-link" :to="{ name: 'profile' }" data-testid="start-profile-link">查看名片</router-link>
          </div>
        </template>

        <StateSurface
          v-else
          data-testid="start-profile-surface"
          :state="profileState"
          loading-text="名片载入中…"
          error-text="名片暂时取不到。"
          @retry="home.loadProfile()"
        >
          <p v-if="player.rankLabel" class="home-player__rank" data-testid="start-player-rank">{{ player.rankLabel }}</p>
          <div class="home-bar" role="img" :aria-label="'段位进度 ' + player.rankFill + '%'">
            <div class="home-bar__fill" data-testid="start-player-rank-fill" :style="{ width: player.rankFill + '%' }"></div>
          </div>
          <div class="home-player__level">
            <span class="home-player__level-label" data-testid="start-player-level">{{ player.level }}</span>
            <span class="home-player__level-text" data-testid="start-player-level-text">{{ player.levelText }}</span>
          </div>
          <div class="home-bar" role="img" :aria-label="'等级经验 ' + player.levelFill + '%'">
            <div class="home-bar__fill home-bar__fill--xp" data-testid="start-player-level-fill" :style="{ width: player.levelFill + '%' }"></div>
          </div>
          <dl class="home-player__kv">
            <div class="home-player__kv-row">
              <dt>战绩</dt>
              <dd data-testid="start-player-record">{{ player.record || '暂无' }}</dd>
            </div>
            <div class="home-player__kv-row">
              <dt>胜率</dt>
              <dd data-testid="start-player-winrate">{{ player.winRate || '暂无' }}</dd>
            </div>
            <div class="home-player__kv-row">
              <dt>最长连胜</dt>
              <dd data-testid="start-player-streak">{{ player.streak || '暂无' }}</dd>
            </div>
          </dl>
          <router-link class="home-link" :to="{ name: 'profile' }" data-testid="start-profile-link">查看我的名片</router-link>
        </StateSurface>
      </aside>

      <!-- 在线与公告。 -->
      <aside class="home-side">
        <section class="home-panel" data-testid="start-online" aria-labelledby="home-online-title">
          <h2 id="home-online-title" class="home-panel__title">在 线</h2>
          <StateSurface
            data-testid="start-stats-surface"
            :state="statsState"
            loading-text="在线数据载入中…"
            empty-text="暂无在线数据"
            error-text="在线数据暂时取不到。"
            @retry="home.loadStats(true)"
          >
            <dl class="home-stats">
              <div class="home-stat home-stat--wide">
                <dt>在线玩家</dt>
                <dd><b data-testid="start-online-count">{{ stats.online }}</b><span class="home-stat__unit">人</span></dd>
              </div>
              <div class="home-stat">
                <dt>休闲队列</dt>
                <dd><b data-testid="start-queue-casual">{{ stats.casual }}</b><span class="home-stat__unit">人</span></dd>
              </div>
              <div class="home-stat">
                <dt>排位队列</dt>
                <dd><b data-testid="start-queue-ranked">{{ stats.ranked }}</b><span class="home-stat__unit">人</span></dd>
              </div>
              <div class="home-stat">
                <dt>大厅房间</dt>
                <dd><b data-testid="start-lobby-rooms">{{ stats.rooms }}</b><span class="home-stat__unit">间</span></dd>
              </div>
            </dl>
          </StateSurface>
        </section>

        <section class="home-panel home-changelog" data-testid="start-changelog" aria-labelledby="home-changelog-title">
          <h2 id="home-changelog-title" class="home-panel__title">最 近 公 告</h2>
          <p class="home-changelog__latest" data-testid="start-changelog-latest">{{ latestText }}</p>
          <StateSurface
            :state="changelogState"
            loading-text="公告载入中…"
            @retry="home.loadChangelog()"
          >
            <ul class="home-changelog__list">
              <li
                v-for="entry in entries"
                :key="entry.key"
                class="home-changelog__entry"
                :data-testid="'start-changelog-entry-' + entry.key"
              >
                <p class="home-changelog__date">{{ entry.date }}</p>
                <ul class="home-changelog__items">
                  <li v-for="(item, index) in entry.items" :key="index">{{ item }}</li>
                </ul>
              </li>
            </ul>
            <template #empty>
              <p class="home-panel__note" data-testid="start-changelog-empty">暂时没有公告。</p>
            </template>
            <template #error>
              <p class="home-panel__note" data-testid="start-changelog-empty">
                暂时没有公告（载入失败），可以重试。
              </p>
            </template>
          </StateSurface>
        </section>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.home-screen {
  width: 100%;
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 0 24px;
  gap: 4px;
}

.home-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 4px 18px;
}

.home-head__main {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.home-head__eyebrow {
  margin: 0;
  color: #8f9bc4;
  font-size: 9px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.home-head__title {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
}

.home-head__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  min-width: 0;
}

.home-pill {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  padding: 4px 12px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: rgba(13, 17, 34, 0.72);
  font-size: 12px;
  white-space: nowrap;
}

.home-pill__value {
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.home-pill__label,
.home-pill__unit {
  color: var(--text-muted);
  font-size: 11px;
}

.home-conn {
  color: var(--text-dim);
  font-size: 12px;
}

.home-conn[data-connected='true'] {
  color: var(--success);
}

.home-grid {
  display: grid;
  gap: 16px;
  min-width: 0;
  grid-template-columns: minmax(0, 280px) minmax(0, 1fr) minmax(0, 292px);
  grid-template-areas: 'player actions side';
  align-items: start;
}

.home-actions {
  grid-area: actions;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.home-player {
  grid-area: player;
}

.home-side {
  grid-area: side;
  display: grid;
  gap: 16px;
  min-width: 0;
}

/* Panel language: translucent indigo card with a violet hairline and a dashed
   header rule, matching the C+ arena panels. */
.home-panel {
  min-width: 0;
  padding: 14px 16px;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-panel);
}

.home-panel__title {
  margin: 0 0 8px;
  padding-bottom: 6px;
  border-bottom: 1px dashed var(--line-dash);
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.1em;
}

.home-panel__note {
  margin: 10px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.home-actions__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 8px;
  margin-bottom: 8px;
}

.home-actions__meta .home-panel__title {
  margin: 0;
  padding: 0;
  border: 0;
  color: var(--text);
  font-size: 12px;
  letter-spacing: 0.1em;
}

.home-actions__lead {
  margin: 0;
  color: var(--text-muted);
  font-size: 11px;
}

/* Action cards. The casual card is the purple hero; ranked carries the gold
   rank language; the AI card stays a quiet panel. */
.home-action {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 3px;
  width: 100%;
  margin: 0 0 10px;
  padding: 15px 18px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  background: rgba(15, 19, 38, 0.72);
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.home-action:hover:not(:disabled) {
  border-color: var(--accent);
  background: rgba(124, 92, 240, 0.18);
}

.home-action:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.home-action--primary {
  min-height: 88px;
  justify-content: center;
  border-color: var(--accent-strong);
  background: var(--hero-grad);
  box-shadow: var(--shadow-accent);
}

.home-action--primary:hover:not(:disabled) {
  filter: brightness(1.12);
}

.home-action--primary .home-action__title {
  font-size: 23px;
  letter-spacing: 0.04em;
}

.home-action--primary .home-action__desc {
  color: rgba(255, 255, 255, 0.82);
}

.home-action[data-testid='start-ranked-action'] {
  border-color: var(--role-action);
  background: var(--role-action-soft);
}

.home-action__title {
  font-size: 17px;
  font-weight: 600;
}

.home-action__desc {
  color: var(--text-muted);
  font-size: 12px;
}

.home-queue {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin: 0 0 10px;
  padding: 10px 12px;
  border: 1px dashed var(--accent-strong);
  border-radius: var(--radius);
  background: var(--accent-soft);
}

.home-queue__text {
  margin: 0;
  font-size: 13px;
}

.home-ai {
  display: grid;
  gap: 10px;
  margin-bottom: 10px;
}

.home-ai__action {
  margin-bottom: 0;
}

/* Four directly clickable difficulty pills (story 17): no hidden dropdown. */
.home-ai__caps {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.home-ai__cap {
  display: grid;
  justify-items: center;
  gap: 2px;
  min-height: 52px;
  padding: 7px 6px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface-chamber);
  color: var(--text-secondary);
  font: inherit;
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease), background var(--duration-fast) var(--ease);
}

.home-ai__cap b {
  font-size: 14px;
  font-weight: 600;
}

.home-ai__cap small {
  color: var(--text-tertiary);
  font-size: 10px;
  line-height: 1.3;
  text-align: center;
}

.home-ai__cap:hover:not(:disabled) {
  border-color: var(--role-action);
  color: var(--text-primary);
}

.home-ai__cap.is-active {
  border-color: var(--role-action);
  background: var(--role-action-soft);
  color: var(--text-primary);
}

.home-ai__cap.is-active small {
  color: var(--text-secondary);
}

.home-ai__cap:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 420px) {
  .home-ai__caps {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.home-notice {
  margin: 0 0 10px;
  padding: 8px 10px;
  border: 1px solid var(--danger);
  border-radius: var(--radius-sm);
  background: rgba(42, 20, 24, 0.8);
  color: #ffb3a8;
  font-size: 13px;
}

.home-links {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.home-player__links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.home-link {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 42px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: rgba(13, 17, 34, 0.72);
  color: var(--text-muted);
  font-size: 13px;
}

.home-link:hover {
  border-color: var(--accent);
  color: var(--text);
  background: var(--accent-soft);
}

/* The collection entry is an overlay button that must look exactly like the
   neighbouring route links (no new route name, same visual affordance). */
.home-link--button {
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.home-player__emblem {
  display: grid;
  place-items: center;
  width: 100px;
  height: 100px;
  margin: 2px auto 14px;
  border: 2px solid rgba(201, 162, 76, 0.55);
  border-radius: 50%;
  background: radial-gradient(circle at 50% 32%, rgba(201, 162, 76, 0.3), rgba(124, 92, 240, 0.18) 58%, transparent 74%);
  box-shadow: 0 0 34px rgba(201, 162, 76, 0.18), inset 0 0 24px rgba(201, 162, 76, 0.14);
}

.home-player__emblem span {
  color: var(--gold-strong);
  font-size: 32px;
  letter-spacing: 0.06em;
}

.home-player__name {
  margin: 0 0 8px;
  overflow-wrap: anywhere;
  font-size: 21px;
  font-weight: 700;
}

.home-player__note {
  margin: 0 0 4px;
  color: var(--text-muted);
  font-size: 13px;
}

.home-player__rank {
  margin: 0 0 6px;
  overflow-wrap: anywhere;
  color: var(--text);
  font-size: 14px;
}

.home-bar {
  height: 6px;
  margin-bottom: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--bg-sunken);
}

.home-bar__fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #b8873a, var(--gold-strong));
}

.home-bar__fill--xp {
  background: linear-gradient(90deg, #2a8f68, var(--success));
}

.home-player__level {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.home-player__level-label {
  font-size: 14px;
  font-weight: 600;
}

.home-player__level-text {
  color: var(--text-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.home-player__kv {
  display: grid;
  gap: 4px;
  margin: 0 0 12px;
}

.home-player__kv-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 9px;
  border: 1px solid rgba(42, 51, 88, 0.6);
  border-radius: var(--radius-sm);
  background: rgba(13, 17, 34, 0.62);
}

.home-player__kv-row dt {
  color: var(--text-muted);
  font-size: 12px;
}

.home-player__kv-row dd {
  margin: 0;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.home-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}

.home-stat {
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid rgba(42, 51, 88, 0.6);
  border-radius: var(--radius-sm);
  background: rgba(13, 17, 34, 0.62);
}

.home-stat--wide {
  grid-column: 1 / -1;
}

.home-stat dt {
  color: var(--text-muted);
  font-size: 12px;
}

.home-stat dd {
  display: flex;
  align-items: baseline;
  gap: 3px;
  margin: 2px 0 0;
  font-size: 18px;
  font-variant-numeric: tabular-nums;
}

.home-stat__unit {
  color: var(--text-muted);
  font-size: 12px;
}

.home-changelog__latest {
  margin: 0 0 8px;
  color: var(--accent-cyan);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.home-changelog__list,
.home-changelog__items {
  margin: 0;
  padding: 0;
  list-style: none;
}

.home-changelog__list {
  display: grid;
  gap: 10px;
}

.home-changelog__entry {
  min-width: 0;
  padding-top: 8px;
  border-top: 1px solid rgba(42, 51, 88, 0.7);
}

.home-changelog__entry:first-child {
  padding-top: 0;
  border-top: 0;
}

.home-changelog__date {
  margin: 0 0 4px;
  color: var(--text-dim);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.home-changelog__items {
  display: grid;
  gap: 3px;
  color: var(--text);
  font-size: 12px;
  overflow-wrap: anywhere;
}

@media (max-width: 1179px) {
  .home-grid {
    grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
    grid-template-areas:
      'actions actions'
      'player side';
  }
}

@media (max-width: 759px) {
  .home-grid {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      'actions'
      'player'
      'side';
  }

  .home-screen {
    max-width: none;
    padding: 10px 14px 22px;
  }

  .home-conn {
    display: none;
  }

  .home-action--primary {
    min-height: 74px;
  }

  .home-player__emblem {
    display: none;
  }
}
</style>
