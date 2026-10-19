<script setup lang="ts">
import { computed } from 'vue'
import type { BoardCell } from './view'

/**
 * One 6x6 sea (ticket #27). Pure rendering: every flag comes from the view
 * model, which itself only formats store values. The panel never decides a
 * game rule; `attackable` is computed from the server snapshot (my turn +
 * battle phase + attacks left + cell not already shot).
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
  hidden?: boolean
  picking?: boolean
}>()

const emit = defineEmits<{ (event: 'cell', x: number, y: number): void }>()

const selectedSet = computed(() => new Set(props.selected ?? []))
const previewSet = computed(() => new Set(props.preview ?? []))

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
  return parts.join('，')
}

function onCell(cell: BoardCell): void {
  emit('cell', cell.x, cell.y)
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
    <div class="board__grid" role="grid" :aria-label="title">
      <button
        v-for="cell in cells"
        :key="cell.key"
        type="button"
        role="gridcell"
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
            'cell--selected': selectedSet.has(cell.key),
            'cell--preview': previewSet.has(cell.key),
          },
        ]"
        :data-testid="'game-cell-' + board + '-' + cell.x + '-' + cell.y"
        :data-cell="cellState(cell)"
        :data-attackable="cell.attackable ? 'true' : 'false'"
        :aria-label="cellLabel(cell)"
        :aria-disabled="board === 'opponent' && !cell.attackable ? 'true' : 'false'"
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
  gap: 8px;
}

.board__title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--text-muted);
}

.board__subtitle {
  margin: 0;
  font-size: 11px;
  color: var(--text-muted);
}

.board__grid {
  display: grid;
  grid-template-columns: repeat(6, var(--cell, 40px));
  gap: 3px;
  padding: 6px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: radial-gradient(circle at 50% 0%, #0f2a38, #08151d 70%);
  width: fit-content;
}

.board--opponent .board__grid {
  box-shadow: inset 0 0 0 1px rgb(55 194 217 / 25%);
}

.board--picking .board__grid {
  box-shadow: 0 0 0 2px var(--accent);
}

.cell {
  position: relative;
  width: var(--cell, 40px);
  height: var(--cell, 40px);
  padding: 0;
  border: 1px solid #1b3b4c;
  border-radius: 6px;
  background: #0b1f2a;
  color: var(--text-muted);
  font: inherit;
  font-size: 14px;
  line-height: 1;
  cursor: default;
}

.cell--attackable {
  cursor: crosshair;
  border-color: #2b6c80;
}

.cell--attackable:hover {
  background: #17475a;
}

.cell--ship {
  background: #123c4a;
  border-color: #2f7f96;
}

.cell--sunk {
  background: #2a1414;
  border-color: #6b2b26;
  color: var(--danger);
}

.cell--ship-hit,
.cell--hit {
  background: #3a1a16;
  border-color: #8a3a2f;
  color: var(--danger);
}

.cell--miss {
  color: var(--accent);
}

.cell--frozen {
  box-shadow: inset 0 0 0 1px #6fb7ff;
}

.cell--shielded {
  box-shadow: inset 0 0 0 1px #ffd76a;
}

.cell--shield-broken {
  border-color: #ffd76a;
}

.cell--revealed {
  background: #2c2a12;
  border-color: #a08a2c;
}

.cell--hole {
  background: repeating-linear-gradient(45deg, #101820, #101820 4px, #0a1117 4px, #0a1117 8px);
  border-style: dashed;
}

.cell--frozen-area {
  outline: 1px dashed #6fb7ff;
  outline-offset: -2px;
}

.cell--last-stand {
  outline: 1px dashed #ffd76a;
  outline-offset: -2px;
}

.cell--selected {
  box-shadow: 0 0 0 2px var(--accent);
}

.cell--preview {
  background: #1b4d5e;
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
  color: #ffd76a;
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