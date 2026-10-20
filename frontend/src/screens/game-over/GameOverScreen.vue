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
    </header>

    <section v-if="!hasResult" class="game-over__empty" data-testid="game-over-empty">
      <p class="game-over__empty-title">还没有收到本局结算数据</p>
      <p class="game-over__empty-hint">
        从对局结束进入时，这里会显示胜负、双方信息与本局数据；刷新后请返回首页重新进入。
      </p>
    </section>

    <template v-else>
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
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding-top: 8px;
}

/* The hero panel: C+ draws one wide, gold-edged banner with the verdict
   centred under an anchor sigil, then a single "本局数据" panel below it. */
.game-over__head {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  width: 100%;
  max-width: 1120px;
  padding: 20px 30px 22px;
  border: 1px solid rgba(201, 162, 76, 0.55);
  border-radius: var(--radius);
  background:
    radial-gradient(420px 140px at 50% 0%, rgba(201, 162, 76, 0.12), transparent 72%),
    linear-gradient(160deg, rgba(32, 29, 40, 0.88), rgba(18, 20, 36, 0.92));
  box-shadow: 0 0 34px rgba(201, 162, 76, 0.1), var(--shadow-panel);
  text-align: center;
}

.game-over__head::before {
  content: '⚓';
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  margin: 0 auto 6px;
  border: 1px solid rgba(201, 162, 76, 0.6);
  border-radius: 11px;
  background: rgba(11, 13, 24, 0.6);
  color: var(--accent-cyan);
  font-size: 22px;
}

.game-over__eyebrow {
  margin: 0;
  color: #8f9bc4;
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.game-over__title {
  margin: 0;
  color: var(--text-dim);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.26em;
}

.game-over__verdict {
  margin: 2px 0 0;
  font-size: 42px;
  font-weight: 800;
  letter-spacing: 0.14em;
  line-height: 1.1;
}

.game-over[data-outcome='win'] .game-over__verdict {
  color: var(--gold-strong);
  text-shadow: 0 0 26px rgba(201, 162, 76, 0.35);
}

.game-over[data-outcome='lose'] .game-over__verdict {
  color: #ff8a7a;
}

.game-over__summary {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}

.game-over__empty {
  display: grid;
  gap: 8px;
  width: 100%;
  max-width: 1120px;
  padding: 20px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  background: var(--panel);
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
  justify-content: center;
  gap: 8px 16px;
  margin-top: 10px;
  padding: 0;
  border: 0;
  background: transparent;
}

.game-over__player {
  display: grid;
  gap: 1px;
}

.game-over__player--opponent {
  text-align: right;
}

.game-over__player-role {
  color: var(--text-dim);
  font-size: 10px;
  letter-spacing: 0.16em;
}

.game-over__player-name {
  font-size: 14px;
}

.game-over__player-seat {
  color: var(--text-muted);
  font-size: 11px;
}

.game-over__vs {
  color: var(--text-dim);
  font-size: 11px;
  letter-spacing: 0.12em;
}

.game-over__mode {
  margin-left: 6px;
  padding: 3px 10px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  color: var(--text-muted);
  font-size: 11px;
}

.game-over__stats {
  width: 100%;
  max-width: 1120px;
  padding: 14px 24px 8px;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-panel);
}

.game-over__section-title {
  margin: 0 0 2px;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--line-dash);
  color: var(--text);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.26em;
}

.game-over__stat-grid {
  display: block;
  margin: 0;
}

.game-over__stat {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  padding: 11px 2px;
  border-bottom: 1px dashed rgba(42, 51, 88, 0.8);
  background: none;
}

.game-over__stat:last-child {
  border-bottom: 0;
}

.game-over__stat dt {
  color: var(--text-muted);
  font-size: 13px;
}

.game-over__stat dd {
  margin: 0;
  font-size: 15px;
  font-variant-numeric: tabular-nums;
}

.game-over__cards {
  display: grid;
  gap: 14px;
  width: 100%;
  max-width: 1120px;
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
  padding: 16px 20px;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-panel);
}

.game-over__rank-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 0 0 10px;
}

.game-over__rank-delta {
  color: var(--gold-strong);
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
  color: var(--gold-strong);
}

.game-over__bar {
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--bg-sunken);
}

.game-over__bar-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #b8873a, var(--gold-strong));
}

.game-over__rank-note {
  margin: 8px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.game-over__xp,
.game-over__badges {
  padding: 16px 20px;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-panel);
}

.game-over__xp-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 0 0 10px;
}

.game-over__xp-delta {
  color: var(--success);
  font-size: 24px;
  font-variant-numeric: tabular-nums;
}

.game-over__xp-level {
  color: var(--text-muted);
  font-size: 13px;
}

.game-over__bar-fill--xp {
  background: linear-gradient(90deg, #2a8f68, var(--success));
}

.game-over__xp-progress,
.game-over__xp-levelup {
  margin: 6px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.game-over__xp-levelup {
  color: var(--success);
}

.game-over__breakdown {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
  color: var(--text-muted);
  font-size: 12px;
}

.game-over__breakdown b {
  color: var(--success);
}

.game-over__badges {
  width: 100%;
}

.game-over__badge-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.game-over__badge {
  display: grid;
  gap: 2px;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--accent-soft);
}

.game-over__badge b {
  font-size: 12px;
}

.game-over__badge span {
  color: var(--text-muted);
  font-size: 11px;
}

.game-over__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
  padding-top: 4px;
}

.game-over__actions .button {
  min-height: 40px;
  padding: 8px 22px;
}

.game-over__actions [data-testid='game-over-play-again'] {
  border-color: var(--accent-strong);
  background: var(--hero-grad);
  box-shadow: var(--shadow-accent);
  color: #fff;
  font-weight: 600;
}

.button--ghost {
  border-color: var(--border-strong);
  background: rgba(13, 17, 34, 0.72);
  color: var(--text-muted);
}

.game-over__replay-note {
  flex-basis: 100%;
  margin: 0;
  color: var(--text-dim);
  font-size: 12px;
  text-align: center;
}

@media (max-width: 899px) {
  .game-over {
    justify-content: flex-start;
  }
}

@media (max-width: 760px) {
  .game-over {
    gap: 10px;
  }

  .game-over__head {
    padding: 16px 16px 18px;
  }

  .game-over__verdict {
    font-size: 32px;
  }

  .game-over__stats {
    padding: 12px 14px 6px;
  }

  .game-over__players {
    gap: 6px 10px;
  }
}
</style>
