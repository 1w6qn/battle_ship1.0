<script setup lang="ts">
import ScreenScaffold from '../../components/ScreenScaffold.vue'
</script>

<template>
  <ScreenScaffold
    screen="game"
    title="对局"
    hint="双棋盘、手牌、连锁与浮层（#24/#25 迁移）。"
  >
    <div class="screen__actions">
      <button type="button" class="button" data-testid="game-primary-action">结束回合</button>
      <p class="screen__note">
        占位组件：路由 / 错误边界 / 构建产物门禁可用；业务逻辑见后续票据。
      </p>
    </div>
  </ScreenScaffold>
</template>
