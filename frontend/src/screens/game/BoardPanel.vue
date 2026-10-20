<script setup lang="ts">
import { computed, ref } from 'vue'
import type { BoardCell } from './view'

/**
 * One 6x6 sea (ticket #27, keyboard + legal-range pass in #47).
 *
 * Pure rendering: every flag comes from the view model, which itself only
 * formats store values. The panel never decides a game rule; `attackable` and
 * `legal` are computed from the server snapshot by the screen.
 *
 * #47 adds two presentation-only behaviours: a roving cursor so arrow keys +
 * Enter can fire (the grid keeps one tab stop, cells stay programmatic
 * buttons for the gates) and a `legal` highlight set for the target banner.
 */
const props = defineProps<{
  board: 'self' | 'opponent'
  boardTestid: string
  titleTestid: string
  title: string
  subtitle?: string
  cells: BoardCell[]
  selected?: string[]
  preview?: string[]
  legal?: string[]
  hidden?: boolean
  picking?: boolean
  interactive?: boolean
}>()

const emit = defineEmits<{ (event: 'cell', x: number, y: number): void }>()

const selectedSet = computed(() => new Set(props.selected ?? []))
const previewSet = computed(() => new Set(props.preview ?? []))
const legalSet = computed(() => new Set(props.legal ?? []))
const cursor = ref(0)
const grid = ref<HTMLElement | null>(null)

function cellState(cell: BoardCell): string {
  if (cell.hit && cell.ship) return 'ship-hit'
  if (cell.sunk) return 'ship-sunk'
  if (cell.hit) return 'hit'
  if (cell.miss) return 'miss'
  if (cell.shielded) return 'ship-shielded'
  if (cell.ship) return 'ship'
  return 'empty'
}

function cellLabel(cell: BoardCell): string {
  const parts = ['第 ' + (cell.x + 1) + ' 列 第 ' + (cell.y + 1) + ' 行']
  if (cell.ship) parts.push(cell.sunk ? '已沉没的战舰' : '你的战舰')
  if (cell.frozen) parts.push('被冻结')
  if (cell.shielded) parts.push('带护盾')
  if (cell.invincible) parts.push('无敌')
  if (cell.hit) parts.push('命中')
  if (cell.miss) parts.push('未命中')
  if (cell.shieldBroken) parts.push('护盾挡下这一炮')
  if (cell.revealed) parts.push('已探明敌舰位置')
  if (cell.hole) parts.push('被神威扣掉，无法攻击')
  if (cell.frozenArea) parts.push('冻结区域')
  if (cell.lastStand) parts.push('绝处逢生候选格')
  if (cell.attackable) parts.push('可攻击')
  if (legalSet.value.has(cell.key)) parts.push('可选择')
  return parts.join('，')
}

function onCell(cell: BoardCell): void {
  emit('cell', cell.x, cell.y)
}

function focusIndex(index: number): void {
  cursor.value = Math.min(Math.max(index, 0), props.cells.length - 1)
  const node = grid.value?.querySelectorAll<HTMLElement>('[role="gridcell"]')[cursor.value]
  node?.focus()
}

/** Arrow keys move the cursor; Enter/Space fires the focused cell (#47). */
function onKeydown(event: KeyboardEvent): void {
  const current = props.cells[cursor.value]
  if (!current) return
  const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -6, ArrowDown: 6 }[event.key]
  if (step !== undefined) {
    event.preventDefault()
    const next = cursor.value + step
    if (next >= 0 && next < props.cells.length) focusIndex(next)
    return
  }
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    emit('cell', current.x, current.y)
  }
}

function onCellFocus(index: number): void {
  cursor.value = index
}
</script>

<template>
  <section
    v-show="!hidden"
    class="board"
    :class="['board--' + board, { 'board--picking': picking }]"
    :data-testid="boardTestid"
    :data-board="board"
    :aria-label="title"
  >
    <header class="board__head">
      <h2 class="board__title" :data-testid="titleTestid">{{ title }}</h2>
      <p v-if="subtitle" class="board__subtitle">{{ subtitle }}</p>
    </header>
    <div
      ref="grid"
      class="board__grid"
      role="grid"
      tabindex="0"
      :aria-label="title + '，方向键移动，Enter 开炮'"
      @keydown="onKeydown"
    >
      <button
        v-for="(cell, index) in cells"
        :key="cell.key"
        type="button"
        role="gridcell"
        tabindex="-1"
        class="cell"
        :class="[
          'cell--' + cellState(cell),
          {
            'cell--ship': cell.ship,
            'cell--sunk': cell.sunk,
            'cell--frozen': cell.frozen,
            'cell--shielded': cell.shielded,
            'cell--invincible': cell.invincible,
            'cell--hit': cell.hit,
            'cell--miss': cell.miss,
            'cell--shield-broken': cell.shieldBroken,
            'cell--revealed': cell.revealed,
            'cell--hole': cell.hole,
            'cell--frozen-area': cell.frozenArea,
            'cell--last-stand': cell.lastStand,
            'cell--attackable': cell.attackable,
            'cell--legal': legalSet.has(cell.key),
            'cell--selected': selectedSet.has(cell.key),
            'cell--preview': previewSet.has(cell.key),
            'cell--cursor': cursor === index,
          },
        ]"
        :data-testid="'game-cell-' + board + '-' + cell.x + '-' + cell.y"
        :data-cell="cellState(cell)"
        :data-attackable="cell.attackable ? 'true' : 'false'"
        :data-legal="legalSet.has(cell.key) ? 'true' : 'false'"
        :aria-label="cellLabel(cell)"
        :aria-disabled="board === 'opponent' && !cell.attackable ? 'true' : 'false'"
        @focus="onCellFocus(index)"
        @click="onCell(cell)"
      >
        <span v-if="cell.sunk || cell.hit" class="cell__mark">✕</span>
        <span v-else-if="cell.miss" class="cell__mark cell__mark--miss">○</span>
        <span v-else-if="cell.ship" class="cell__mark cell__mark--ship">■</span>
        <span v-if="cell.shielded" class="cell__badge" title="带护盾">盾</span>
        <span v-if="cell.frozen" class="cell__badge cell__badge--frozen" title="被冻结">冻</span>
        <span v-if="cell.shieldBroken" class="cell__badge cell__badge--broken" title="护盾挡下这一炮">破</span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.board {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.board__head {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px;
}

.board__title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--text-secondary);
}

.board__subtitle {
  margin: 0;
  font-size: 12px;
  color: var(--text-tertiary);
}

.board__grid {
  display: grid;
  grid-template-columns: repeat(6, var(--cell, 40px));
  gap: 3px;
  padding: 6px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  background: radial-gradient(120% 120% at 50% 0%, var(--surface-chamber), var(--surface-sea) 72%);
  width: fit-content;
  outline: none;
}

.board__grid:focus-visible {
  box-shadow: 0 0 0 2px var(--focus-ring);
}

.board--opponent .board__grid {
  box-shadow: inset 0 0 0 1px var(--role-enemy-soft);
}

.board--picking .board__grid {
  box-shadow: 0 0 0 2px var(--role-action);
}

.cell {
  position: relative;
  width: var(--cell, 40px);
  height: var(--cell, 40px);
  padding: 0;
  border: 1px solid rgba(98, 210, 232, 0.12);
  border-radius: 6px;
  background: var(--surface-deck);
  color: var(--text-tertiary);
  font: inherit;
  font-size: 14px;
  line-height: 1;
  cursor: default;
}

.cell--attackable {
  cursor: crosshair;
  border-color: var(--role-enemy);
}

.cell--attackable:hover,
.cell--cursor {
  background: var(--role-enemy-soft);
}

.cell--legal {
  box-shadow: inset 0 0 0 1px var(--role-action);
}

.cell--ship {
  background: #7f93a3;
  border-color: #b8cbd6;
  color: #08131a;
}

.cell--sunk {
  background: #2a1414;
  border-color: #6b2b26;
  color: var(--role-enemy);
}

.cell--ship-hit,
.cell--hit {
  background: #3a1a16;
  border-color: #8a3a2f;
  color: var(--role-enemy);
}

.cell--miss {
  color: var(--role-self);
}

.cell--frozen {
  box-shadow: inset 0 0 0 1px #6fb7ff;
}

.cell--shielded {
  box-shadow: inset 0 0 0 1px var(--role-action);
}

.cell--shield-broken {
  border-color: var(--role-action);
}

.cell--revealed {
  background: rgba(240, 182, 78, 0.28);
  border-color: rgba(240, 182, 78, 0.6);
}

.cell--hole {
  background: repeating-linear-gradient(45deg, #0a141d, #0a141d 4px, #05101a 4px, #05101a 8px);
  border-style: dashed;
}

.cell--frozen-area {
  outline: 1px dashed #6fb7ff;
  outline-offset: -2px;
}

.cell--last-stand {
  outline: 1px dashed var(--role-action);
  outline-offset: -2px;
}

.cell--selected {
  box-shadow: 0 0 0 2px var(--role-action);
}

.cell--preview {
  background: var(--role-action-soft);
}

.cell__mark {
  pointer-events: none;
  font-weight: 700;
}

.cell__mark--miss {
  font-size: 12px;
}

.cell__mark--ship {
  font-size: 10px;
  opacity: 0.55;
}

.cell__badge {
  position: absolute;
  right: 1px;
  bottom: 0;
  font-size: 9px;
  line-height: 1;
  color: var(--role-action);
}

.cell__badge--frozen {
  color: #6fb7ff;
}

.cell__badge--broken {
  left: 1px;
  right: auto;
}

@media (max-width: 719px) {
  .board__grid {
    gap: 2px;
    padding: 4px;
  }
}
</style>
