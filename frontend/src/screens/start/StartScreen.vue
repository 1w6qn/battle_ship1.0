<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useGameStore } from '../../stores/game'
import { useHomeStore } from '../../stores/home'
import {
  acquireHomeChannel,
  createAiRoom,
  emitCancelMatch,
  emitFindMatch,
  homeSocket,
} from '../../realtime/home'
import {
  changelogKey,
  numberText,
  playerView,
  queueStatusText,
  statsText,
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
const home = useHomeStore()
const game = useGameStore()

const difficulty = ref('normal')
let releaseChannel: (() => void) | null = null
let navigating = false

onMounted(() => {
  releaseChannel = acquireHomeChannel(undefined, {
    onConnect: () => {
      // The online counter includes this very connection once it is up.
      void home.loadStats()
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
})

const player = computed(() => playerView(home.profile))
const playerName = computed(() => (player.value.guest ? '玩家' : player.value.name))
const stats = computed(() => statsText(home.stats))
const queueText = computed(() => queueStatusText(home.queueMode))
const pillText = computed(() => numberText(home.onlinePill))
const latestText = computed(() => {
  if (home.changelogLatest) return home.changelogLatest
  return home.changelogLoaded ? '—' : '载入中…'
})
const entries = computed(() =>
  home.changelog.map((entry) => ({ ...entry, key: changelogKey(entry) })),
)
const actionsDisabled = computed(() => home.busy || home.awaitingPlacement)

function maybeAdvance(): void {
  if (navigating || !home.awaitingPlacement) return
  if (game.state.state !== 'placing_ships') return
  navigating = true
  home.placementHandled()
  void router.push({ name: 'placement' })
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
    await emitCancelMatch(socket)
    home.applyMatchCanceled()
  } catch {
    home.notifyMessage('取消匹配失败，请再试一次')
  }
}

async function startAi(): Promise<void> {
  const socket = currentSocket()
  if (!socket) return
  home.clearNotice()
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
        <h2 id="home-actions-title" class="home-panel__title">开 一 局</h2>
        <p class="home-actions__lead">
          休闲与排位共用一个匹配队列；人机随时开局，不结算段位分。
        </p>

        <button
          type="button"
          class="home-action home-action--primary"
          data-testid="start-primary-action"
          :disabled="actionsDisabled"
          @click="startMatch('casual')"
        >
          <span class="home-action__title">休闲匹配</span>
          <span class="home-action__desc">随机匹配一位在线玩家 · 不计段位分</span>
        </button>

        <div v-if="home.queuePending" class="home-queue" role="status">
          <p class="home-queue__text" data-testid="start-queue-status">{{ queueText }}</p>
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
          <span class="home-action__title">排位对战</span>
          <span class="home-action__desc">结算会改变段位 · 需要登录</span>
        </button>

        <div class="home-ai">
          <button
            type="button"
            class="home-action home-ai__action"
            data-testid="start-ai-action"
            :disabled="actionsDisabled"
            @click="startAi"
          >
            <span class="home-action__title">人机对战</span>
            <span class="home-action__desc">四档电脑难度 · 练习规则与连锁</span>
          </button>
          <label class="home-ai__label">
            <span class="home-ai__label-text">电脑难度</span>
            <select
              v-model="difficulty"
              class="home-ai__select"
              data-testid="start-ai-difficulty"
              :disabled="actionsDisabled"
            >
              <option value="easy">简单</option>
              <option value="normal">普通</option>
              <option value="hard">困难</option>
              <option value="master">大师</option>
            </select>
          </label>
        </div>

        <p v-if="home.notice" class="home-notice" role="alert" data-testid="start-notice">
          {{ home.notice }}
        </p>

        <nav class="home-links" aria-label="更多入口">
          <router-link class="home-link" :to="{ name: 'lobby' }" data-testid="start-lobby-link">游戏大厅</router-link>
          <router-link class="home-link" :to="{ name: 'leaderboard' }" data-testid="start-leaderboard-link">排行榜</router-link>
          <router-link class="home-link" :to="{ name: 'settings' }" data-testid="start-settings-link">设置</router-link>
        </nav>
      </section>

      <!-- 玩家信息：/api/profile 的服务端字段，前端只排版。 -->
      <aside class="home-panel home-player" data-testid="start-player" aria-labelledby="home-player-title">
        <h2 id="home-player-title" class="home-panel__title">指 挥 官</h2>
        <p class="home-player__name" data-testid="start-player-name">{{ player.name }}</p>

        <template v-if="player.guest">
          <p v-if="home.profileFailed" class="home-player__note" data-testid="start-player-error">
            名片暂时取不到，刷新后再试。
          </p>
          <p v-else-if="home.profileLoaded" class="home-player__note" data-testid="start-player-guest">
            游客状态：登录后显示段位、等级与战绩。
          </p>
          <p v-else class="home-player__note" data-testid="start-player-loading">正在读取名片…</p>
          <div class="home-player__links">
            <a class="home-link" href="/login" data-testid="start-login-link">去登录</a>
            <router-link class="home-link" :to="{ name: 'profile' }" data-testid="start-profile-link">查看名片</router-link>
          </div>
        </template>

        <template v-else>
          <p class="home-player__rank" data-testid="start-player-rank">{{ player.rankLabel }}</p>
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
              <dd data-testid="start-player-record">{{ player.record }}</dd>
            </div>
            <div class="home-player__kv-row">
              <dt>胜率</dt>
              <dd data-testid="start-player-winrate">{{ player.winRate }}</dd>
            </div>
            <div class="home-player__kv-row">
              <dt>最长连胜</dt>
              <dd data-testid="start-player-streak">{{ player.streak }}</dd>
            </div>
          </dl>
          <router-link class="home-link" :to="{ name: 'profile' }" data-testid="start-profile-link">查看我的名片</router-link>
        </template>
      </aside>

      <!-- 在线与公告。 -->
      <aside class="home-side">
        <section class="home-panel" data-testid="start-online" aria-labelledby="home-online-title">
          <h2 id="home-online-title" class="home-panel__title">在 线</h2>
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
          <p v-if="home.statsFailed" class="home-panel__note" data-testid="start-stats-note">
            在线数据暂时取不到，稍后再看。
          </p>
        </section>

        <section class="home-panel home-changelog" data-testid="start-changelog" aria-labelledby="home-changelog-title">
          <h2 id="home-changelog-title" class="home-panel__title">最 近 公 告</h2>
          <p class="home-changelog__latest" data-testid="start-changelog-latest">{{ latestText }}</p>
          <ul v-if="entries.length" class="home-changelog__list">
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
          <p v-else class="home-panel__note" data-testid="start-changelog-empty">
            {{ home.changelogLoaded ? '暂时没有公告。' : '公告载入中…' }}
          </p>
        </section>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.home-screen {
  padding: 20px;
  gap: 14px;
}

.home-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 10px 18px;
}

.home-head__main {
  min-width: 0;
}

.home-head__eyebrow {
  margin: 0 0 4px;
  color: var(--accent);
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.home-head__title {
  margin: 0;
  font-size: 28px;
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
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--bg-elevated);
  font-size: 13px;
  white-space: nowrap;
}

.home-pill__value {
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}

.home-pill__label,
.home-pill__unit {
  color: var(--text-muted);
  font-size: 12px;
}

.home-conn {
  color: var(--text-muted);
  font-size: 12px;
}

.home-conn[data-connected='true'] {
  color: #6fe0a0;
}

.home-grid {
  display: grid;
  gap: 16px;
  min-width: 0;
  grid-template-columns: minmax(220px, 300px) minmax(0, 1fr) minmax(250px, 340px);
  grid-template-areas: 'player actions side';
  align-items: start;
}

.home-actions {
  grid-area: actions;
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

.home-panel {
  min-width: 0;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-elevated);
}

.home-panel__title {
  margin: 0 0 10px;
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.24em;
}

.home-panel__note {
  margin: 10px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.home-actions__lead {
  margin: 0 0 12px;
  color: var(--text-muted);
  font-size: 13px;
}

.home-action {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  margin-bottom: 10px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: #0b1a24;
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.home-action:hover:not(:disabled) {
  border-color: var(--accent-strong);
  background: #103240;
}

.home-action:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.home-action--primary {
  border-color: var(--accent-strong);
  background: #0f3a47;
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
  background: #0e2a34;
}

.home-queue__text {
  margin: 0;
  font-size: 13px;
}

.home-ai {
  display: grid;
  gap: 8px;
  margin-bottom: 10px;
}

.home-ai__action {
  margin-bottom: 0;
}

.home-ai__label {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: 12px;
}

.home-ai__select {
  flex: 1;
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #0b1a24;
  color: var(--text);
  font: inherit;
  font-size: 13px;
}

.home-notice {
  margin: 0 0 10px;
  padding: 8px 10px;
  border: 1px solid var(--danger);
  border-radius: 8px;
  background: #2a1414;
  color: #ffb3a8;
  font-size: 13px;
}

.home-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.home-player__links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.home-link {
  display: inline-block;
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-muted);
  font-size: 13px;
}

.home-link:hover {
  border-color: var(--accent-strong);
  color: var(--text);
  background: #14303f;
}

.home-player__name {
  margin: 0 0 8px;
  overflow-wrap: anywhere;
  font-size: 22px;
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
  background: #0b1a24;
}

.home-bar__fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #b8872e, #ffd76a);
}

.home-bar__fill--xp {
  background: linear-gradient(90deg, #2a8f68, #6fe0a0);
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
  margin: 0 0 10px;
}

.home-player__kv-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 8px;
  background: #0b1a24;
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
  border-radius: 8px;
  background: #0b1a24;
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
  color: var(--accent);
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
  border-top: 1px solid var(--border);
}

.home-changelog__entry:first-child {
  padding-top: 0;
  border-top: 0;
}

.home-changelog__date {
  margin: 0 0 4px;
  color: var(--text-muted);
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
}

@media (max-width: 520px) {
  .home-screen {
    padding: 14px;
  }

  .home-head__title {
    font-size: 24px;
  }

  .home-action__title {
    font-size: 16px;
  }
}
</style>
