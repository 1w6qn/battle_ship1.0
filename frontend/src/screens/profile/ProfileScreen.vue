<script setup lang="ts">
import ScreenScaffold from '../../components/ScreenScaffold.vue'
</script>

<template>
  <ScreenScaffold
    screen="profile"
    title="档案"
    hint="名片、徽章与战绩（#27 迁移）。"
  >
    <div class="screen__actions">
      <button type="button" class="button" data-testid="profile-primary-action">编辑名片</button>
      <p class="screen__note">
        占位组件：路由 / 错误边界 / 构建产物门禁可用；业务逻辑见后续票据。
      </p>
    </div>
  </ScreenScaffold>
</template>
