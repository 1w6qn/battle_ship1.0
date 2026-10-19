<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { acquireSettlementChannel } from '../../realtime/settlement'
import { useGameStore } from '../../stores/game'
import { useResultStore } from '../../stores/result'
import {
  modeText,
  outcomeOf,
  progressPercent,
  readArray,
  readBoolean,
  readNumber,
  readObject,
  readString,
  signed,
  summaryText,
  toObjects,
  verdictText,
  type Outcome,
} from './view'

/**
 * Ticket #22: the settlement screen (sample screen for the P3 migration).
 *
 * The view model lives in the Pinia stores; this component only renders it.
 * game_over arrives over the real socket channel, while xp/rank/badges are
 * optional follow-ups. A direct deep link (or a refresh after the server state
 * is gone) must never leave a white page, so the empty state is part of the
 * contract.
 */
const router = useRouter()
const game = useGameStore()
const result = useResultStore()

let releaseChannel: (() => void) | null = null

onMounted(() => {
  releaseChannel = acquireSettlementChannel()
})

onBeforeUnmount(() => {
  releaseChannel?.()
  releaseChannel = null
})

const gameOver = computed(() => result.gameOver)
const hasResult = computed(() => gameOver.value !== null)
const matchId = computed(() => result.gameOverMatchId)
const outcome = computed<Outcome>(() => outcomeOf(gameOver.value, game.state.player_id))
const verdict = computed(() => verdictText(outcome.value))
const summary = computed(() => {
  const record = gameOver.value
  if (!record) return ''
  return summaryText(record, outcome.value, game.state.round)
})

const selfName = computed(() => game.state.player_name || '你')
const opponentName = computed(() => game.state.opponent_name || '对手')
const seatLabel = computed(() => game.state.player_seat || '—')
const mode = computed(() => modeText(game.state.ranked, game.state.mode))

const attacks = computed(() => (Array.isArray(game.state.attacks) ? game.state.attacks : []))
const hits = computed(() => attacks.value.filter((cell) => cell && cell.hit).length)
const roundText = computed(() => (hasResult.value && game.state.round > 0 ? String(game.state.round) : '—'))
const fireText = computed(() => (hasResult.value && attacks.value.length ? hits.value + ' / ' + attacks.value.length : '—'))
const shipsText = computed(() =>
  hasResult.value ? game.state.remaining_ships + ' / ' + game.state.opponent_remaining_ships : '—',
)

const rank = computed(() => result.rank)
const rankDeltaText = computed(() => signed(readNumber(rank.value, 'delta') ?? 0))
const rankRole = computed(() => {
  const role = readString(rank.value, 'role')
  if (role === 'winner') return '胜方'
  if (role === 'loser') return '败方'
  return ''
})
const rankBeforeLabel = computed(() => readString(readObject(rank.value, 'before'), 'label') || '—')
const rankAfterLabel = computed(() => readString(readObject(rank.value, 'after'), 'label') || '—')
const rankFill = computed(() => {
  const after = readObject(rank.value, 'after')
  return progressPercent(readNumber(after, 'progress'), readNumber(after, 'sub_points'))
})
const rankNote = computed(() => {
  if (!rank.value) return ''
  if (readBoolean(rank.value, 'clamped')) return '已到最低分，本局不再扣分'
  if (readBoolean(rank.value, 'admiral_promoted')) return '晋升大舰长'
  if (readBoolean(rank.value, 'admiral_demoted')) return '大舰长资格已失效'
  if (readBoolean(rank.value, 'promoted')) return '段位提升'
  if (readBoolean(rank.value, 'demoted')) return '段位下降'
  return ''
})

const xp = computed(() => result.xp)
const xpBefore = computed(() => readObject(xp.value, 'before'))
const xpAfter = computed(() => readObject(xp.value, 'after'))
const xpDeltaText = computed(() => '+' + (readNumber(xp.value, 'delta') ?? 0))
const xpLevelText = computed(() => 'Lv.' + (readNumber(xpAfter.value, 'level') ?? 1))
const xpNeed = computed(() => readNumber(xpAfter.value, 'need') ?? 0)
const xpInto = computed(() => readNumber(xpAfter.value, 'into') ?? 0)
const xpProgressText = computed(() => (xpNeed.value > 0 ? xpInto.value + ' / ' + xpNeed.value : '满级'))
const xpFill = computed(() => (xpNeed.value > 0 ? progressPercent(xpInto.value, xpNeed.value) : 100))
const xpLevelUpText = computed(() => {
  const before = readNumber(xpBefore.value, 'level')
  const after = readNumber(xpAfter.value, 'level')
  return before !== null && after !== null && after > before
    ? '升级！Lv.' + before + ' → Lv.' + after
    : ''
})
const xpBreakdown = computed(() =>
  toObjects(readArray(xp.value, 'breakdown')).map((item) => ({
    label: readString(item, 'label'),
    xp: readNumber(item, 'xp') ?? 0,
  })),
)
const achievementItems = computed(() => result.achievements)

function leaveResult(): void {
  result.reset()
  game.reset()
  void router.push({ name: 'start' })
}

function playAgain(): void {
  leaveResult()
}

function returnHome(): void {
  leaveResult()
}

function openReplay(): void {
  const id = matchId.value
  if (!id) return
  void router.push({ name: 'replay', query: { match_id: id } })
}
</script>

<template>
  <section
    class="screen game-over"
    data-screen="game-over"
    data-testid="screen-game-over"
    :data-outcome="outcome"
    aria-labelledby="screen-game-over-title"
  >
    <header class="game-over__head">
      <p class="game-over__eyebrow">{{ hasResult ? mode + ' · 结算' : 'P3 · 结算' }}</p>
      <h1 id="screen-game-over-title" class="game-over__title" data-testid="game-over-heading">结算</h1>
      <p v-if="hasResult" class="game-over__verdict" data-testid="game-over-verdict">{{ verdict }}</p>
      <p v-if="hasResult" class="game-over__summary" data-testid="game-over-reason">{{ summary }}</p>
    </header>

    <section v-if="!hasResult" class="game-over__empty" data-testid="game-over-empty">
      <p class="game-over__empty-title">还没有收到本局结算数据</p>
      <p class="game-over__empty-hint">
        从对局结束进入时，这里会显示胜负、双方信息与本局数据；刷新后请返回首页重新进入。
      </p>
    </section>

    <template v-else>
      <section class="game-over__players" data-testid="game-over-players" aria-label="双方信息">
        <div class="game-over__player">
          <span class="game-over__player-role">你</span>
          <b class="game-over__player-name" data-testid="game-over-self">{{ selfName }}</b>
          <span class="game-over__player-seat">{{ seatLabel }}</span>
        </div>
        <div class="game-over__vs" aria-hidden="true">VS</div>
        <div class="game-over__player game-over__player--opponent">
          <span class="game-over__player-role">对手</span>
          <b class="game-over__player-name" data-testid="game-over-opponent">{{ opponentName }}</b>
        </div>
        <span class="game-over__mode" data-testid="game-over-mode">{{ mode }}</span>
      </section>

      <section class="game-over__stats" data-testid="game-over-stats" aria-label="本局数据">
        <h2 class="game-over__section-title">本 局 数 据</h2>
        <dl class="game-over__stat-grid">
          <div class="game-over__stat">
            <dt>回合</dt>
            <dd data-testid="game-over-stat-round">{{ roundText }}</dd>
          </div>
          <div class="game-over__stat">
            <dt>命中 / 开火</dt>
            <dd data-testid="game-over-stat-fire">{{ fireText }}</dd>
          </div>
          <div class="game-over__stat">
            <dt>剩余战舰</dt>
            <dd data-testid="game-over-stat-ships">{{ shipsText }}</dd>
          </div>
        </dl>
      </section>

      <div class="game-over__cards">
        <section v-if="rank" class="game-over__rank" data-testid="game-over-rank" aria-label="段位变化">
          <h2 class="game-over__section-title">段 位</h2>
          <p class="game-over__rank-head">
            <b class="game-over__rank-delta" data-testid="game-over-rank-delta">{{ rankDeltaText }}</b>
            <span class="game-over__rank-role" data-testid="game-over-rank-role">{{ rankRole }}</span>
          </p>
          <div class="game-over__rank-tiers">
            <span class="game-over__rank-label" data-testid="game-over-rank-before">{{ rankBeforeLabel }}</span>
            <span class="game-over__rank-arrow" aria-hidden="true">→</span>
            <span class="game-over__rank-label game-over__rank-label--after" data-testid="game-over-rank-after">
              {{ rankAfterLabel }}
            </span>
          </div>
          <div class="game-over__bar" role="img" :aria-label="'段位进度 ' + rankFill + '%'">
            <div class="game-over__bar-fill" data-testid="game-over-rank-fill" :style="{ width: rankFill + '%' }"></div>
          </div>
          <p v-if="rankNote" class="game-over__rank-note" data-testid="game-over-rank-note">{{ rankNote }}</p>
        </section>

        <section v-if="xp" class="game-over__xp" data-testid="game-over-xp" aria-label="本局经验">
          <h2 class="game-over__section-title">经 验</h2>
          <p class="game-over__xp-head">
            <b class="game-over__xp-delta" data-testid="game-over-xp-delta">{{ xpDeltaText }}</b>
            <span class="game-over__xp-level" data-testid="game-over-xp-level">{{ xpLevelText }}</span>
          </p>
          <div class="game-over__bar" role="img" :aria-label="'经验进度 ' + xpFill + '%'">
            <div class="game-over__bar-fill game-over__bar-fill--xp" data-testid="game-over-xp-fill" :style="{ width: xpFill + '%' }"></div>
          </div>
          <p class="game-over__xp-progress" data-testid="game-over-xp-progress">{{ xpProgressText }}</p>
          <p v-if="xpLevelUpText" class="game-over__xp-levelup" data-testid="game-over-xp-levelup">{{ xpLevelUpText }}</p>
          <ul v-if="xpBreakdown.length" class="game-over__breakdown">
            <li v-for="row in xpBreakdown" :key="row.label">
              <span>{{ row.label }}</span>
              <b>+{{ row.xp }}</b>
            </li>
          </ul>
        </section>

        <section v-if="achievementItems.length" class="game-over__badges" data-testid="game-over-achievements" aria-label="本局解锁徽章">
          <h2 class="game-over__section-title">本 局 徽 章</h2>
          <ul class="game-over__badge-list">
            <li
              v-for="item in achievementItems"
              :key="readString(item, 'id')"
              class="game-over__badge"
              :data-testid="'game-over-achievement-' + readString(item, 'id')"
            >
              <b>{{ readString(item, 'name') }}</b>
              <span>{{ readString(item, 'desc') }}</span>
            </li>
          </ul>
        </section>
      </div>
    </template>

    <footer class="game-over__actions">
      <button type="button" class="button" data-testid="game-over-play-again" @click="playAgain">
        再来一局
      </button>
      <button v-if="matchId" type="button" class="button button--ghost" data-testid="game-over-replay" @click="openReplay">
        本局回放
      </button>
      <button type="button" class="button button--ghost" data-testid="game-over-return-home" @click="returnHome">
        返回首页
      </button>
      <p v-if="hasResult && !matchId" class="game-over__replay-note" data-testid="game-over-replay-note">
        本局没有可回放的权威记录。
      </p>
    </footer>
  </section>
</template>

<style scoped>
.game-over {
  gap: 12px;
}

.game-over__eyebrow {
  margin: 0 0 4px;
  color: var(--accent);
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.game-over__title {
  margin: 0;
  font-size: 28px;
}

.game-over__verdict {
  margin: 4px 0 0;
  font-size: clamp(28px, 5vw, 42px);
  font-weight: 800;
  letter-spacing: 0.14em;
  line-height: 1.1;
}

.game-over[data-outcome='win'] .game-over__verdict {
  color: #ffd76a;
}

.game-over[data-outcome='lose'] .game-over__verdict {
  color: #ff8a7a;
}

.game-over__summary {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 14px;
}

.game-over__empty {
  display: grid;
  gap: 8px;
  padding: 20px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  background: rgb(13 27 38 / 60%);
}

.game-over__empty-title {
  margin: 0;
  font-size: 18px;
}

.game-over__empty-hint {
  margin: 0;
  max-width: 52ch;
  color: var(--text-muted);
  font-size: 13px;
}

.game-over__players {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 18px;
  padding: 10px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-elevated);
}

.game-over__player {
  display: grid;
  gap: 2px;
}

.game-over__player--opponent {
  text-align: right;
}

.game-over__player-role {
  color: var(--text-muted);
  font-size: 11px;
  letter-spacing: 0.16em;
}

.game-over__player-name {
  font-size: 18px;
}

.game-over__player-seat {
  color: var(--text-muted);
  font-size: 12px;
}

.game-over__vs {
  color: var(--text-muted);
  font-size: 12px;
  letter-spacing: 0.12em;
}

.game-over__mode {
  margin-left: auto;
  padding: 3px 9px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--accent);
  font-size: 12px;
}

.game-over__stats {
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-elevated);
}

.game-over__section-title {
  margin: 0 0 8px;
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.22em;
}

.game-over__stat-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
}

.game-over__stat {
  padding: 6px 10px;
  border-radius: 8px;
  background: #0b1a24;
}

.game-over__stat dt {
  color: var(--text-muted);
  font-size: 12px;
}

.game-over__stat dd {
  margin: 2px 0 0;
  font-size: 20px;
  font-variant-numeric: tabular-nums;
}

.game-over__cards {
  display: grid;
  gap: 12px;
}

@media (min-width: 900px) {
  .game-over__cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .game-over__badges {
    grid-column: 1 / -1;
  }
}

.game-over__rank {
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-elevated);
}

.game-over__rank-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 0 0 10px;
}

.game-over__rank-delta {
  color: #ffd76a;
  font-size: 24px;
  font-variant-numeric: tabular-nums;
}

.game-over__rank-role,
.game-over__rank-arrow {
  color: var(--text-muted);
  font-size: 12px;
}

.game-over__rank-tiers {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  margin-bottom: 8px;
}

.game-over__rank-label {
  font-size: 14px;
}

.game-over__rank-label--after {
  color: #ffd76a;
}

.game-over__bar {
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: #0b1a24;
}

.game-over__bar-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #b8872e, #ffd76a);
}

.game-over__rank-note {
  margin: 8px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.game-over__xp,
.game-over__badges {
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-elevated);
}

.game-over__xp-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 0 0 10px;
}

.game-over__xp-delta {
  color: #6fe0a0;
  font-size: 24px;
  font-variant-numeric: tabular-nums;
}

.game-over__xp-level {
  color: var(--text-muted);
  font-size: 13px;
}

.game-over__bar-fill--xp {
  background: linear-gradient(90deg, #2a8f68, #6fe0a0);
}

.game-over__xp-progress,
.game-over__xp-levelup {
  margin: 6px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.game-over__xp-levelup {
  color: #6fe0a0;
}

.game-over__breakdown,
.game-over__badge-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
  color: var(--text-muted);
  font-size: 12px;
}

.game-over__breakdown li {
  display: flex;
  gap: 5px;
}

.game-over__breakdown b {
  color: var(--text);
}

.game-over__badge {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #0b1a24;
}

.game-over__badge b {
  color: #ffd76a;
  font-size: 13px;
}

.game-over__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: auto;
  padding-top: 8px;
}

.game-over__replay-note {
  flex-basis: 100%;
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.button--ghost {
  border-color: var(--border);
  background: transparent;
  color: var(--text-muted);
}

.button--ghost:hover {
  background: #14303f;
  color: var(--text);
}

@media (max-width: 520px) {
  .game-over__stat-grid {
    grid-template-columns: 1fr;
  }

  .game-over__player--opponent {
    text-align: left;
  }

  .game-over__mode {
    margin-left: 0;
  }
}
</style>
