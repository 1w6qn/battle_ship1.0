<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { acquireMatchChannel, emitMatchEvent, matchSocket } from '../../realtime/match'
import { useGameStore } from '../../stores/game'
import { useRpsStore } from '../../stores/rps'
import { choiceName, rpsResultView } from './view'

/**
 * Ticket #23: the rock-paper-scissors screen.
 *
 * Data flow (port map 10 section 0.2 / 14 section 1.5):
 *   game_state            -> useGameStore (round, names, seat, state)
 *   rps_result            -> useRpsStore.result (status/winner/choices)
 *   click                 -> rps_choice; the ack only means "received", so the
 *                            waiting state ends on rps_result (or its own 6s
 *                            ack timeout), exactly like static/game.js:11685.
 *   game_state{attacking} -> /game (route names frozen by #21)
 */
const router = useRouter()
const route = useRoute()
const game = useGameStore()
const rps = useRpsStore()

let releaseChannel: (() => void) | null = null
let offError: (() => void) | null = null
let offMessage: (() => void) | null = null

const choices = [
  { value: 'rock', label: '石头', icon: '✊' },
  { value: 'paper', label: '布', icon: '✋' },
  { value: 'scissors', label: '剪刀', icon: '✌' },
] as const

const hasRoom = computed(() => Boolean(game.state.room_id))
const inRound = computed(() => game.state.state === 'rock_paper_scissors')
const canChoose = computed(() => hasRoom.value && inRound.value && !rps.waiting)
const selfName = computed(() => game.state.player_name || '你')
const opponentName = computed(() => game.state.opponent_name || '对手')
const seatLabel = computed(() => game.state.player_seat || '—')
const roundText = computed(() => String(game.state.round || 1))
const resultView = computed(() => rpsResultView(rps.result, game.state.player_id))

function readText(payload: Record<string, unknown>, key: string): string {
  const value = payload[key]
  return typeof value === 'string' ? value : ''
}

function routeForState(state: string): void {
  if (route.name !== 'rps') return
  if (state === 'placing_ships') {
    void router.push({ name: 'placement' })
  } else if (state === 'attacking') {
    void router.push({ name: 'game' })
  } else if (state === 'game_over') {
    void router.push({ name: 'game-over' })
  }
}

onMounted(() => {
  releaseChannel = acquireMatchChannel()
  const socket = matchSocket()
  if (socket) {
    offError = socket.on('error', (payload) => rps.noteNotice(readText(payload, 'message')))
    offMessage = socket.on('message', (payload) => rps.noteNotice(readText(payload, 'message')))
  }
  rps.resetForEntry()
})

onBeforeUnmount(() => {
  offError?.()
  offMessage?.()
  offError = null
  offMessage = null
  releaseChannel?.()
  releaseChannel = null
})

watch(
  () => game.state.state,
  (state) => routeForState(state),
  { immediate: true },
)

async function choose(choice: string): Promise<void> {
  if (!canChoose.value) return
  const socket = matchSocket()
  if (!socket || !socket.socket.connected) {
    rps.noteNotice('连接已断开，正在重连。稍后会自动同步房间状态，再试一次即可。')
    return
  }
  const roomId = game.state.room_id
  const playerId = game.state.player_id
  if (!roomId || !playerId) {
    rps.noteNotice('还没进入房间，请重新创建或加入房间。')
    return
  }
  rps.beginChoice(choice)
  try {
    const ack = await emitMatchEvent(socket, 'rps_choice', {
      room_id: roomId,
      player_id: playerId,
      choice,
    })
    if (!rps.waiting) return
    rps.settleAck(ack?.status === 'success', typeof ack?.message === 'string' ? ack.message : '')
  } catch (error) {
    if (!rps.waiting) return
    rps.settleAck(false, error instanceof Error ? error.message : '')
  }
}

function returnHome(): void {
  void router.push({ name: 'start' })
}
</script>

<template>
  <section
    class="screen rps"
    data-screen="rps"
    data-testid="screen-rps"
    aria-labelledby="screen-rps-title"
  >
    <header class="rps__head">
      <p class="rps__eyebrow">P4 · 猜拳</p>
      <h1 id="screen-rps-title" class="rps__title" data-testid="rps-heading">猜拳决定攻击顺序</h1>
      <p class="rps__round">
        第 <b data-testid="rps-round">{{ roundText }}</b> 回合 · 选择一种手势
      </p>
    </header>

    <div class="rps__players">
      <span class="rps__player">你 <b data-testid="rps-self">{{ selfName }}</b></span>
      <span class="rps__seat" aria-label="座位">{{ seatLabel }}</span>
      <span class="rps__vs" aria-hidden="true">VS</span>
      <span class="rps__player rps__player--opponent">
        对手 <b data-testid="rps-opponent">{{ opponentName }}</b>
      </span>
    </div>

    <p v-if="!hasRoom" class="rps__empty" data-testid="rps-empty" role="status">
      还没进入房间，先创建或加入房间再猜拳。
    </p>

    <div class="rps__choices" role="group" aria-label="选择手势">
      <button
        v-for="choice in choices"
        :key="choice.value"
        type="button"
        class="rps__choice"
        :class="{ 'is-picked': rps.pendingChoice === choice.value }"
        :data-testid="'rps-choice-' + choice.value"
        :aria-pressed="rps.pendingChoice === choice.value ? 'true' : 'false'"
        :disabled="!canChoose"
        @click="choose(choice.value)"
      >
        <span class="rps__icon" aria-hidden="true">{{ choice.icon }}</span>
        <span class="rps__label">{{ choice.label }}</span>
      </button>
    </div>

    <p
      v-if="rps.waiting"
      class="rps__waiting"
      data-testid="rps-waiting"
      role="status"
      aria-live="polite"
    >
      已出拳，等待对手… 你选择了
      <b data-testid="rps-waiting-choice">{{ choiceName(rps.pendingChoice) }}</b>
      <b class="rps__countdown" data-testid="rps-waiting-countdown">{{ rps.countdown }}s</b>
    </p>

    <p v-if="rps.error" class="rps__error" data-testid="rps-error" role="alert">
      {{ rps.error }}
    </p>

    <div
      v-if="resultView"
      class="rps__result"
      :class="{ 'is-tie': resultView.tie }"
      data-testid="rps-result"
      role="status"
      aria-live="polite"
    >
      <p class="rps__verdict" data-testid="rps-result-verdict">{{ resultView.verdict }}</p>
      <p v-if="resultView.hasChoices" class="rps__reveal">
        <span class="rps__reveal-item">
          你 <b data-testid="rps-result-self">{{ resultView.self }}</b>
        </span>
        <span class="rps__reveal-item">
          对手 <b data-testid="rps-result-opponent">{{ resultView.opponent }}</b>
        </span>
      </p>
    </div>

    <button
      v-if="!hasRoom"
      type="button"
      class="button button--ghost rps__home"
      data-testid="rps-return-home"
      @click="returnHome"
    >
      返回首页
    </button>
  </section>
</template>

<style scoped>
.rps {
  gap: 12px;
}

.rps__head {
  display: grid;
  gap: 2px;
}

.rps__eyebrow {
  margin: 0;
  color: var(--accent);
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.rps__title {
  margin: 0;
  font-size: 26px;
}

.rps__round {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}

.rps__round b {
  color: var(--text);
  font-size: 16px;
  font-variant-numeric: tabular-nums;
}

.rps__players {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
  padding: 8px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-elevated);
  font-size: 14px;
}

.rps__player--opponent {
  margin-left: auto;
}

.rps__seat {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  font-size: 12px;
}

.rps__vs {
  color: var(--text-muted);
  font-size: 11px;
  letter-spacing: 0.12em;
}

.rps__empty {
  margin: 0;
  padding: 10px 14px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  font-size: 13px;
}

.rps__choices {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  max-width: 560px;
}

.rps__choice {
  display: grid;
  place-items: center;
  gap: 6px;
  padding: 16px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: linear-gradient(160deg, #0d2230, #0b1a24 75%);
  color: var(--text);
  font: inherit;
  cursor: pointer;
  transition: transform 140ms ease, border-color 140ms ease, background 140ms ease;
}

.rps__choice:hover:not(:disabled) {
  border-color: var(--accent);
  background: #113140;
  transform: translateY(-2px);
}

.rps__choice.is-picked {
  border-color: var(--accent);
  background: linear-gradient(160deg, #1c5f78, #14414f);
  box-shadow: 0 0 0 1px rgb(120 220 240 / 35%), 0 8px 22px rgb(0 0 0 / 35%);
}

.rps__choice:disabled {
  cursor: default;
  opacity: 0.62;
}

.rps__choice:disabled.is-picked {
  opacity: 1;
}

.rps__icon {
  font-size: 30px;
  line-height: 1;
}

.rps__label {
  font-size: 14px;
}

.rps__waiting {
  margin: 0;
  padding: 8px 12px;
  border: 1px solid #2a5568;
  border-radius: 8px;
  background: #0b1a24;
  color: var(--accent);
  font-size: 13px;
}

.rps__waiting b {
  color: var(--text);
}

.rps__countdown {
  margin-left: 6px;
  font-variant-numeric: tabular-nums;
}

.rps__error {
  margin: 0;
  padding: 8px 12px;
  border: 1px solid #7a2f2a;
  border-radius: 8px;
  background: #2a1414;
  color: #ff9c8f;
  font-size: 13px;
}

.rps__result {
  display: grid;
  gap: 6px;
  padding: 12px 16px;
  border: 1px solid #2a8f68;
  border-radius: var(--radius);
  background: linear-gradient(160deg, rgb(42 143 104 / 20%), rgb(42 143 104 / 6%));
  animation: rps-reveal 220ms ease-out;
}

.rps__result.is-tie {
  border-color: #7a6a2a;
  background: linear-gradient(160deg, rgb(122 106 42 / 22%), rgb(122 106 42 / 6%));
}

.rps__verdict {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
}

.rps__result.is-tie .rps__verdict {
  color: #ffd76a;
}

.rps__reveal {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
}

.rps__reveal b {
  color: var(--text);
  font-size: 15px;
}

.rps__home {
  align-self: flex-start;
}

@keyframes rps-reveal {
  from {
    opacity: 0;
    transform: translateY(6px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
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
  .rps {
    gap: 10px;
    padding: 12px;
  }

  .rps__title {
    font-size: 22px;
  }

  .rps__choice {
    padding: 12px 6px;
  }

  .rps__icon {
    font-size: 26px;
  }
}

@media (max-height: 680px) {
  .rps__eyebrow {
    display: none;
  }

  .rps__title {
    font-size: 20px;
  }

  .rps__choice {
    padding: 10px 6px;
  }

  .rps__icon {
    font-size: 24px;
  }
}
</style>
