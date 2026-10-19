<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProfileStore, type JsonObject } from '../../stores/profile'

/**
 * Ticket #25: own / other player's profile card.
 *
 * Every number, badge, tier label and history row comes from the server. The
 * privacy flags are rendered, not enforced here: show_history / show_rank /
 * show_guestbook were already applied by the server, while show_stats /
 * show_fav_cards remain legacy frontend-only hides (DECISIONS D13).
 */
const route = useRoute()
const router = useRouter()
const store = useProfileStore()

const targetUsername = computed(() => String(route.query.username || '').trim())
const viewed = computed(() => store.viewed)
const stats = computed<JsonObject | null>(() => viewed.value.stats)

const isSelf = computed(() => {
  const row = stats.value
  if (!row) return false
  const name = String(row.username || '')
  return Boolean(name) && name === store.viewerName
})

function readObject(source: JsonObject | null | undefined, key: string): JsonObject | null {
  const value = source ? source[key] : null
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonObject)
    : null
}

function readArray(source: JsonObject | null | undefined, key: string): unknown[] {
  const value = source ? source[key] : null
  return Array.isArray(value) ? value : []
}

function readString(source: JsonObject | null | undefined, key: string): string {
  const value = source ? source[key] : null
  return typeof value === 'string' ? value : ''
}

function readNumber(source: JsonObject | null | undefined, key: string): number | null {
  const value = Number(source ? source[key] : NaN)
  return Number.isFinite(value) ? value : null
}

function flag(key: string): boolean {
  const value = stats.value ? stats.value[key] : null
  return value === undefined || value === null ? true : Number(value) !== 0
}

const loading = computed(
  () =>
    viewed.value.status === 'loading' ||
    (store.ownStatus === 'loading' && !targetUsername.value),
)
const loginRequired = computed(
  () => !targetUsername.value && store.ownStatus === 'anonymous' && viewed.value.status === 'idle',
)
const empty = computed(() => viewed.value.status === 'empty')
const failed = computed(() => viewed.value.status === 'error')
const ready = computed(() => viewed.value.status === 'ready' && stats.value !== null)

const avatar = computed(() => readString(stats.value, 'avatar'))
const displayName = computed(() => readString(stats.value, 'username') || targetUsername.value || '玩家')
const statusText = computed(() => readString(stats.value, 'status_text'))
const signature = computed(() => readString(stats.value, 'signature'))
const titleName = computed(() => readString(stats.value, 'title_name'))
const nameStyle = computed(() => readString(stats.value, 'name_style'))
const cardBg = computed(() => readString(stats.value, 'card_bg_id') || 'deep')
const frame = computed(() => readString(stats.value, 'frame_id') || 'none')

const tags = computed(() => {
  const names = readArray(stats.value, 'tag_names').map((item) => String(item))
  if (names.length) return names
  return readArray(stats.value, 'tags').map((item) => String(item))
})

const wins = computed(() => readNumber(stats.value, 'wins') ?? 0)
const losses = computed(() => readNumber(stats.value, 'losses') ?? 0)
const totalMatches = computed(() => wins.value + losses.value)
const winRateText = computed(() => {
  const total = totalMatches.value
  return total ? Math.round((wins.value / total) * 100) + '%' : '—'
})
const streak = computed(() => readNumber(stats.value, 'longest_streak') ?? 0)

const levelInfo = computed(() => readObject(stats.value, 'level_info'))
const levelText = computed(() => 'Lv.' + (readNumber(levelInfo.value, 'level') ?? 1))
const levelCapped = computed(() => levelInfo.value?.capped === true)
const levelFill = computed(() => {
  if (!levelInfo.value) return 0
  if (levelCapped.value) return 100
  const ratio = readNumber(levelInfo.value, 'ratio') ?? 0
  return Math.max(0, Math.min(100, Math.round(ratio * 100)))
})
const levelProgressText = computed(() => {
  if (!levelInfo.value) return ''
  if (levelCapped.value) return '满级 ' + (readNumber(levelInfo.value, 'max_level') ?? 100)
  const into = readNumber(levelInfo.value, 'into') ?? 0
  const need = readNumber(levelInfo.value, 'need') ?? 0
  return into + ' / ' + need + ' 经验'
})

const rankInfo = computed(() => readObject(stats.value, 'rank_info'))
const showRank = computed(() => flag('show_rank'))
const rankFill = computed(() => {
  const row = rankInfo.value
  if (!row) return 0
  const sub = readNumber(row, 'sub_points') ?? 0
  const progress = readNumber(row, 'progress') ?? 0
  if (sub <= 0) return 0
  return Math.max(0, Math.min(100, Math.round((progress / sub) * 100)))
})
const rankNextText = computed(() => {
  const next = rankInfo.value ? readNumber(rankInfo.value, 'to_next') : null
  return next === null ? '' : '还差 ' + next + ' 分'
})

const showStats = computed(() => flag('show_stats'))
const showFavCards = computed(() => flag('show_fav_cards'))
const favCards = computed(() =>
  readArray(stats.value, 'fav_cards')
    .filter((item): item is JsonObject => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    .filter((item) => Boolean(item.name)),
)

const badges = computed(() => {
  // Owner view: the full catalogue comes from /api/achievements.
  if (store.achievements.length) return store.achievements
  return readArray(stats.value, 'achievements').filter(
    (item): item is JsonObject => Boolean(item) && typeof item === 'object' && !Array.isArray(item),
  )
})
const badgeCount = computed(() => store.achievementCount ?? readObject(stats.value, 'badge_count'))
const badgeUnlocked = computed(() => {
  const count = badgeCount.value ? readNumber(badgeCount.value, 'unlocked') : null
  return count ?? badges.value.filter((item) => item.unlocked === true).length
})
const badgeTotal = computed(() => {
  const count = badgeCount.value ? readNumber(badgeCount.value, 'total') : null
  return count ?? badges.value.length
})

const showHistory = computed(() => isSelf.value || flag('show_history'))
const history = computed(() => viewed.value.history)
const historyEmptyText = computed(() => {
  if (!showHistory.value) return '该玩家未公开对局历史'
  return isSelf.value ? '还没有对局记录' : '暂无历史战绩'
})

const winsRank = computed(() => readNumber(stats.value, 'rank'))
const createdAt = computed(() => {
  const seconds = readNumber(stats.value, 'created_at')
  if (!seconds) return ''
  const date = new Date(seconds * 1000)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('zh-CN')
})

function modeLabel(mode: unknown): string {
  switch (String(mode || '')) {
    case 'ranked':
      return '排位'
    case 'casual':
      return '休闲'
    case 'ai':
      return '人机'
    case 'custom':
      return '自定义'
    default:
      return ''
  }
}

function historyTime(row: JsonObject): string {
  const seconds = Number(row.timestamp)
  if (!Number.isFinite(seconds) || seconds <= 0) return ''
  const date = new Date(seconds * 1000)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN')
}

function historyOpponent(row: JsonObject): string {
  const selfId = stats.value ? String(stats.value.id || '') : ''
  const winnerId = String(row.winner_id || '')
  const name = winnerId === selfId ? row.loser_name : row.winner_name
  return String(name || '未知玩家')
}

function historyResult(row: JsonObject): string {
  const selfId = stats.value ? String(stats.value.id || '') : ''
  return String(row.winner_id || '') === selfId ? '胜' : '负'
}

function openReplay(matchId: string): void {
  if (!matchId) return
  void router.push({ name: 'replay', query: { match_id: matchId } })
}

function openSettings(): void {
  void router.push({ name: 'settings' })
}

function back(): void {
  void router.push({ name: 'leaderboard' })
}

async function refresh(): Promise<void> {
  if (targetUsername.value) {
    await store.loadPublic(targetUsername.value)
    return
  }
  if (store.viewerName) {
    await store.loadPublic(store.viewerName)
  } else {
    store.clearViewed()
  }
}

onMounted(async () => {
  await store.loadOwn()
  await refresh()
})

watch(targetUsername, () => {
  void refresh()
})
</script>

<template>
  <section
    class="screen profile"
    data-screen="profile"
    data-testid="screen-profile"
    :data-self="isSelf ? 'true' : 'false'"
    aria-labelledby="screen-profile-title"
  >
    <header class="profile__head">
      <p class="profile__eyebrow">P4 · 名片</p>
      <h1 id="screen-profile-title" class="profile__title" data-testid="profile-heading">名片</h1>
      <p class="profile__viewing" data-testid="profile-viewing">
        {{ ready ? (isSelf ? '我的名片' : displayName + ' 的名片') : '玩家名片' }}
      </p>
    </header>

    <p v-if="loading" class="profile__state" data-testid="profile-loading" role="status">正在加载名片…</p>

    <section v-else-if="loginRequired" class="profile__login" data-testid="profile-login-required">
      <h2>需要先登录</h2>
      <p>自己的名片、徽章与隐私设置都在登录后显示。</p>
      <a class="button" href="/login">前往登录</a>
    </section>

    <p v-else-if="empty" class="profile__state" data-testid="profile-empty">
      没有找到这位玩家 —— 用户名可能拼错了，或账号已经不存在。
    </p>

    <p v-else-if="failed" class="profile__state profile__state--error" data-testid="profile-error" role="alert">
      无法加载名片：{{ viewed.error }}
    </p>

    <template v-else-if="ready">
      <article class="profile__card" :data-bg="cardBg">
        <header class="profile__hero">
          <div class="profile__avatar-wrap">
            <img v-if="avatar" class="profile__avatar" data-testid="profile-avatar"
                 :src="avatar" :data-frame="frame" alt="" />
            <span v-else class="profile__avatar profile__avatar--empty" data-testid="profile-avatar"
                  :data-frame="frame" aria-hidden="true">⚓</span>
            <span class="profile__level" data-testid="profile-level">{{ levelText }}</span>
          </div>
          <div class="profile__who">
            <h2 class="profile__name">
              <span :class="{ 'is-rainbow': nameStyle === 'rainbow' }" data-testid="profile-name">{{ displayName }}</span>
              <span v-if="titleName" class="profile__title-chip" data-testid="profile-title">{{ titleName }}</span>
            </h2>
            <p class="profile__status" data-testid="profile-status">{{ statusText || '这位玩家还没有写状态' }}</p>
            <p class="profile__signature" data-testid="profile-signature">
              {{ signature || '还没有填写个性签名' }}
            </p>
            <div v-if="tags.length" class="profile__tags" data-testid="profile-tags">
              <span v-for="tag in tags" :key="tag" class="profile__tag">{{ tag }}</span>
            </div>
          </div>
        </header>

        <div v-if="levelInfo" class="profile__bar-row">
          <div class="profile__bar" role="img" :aria-label="'等级进度 ' + levelFill + '%'">
            <div class="profile__bar-fill" data-testid="profile-level-fill" :style="{ width: levelFill + '%' }"></div>
          </div>
          <span class="profile__bar-text" data-testid="profile-level-text">{{ levelProgressText }}</span>
        </div>

        <section v-if="rankInfo" class="profile__rank" data-testid="profile-rank">
          <span class="profile__rank-label" data-testid="profile-rank-label">{{ readString(rankInfo, 'label') }}</span>
          <div class="profile__bar profile__bar--rank" role="img" :aria-label="'段位进度 ' + rankFill + '%'">
            <div class="profile__bar-fill profile__bar-fill--rank"
                 data-testid="profile-rank-fill" :style="{ width: rankFill + '%' }"></div>
          </div>
          <span v-if="rankNextText" class="profile__bar-text" data-testid="profile-rank-note">{{ rankNextText }}</span>
        </section>
        <p v-else-if="!isSelf && !showRank" class="profile__private" data-testid="profile-rank-private">
          该玩家未公开段位信息。
        </p>

        <section v-if="showStats" class="profile__stats" data-testid="profile-stats" aria-label="战绩">
          <div class="profile__stat"><b data-testid="profile-stat-streak">{{ streak }}</b><span>最高连胜</span></div>
          <div class="profile__stat"><b data-testid="profile-stat-rate">{{ winRateText }}</b><span>胜率</span></div>
          <div class="profile__stat"><b data-testid="profile-stat-total">{{ totalMatches }}</b><span>总场次</span></div>
        </section>
        <p v-else class="profile__private" data-testid="profile-stats-private">该玩家未公开战绩亮点。</p>

        <section v-if="badges.length" class="profile__block" data-testid="profile-badges" aria-label="徽章墙">
          <h3 class="profile__block-title">
            徽章墙
            <span class="profile__badge-count" data-testid="profile-badge-count">
              已解锁 {{ badgeUnlocked }} / {{ badgeTotal }}
            </span>
          </h3>
          <ul class="profile__badge-list">
            <li
              v-for="badge in badges"
              :key="readString(badge, 'id')"
              class="profile__badge"
              :class="{ 'is-locked': badge.unlocked !== true }"
              :data-testid="'profile-badge-' + readString(badge, 'id')"
              :title="readString(badge, 'requirement')"
            >
              <b>{{ readString(badge, 'name') }}</b>
              <span>{{ badge.unlocked === true ? readString(badge, 'desc') : readString(badge, 'requirement') }}</span>
            </li>
          </ul>
        </section>

        <section v-if="showFavCards" class="profile__block" data-testid="profile-favcards" aria-label="最爱用的卡">
          <h3 class="profile__block-title">最爱用的卡</h3>
          <ul v-if="favCards.length" class="profile__fav-list">
            <li v-for="card in favCards" :key="readString(card, 'name')"
                class="profile__fav" :data-testid="'profile-favcard-' + readString(card, 'name')">
              <span>{{ readString(card, 'name') }}</span>
              <small>{{ readNumber(card, 'uses') ?? 0 }} 次</small>
            </li>
          </ul>
          <p v-else class="profile__private">还没有常用的卡牌记录。</p>
        </section>
        <p v-else class="profile__private" data-testid="profile-favcards-private">该玩家未公开最爱用的卡。</p>

        <section v-if="showHistory" class="profile__block" data-testid="profile-history" aria-label="历史战绩">
          <h3 class="profile__block-title">历史战绩</h3>
          <ul v-if="history.length" class="profile__history">
            <li v-for="row in history" :key="readString(row, 'match_id')"
                class="profile__history-row"
                :data-testid="'profile-history-row-' + readString(row, 'match_id')">
              <span class="profile__history-time">{{ historyTime(row) }}</span>
              <span class="profile__history-opp">
                vs {{ historyOpponent(row) }}
                <small v-if="modeLabel(row.mode)">· {{ modeLabel(row.mode) }}</small>
              </span>
              <b :class="historyResult(row) === '胜' ? 'is-win' : 'is-lose'">{{ historyResult(row) }}</b>
              <button
                v-if="row.has_replay === true"
                type="button"
                class="button button--small"
                :data-testid="'profile-history-replay-' + readString(row, 'match_id')"
                @click="openReplay(readString(row, 'match_id'))"
              >
                回放
              </button>
            </li>
          </ul>
          <p v-else class="profile__private" data-testid="profile-history-empty">{{ historyEmptyText }}</p>
        </section>
        <p v-else class="profile__private" data-testid="profile-history-private">该玩家未公开对局历史。</p>

        <footer class="profile__meta" data-testid="profile-meta">
          <span data-testid="profile-meta-joined">{{ createdAt ? '加入于 ' + createdAt : '加入时间未知' }}</span>
          <span data-testid="profile-meta-rank">{{ winsRank ? '战绩榜第 ' + winsRank + ' 名' : '暂未上榜' }}</span>
          <span data-testid="profile-meta-record">{{ wins }} 胜 {{ losses }} 负</span>
        </footer>
      </article>

      <div class="profile__actions">
        <button v-if="isSelf" type="button" class="button" data-testid="profile-settings-link" @click="openSettings">
          隐私与设置
        </button>
        <button type="button" class="button button--ghost" data-testid="profile-back" @click="back">
          返回排行榜
        </button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.profile {
  gap: 12px;
}

.profile__eyebrow {
  margin: 0 0 4px;
  color: var(--accent);
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.profile__title {
  margin: 0;
  font-size: 28px;
}

.profile__viewing {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}

.profile__state,
.profile__login {
  margin: 0;
  padding: 14px 16px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  background: var(--bg-elevated);
  color: var(--text-muted);
  font-size: 13px;
}

.profile__state--error {
  border-color: var(--danger);
  color: var(--danger);
}

.profile__login h2 {
  margin: 0 0 6px;
  color: var(--text);
  font-size: 18px;
}

.profile__login p {
  margin: 0 0 10px;
}

.profile__card {
  display: grid;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: linear-gradient(160deg, #10283a, #0a1620 70%);
}

.profile__card[data-bg='graphite'] {
  background: linear-gradient(160deg, #232a30, #10151a 70%);
}

.profile__card[data-bg='cyber'] {
  background: linear-gradient(160deg, #2a1840, #0f1a2c 70%);
}

.profile__card[data-bg='lava'] {
  background: linear-gradient(160deg, #3a1a12, #1a0f0c 70%);
}

.profile__hero {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.profile__avatar-wrap {
  display: grid;
  justify-items: center;
  gap: 6px;
  flex: 0 0 auto;
}

.profile__avatar {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  object-fit: cover;
  background: #0b1a24;
  border: 2px solid var(--border);
}

.profile__avatar[data-frame='gold'] {
  border-color: #ffd76a;
}

.profile__avatar[data-frame='silver'] {
  border-color: #c6d3dd;
}

.profile__avatar[data-frame='aurora'] {
  border-color: #6fe0a0;
}

.profile__avatar--empty {
  display: grid;
  place-items: center;
  color: var(--text-muted);
  font-size: 26px;
}

.profile__level {
  padding: 1px 8px;
  border-radius: 999px;
  background: #14303f;
  color: var(--accent);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.profile__who {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.profile__name {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 22px;
}

.profile__name .is-rainbow {
  background: linear-gradient(90deg, #ff8a7a, #ffd76a, #6fe0a0, #37c2d9);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.profile__title-chip {
  padding: 2px 8px;
  border-radius: 999px;
  background: #3a2a10;
  color: #ffd76a;
  font-size: 12px;
}

.profile__status {
  margin: 0;
  color: var(--text);
  font-size: 13px;
}

.profile__signature {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.profile__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;
}

.profile__tag {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  font-size: 11px;
}

.profile__bar-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.profile__bar {
  flex: 1 1 160px;
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: #0b1a24;
}

.profile__bar-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #2a8f68, #6fe0a0);
}

.profile__bar-fill--rank {
  background: linear-gradient(90deg, #b8872e, #ffd76a);
}

.profile__bar-text {
  color: var(--text-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.profile__rank {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: #0b1a24;
}

.profile__rank-label {
  color: #ffd76a;
  font-size: 14px;
}

.profile__stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.profile__stat {
  display: grid;
  gap: 2px;
  padding: 8px 12px;
  border-radius: 8px;
  background: #0b1a24;
}

.profile__stat b {
  font-size: 20px;
  font-variant-numeric: tabular-nums;
}

.profile__stat span {
  color: var(--text-muted);
  font-size: 11px;
}

.profile__block {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: #0b1a24;
}

.profile__block-title {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  margin: 0 0 8px;
  color: var(--text-muted);
  font-size: 11px;
  letter-spacing: 0.14em;
}

.profile__badge-count {
  color: var(--accent);
  letter-spacing: 0;
}

.profile__badge-list,
.profile__fav-list,
.profile__history {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.profile__badge {
  display: grid;
  gap: 2px;
  min-width: 130px;
  max-width: 200px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #10232e;
}

.profile__badge b {
  color: #ffd76a;
  font-size: 13px;
}

.profile__badge span {
  color: var(--text-muted);
  font-size: 11px;
}

.profile__badge.is-locked {
  opacity: 0.55;
}

.profile__badge.is-locked b {
  color: var(--text-muted);
}

.profile__fav {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 12px;
}

.profile__fav small {
  color: var(--text-muted);
}

.profile__history {
  display: grid;
  gap: 6px;
}

.profile__history-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  padding: 6px 10px;
  border-radius: 8px;
  background: #10232e;
  font-size: 12px;
}

.profile__history-time {
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.profile__history-opp {
  flex: 1 1 160px;
}

.profile__history-opp small {
  color: var(--text-muted);
}

.is-win {
  color: #6fe0a0;
}

.is-lose {
  color: #ff8a7a;
}

.profile__private {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.profile__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  padding-top: 8px;
  border-top: 1px solid #14303f;
  color: var(--text-muted);
  font-size: 12px;
}

.profile__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: auto;
}

.button--ghost {
  border-color: var(--border);
  background: transparent;
  color: var(--text-muted);
}

.button--small {
  padding: 3px 9px;
  font-size: 12px;
}

@media (max-width: 640px) {
  .profile__hero {
    flex-direction: column;
    align-items: center;
    text-align: center;
  }

  .profile__name {
    justify-content: center;
  }

  .profile__stats {
    grid-template-columns: 1fr;
  }
}
</style>