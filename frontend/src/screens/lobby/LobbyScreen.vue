<script setup lang="ts">
import ScreenScaffold from '../../components/ScreenScaffold.vue'
</script>

<template>
  <ScreenScaffold
    screen="lobby"
    title="大厅"
    hint="房间列表与房间内聊天（#26 迁移）。"
  >
    <div class="screen__actions">
      <button type="button" class="button" data-testid="lobby-primary-action">刷新大厅</button>
      <p class="screen__note">
        占位组件：路由 / 错误边界 / 构建产物门禁可用；业务逻辑见后续票据。
      </p>
    </div>
  </ScreenScaffold>
</template>
