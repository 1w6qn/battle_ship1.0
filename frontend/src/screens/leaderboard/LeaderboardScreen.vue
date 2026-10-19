<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useLeaderboardStore, type JsonObject } from '../../stores/leaderboard'
import { useProfileStore } from '../../stores/profile'

/**
 * Ticket #25: the leaderboard screen.
 *
 * Two independent server-sorted sources (wins board / ranked board). This screen
 * never re-sorts or recomputes a tier: every label, position and points value is
 * rendered exactly as the endpoint returned it.
 */
const router = useRouter()
const board = useLeaderboardStore()
const profile = useProfileStore()

onMounted(async () => {
  await profile.loadOwn()
  if (board.record.status === 'idle') await board.loadRecord()
})

const meName = computed(() => profile.viewerName)

function text(row: JsonObject | null | undefined, key: string): string {
  const value = row ? row[key] : ''
  return value === null || value === undefined ? '' : String(value)
}

function numberText(row: JsonObject | null | undefined, key: string): string {
  const value = Number(row ? row[key] : 0)
  return Number.isFinite(value) ? String(value) : '0'
}

function winRate(row: JsonObject): string {
  const wins = Number(row.wins) || 0
  const losses = Number(row.losses) || 0
  const total = wins + losses
  return total ? Math.round((wins / total) * 100) + '%' : '—'
}

const activeTab = computed(() => board.activeTab)
const activeBoard = computed(() => board.active)
const podiumRows = computed(() => {
  const rows = activeBoard.value.rows.slice(0, 3)
  if (rows.length < 3) return rows.map((row, index) => ({ row, place: index + 1 }))
  return [
    { row: rows[1], place: 2 },
    { row: rows[0], place: 1 },
    { row: rows[2], place: 3 },
  ]
})

function podiumValue(row: JsonObject): string {
  return activeTab.value === 'ranked' ? numberText(row, 'points') : numberText(row, 'wins')
}

function podiumLabel(): string {
  return activeTab.value === 'ranked' ? '排位分' : '胜场'
}

function isMe(row: JsonObject): boolean {
  const name = text(row, 'username')
  return Boolean(name) && name === meName.value
}

function openTab(tab: 'record' | 'ranked'): void {
  if (tab === activeTab.value) return
  board.setTab(tab)
}

function openUser(username: string): void {
  if (!username) return
  void router.push({ name: 'profile', query: { username } })
}

function backHome(): void {
  void router.push({ name: 'start' })
}
</script>

<template>
  <section
    class="screen leaderboard"
    data-screen="leaderboard"
    data-testid="screen-leaderboard"
    :data-tab="activeTab"
    aria-labelledby="screen-leaderboard-title"
  >
    <header class="leaderboard__head">
      <p class="leaderboard__eyebrow">P4 · 排行</p>
      <h1 id="screen-leaderboard-title" class="leaderboard__title" data-testid="leaderboard-heading">排行榜</h1>
      <p class="leaderboard__hint">
        战绩榜按胜场排序，段位榜按排位分排序；两张榜都是服务端排好的名次。
      </p>
    </header>

    <div class="leaderboard__tabs" data-testid="leaderboard-tabs" role="tablist" aria-label="榜单">
      <button
        type="button"
        class="leaderboard__tab"
        data-testid="leaderboard-tab-record"
        role="tab"
        :aria-selected="activeTab === 'record' ? 'true' : 'false'"
        :class="{ 'is-active': activeTab === 'record' }"
        @click="openTab('record')"
      >
        战绩榜
      </button>
      <button
        type="button"
        class="leaderboard__tab"
        data-testid="leaderboard-tab-ranked"
        role="tab"
        :aria-selected="activeTab === 'ranked' ? 'true' : 'false'"
        :class="{ 'is-active': activeTab === 'ranked' }"
        @click="openTab('ranked')"
      >
        段位榜
      </button>
    </div>

    <p v-if="activeTab === 'ranked' && activeBoard.status === 'loading' && activeBoard.rows.length === 0"
       class="leaderboard__state" data-testid="leaderboard-ranked-loading" role="status">
      正在加载段位榜…
    </p>
    <p v-if="activeTab === 'record' && activeBoard.status === 'loading' && activeBoard.rows.length === 0"
       class="leaderboard__state" data-testid="leaderboard-loading" role="status">
      正在加载战绩榜…
    </p>

    <p v-if="activeTab === 'record' && activeBoard.status === 'error'"
       class="leaderboard__error" data-testid="leaderboard-error" role="alert">
      无法加载排行榜：{{ activeBoard.error }}
    </p>
    <p v-if="activeTab === 'ranked' && activeBoard.status === 'error'"
       class="leaderboard__error" data-testid="leaderboard-ranked-error" role="alert">
      无法加载段位榜：{{ activeBoard.error }}
    </p>

    <p v-if="activeTab === 'record' && activeBoard.status === 'ready' && activeBoard.rows.length === 0"
       class="leaderboard__state" data-testid="leaderboard-empty">
      榜单还空着 —— 打完第一局并产生胜负记录后就会出现在这里。
    </p>
    <p v-if="activeTab === 'ranked' && activeBoard.status === 'ready' && activeBoard.rows.length === 0"
       class="leaderboard__state" data-testid="leaderboard-ranked-empty">
      还没有人打过排位 —— 打一场排位赛就会出现在这里。
    </p>

    <div v-if="podiumRows.length" class="leaderboard__podium" data-testid="leaderboard-podium" aria-label="前三名">
      <button
        v-for="item in podiumRows"
        :key="'podium-' + text(item.row, 'username')"
        type="button"
        class="leaderboard__podium-card"
        :class="{ 'is-me': isMe(item.row) }"
        :data-testid="'leaderboard-podium-' + text(item.row, 'username')"
        :data-place="activeTab === 'ranked' ? numberText(item.row, 'position') : String(item.place)"
        @click="openUser(text(item.row, 'username'))"
      >
        <span class="leaderboard__podium-name">{{ text(item.row, 'username') || '未知玩家' }}</span>
        <b class="leaderboard__podium-score">{{ podiumValue(item.row) }}</b>
        <small class="leaderboard__podium-label">{{ podiumLabel() }}</small>
      </button>
    </div>

    <div v-if="activeTab === 'record'" class="leaderboard__table-wrap">
      <table class="leaderboard__table" data-testid="leaderboard-table">
        <thead>
          <tr>
            <th scope="col">排名</th>
            <th scope="col">玩家</th>
            <th scope="col">胜</th>
            <th scope="col">负</th>
            <th scope="col">胜率</th>
            <th scope="col">最长连胜</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, index) in activeBoard.rows"
            :key="'record-' + text(row, 'username')"
            :data-testid="'leaderboard-row-' + text(row, 'username')"
            :data-me="isMe(row) ? 'true' : 'false'"
            :class="{ 'is-me': isMe(row) }"
          >
            <td>{{ index + 1 }}</td>
            <td class="leaderboard__player">
              <button
                type="button"
                class="leaderboard__user"
                :data-testid="'leaderboard-open-' + text(row, 'username')"
                :title="'查看 ' + (text(row, 'username') || '玩家') + ' 的名片'"
                @click="openUser(text(row, 'username'))"
              >
                <img
                  v-if="text(row, 'avatar')"
                  class="leaderboard__avatar"
                  :src="text(row, 'avatar')"
                  alt=""
                />
                <span :class="['leaderboard__name', { 'is-rainbow': text(row, 'name_style') === 'rainbow' }]">
                  {{ text(row, 'username') || '未知玩家' }}
                </span>
                <span class="leaderboard__open-hint" aria-hidden="true">名片 ↗</span>
              </button>
            </td>
            <td class="leaderboard__num">{{ numberText(row, 'wins') }}</td>
            <td class="leaderboard__num">{{ numberText(row, 'losses') }}</td>
            <td class="leaderboard__num">{{ winRate(row) }}</td>
            <td class="leaderboard__num">{{ numberText(row, 'longest_streak') }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-else class="leaderboard__table-wrap">
      <table class="leaderboard__table" data-testid="leaderboard-ranked-table">
        <thead>
          <tr>
            <th scope="col">名次</th>
            <th scope="col">玩家</th>
            <th scope="col">段位</th>
            <th scope="col">排位分</th>
            <th scope="col">战绩</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in activeBoard.rows"
            :key="'ranked-' + text(row, 'username')"
            :data-testid="'leaderboard-ranked-row-' + text(row, 'username')"
            :data-me="isMe(row) ? 'true' : 'false'"
            :class="{ 'is-me': isMe(row) }"
          >
            <td>{{ numberText(row, 'position') }}</td>
            <td class="leaderboard__player">
              <button
                type="button"
                class="leaderboard__user"
                :data-testid="'leaderboard-ranked-open-' + text(row, 'username')"
                :title="'查看 ' + (text(row, 'username') || '玩家') + ' 的名片'"
                @click="openUser(text(row, 'username'))"
              >
                <img
                  v-if="text(row, 'avatar')"
                  class="leaderboard__avatar"
                  :src="text(row, 'avatar')"
                  alt=""
                />
                <span :class="['leaderboard__name', { 'is-rainbow': text(row, 'name_style') === 'rainbow' }]">
                  {{ text(row, 'username') || '未知玩家' }}
                </span>
                <span class="leaderboard__open-hint" aria-hidden="true">名片 ↗</span>
              </button>
            </td>
            <td>
              <span class="leaderboard__tier" :data-tier="text(row, 'tier_id')">
                {{ text(row, 'label') || text(row, 'tier_name') || '—' }}
              </span>
            </td>
            <td class="leaderboard__num">{{ numberText(row, 'points') }}</td>
            <td class="leaderboard__num">
              {{ numberText(row, 'ranked_wins') }} 胜 {{ numberText(row, 'ranked_losses') }} 负
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <footer class="leaderboard__actions">
      <button type="button" class="button button--ghost" data-testid="leaderboard-back-home" @click="backHome">
        返回首页
      </button>
    </footer>
  </section>
</template>

<style scoped>
.leaderboard {
  gap: 12px;
}

.leaderboard__eyebrow {
  margin: 0 0 4px;
  color: var(--accent);
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.leaderboard__title {
  margin: 0;
  font-size: 28px;
}

.leaderboard__hint {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}

.leaderboard__tabs {
  display: flex;
  gap: 8px;
  padding: 4px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--bg-elevated);
  align-self: flex-start;
}

.leaderboard__tab {
  padding: 6px 16px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  cursor: pointer;
}

.leaderboard__tab.is-active {
  background: #14303f;
  color: var(--text);
}

.leaderboard__state,
.leaderboard__error {
  margin: 0;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-elevated);
  color: var(--text-muted);
  font-size: 13px;
}

.leaderboard__error {
  border-color: var(--danger);
  color: var(--danger);
}

.leaderboard__podium {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.leaderboard__podium-card {
  display: grid;
  gap: 2px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: linear-gradient(160deg, #14303f, #0b1a24);
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.leaderboard__podium-card[data-place='1'] {
  border-color: #b8872e;
  box-shadow: 0 0 0 1px #b8872e inset;
}

.leaderboard__podium-card.is-me {
  outline: 1px solid var(--accent);
}

.leaderboard__podium-name {
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.leaderboard__podium-score {
  color: #ffd76a;
  font-size: 22px;
  font-variant-numeric: tabular-nums;
}

.leaderboard__podium-label {
  color: var(--text-muted);
  font-size: 11px;
}

.leaderboard__table-wrap {
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-elevated);
}

.leaderboard__table {
  width: 100%;
  min-width: 640px;
  border-collapse: collapse;
  font-size: 13px;
}

.leaderboard__table th,
.leaderboard__table td {
  padding: 8px 10px;
  text-align: left;
  border-bottom: 1px solid #14303f;
  white-space: nowrap;
}

.leaderboard__table thead th {
  color: var(--text-muted);
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.08em;
}

.leaderboard__table tbody tr:last-child td {
  border-bottom: 0;
}

.leaderboard__table tbody tr.is-me {
  background: #10303d;
}

.leaderboard__user {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  cursor: pointer;
}

.leaderboard__avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  object-fit: cover;
  background: #0b1a24;
}

.leaderboard__name.is-rainbow {
  background: linear-gradient(90deg, #ff8a7a, #ffd76a, #6fe0a0, #37c2d9);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.leaderboard__open-hint {
  color: var(--text-muted);
  font-size: 11px;
}

.leaderboard__num {
  font-variant-numeric: tabular-nums;
}

.leaderboard__tier {
  padding: 2px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: #ffd76a;
  font-size: 12px;
}

.leaderboard__actions {
  display: flex;
  gap: 10px;
  margin-top: auto;
}

.button--ghost {
  border-color: var(--border);
  background: transparent;
  color: var(--text-muted);
}

@media (max-width: 640px) {
  .leaderboard__podium {
    grid-template-columns: 1fr;
  }
}
</style>