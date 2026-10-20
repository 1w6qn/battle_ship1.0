/**
 * Card-face art (ticket #33).
 *
 * The legacy card faces already live in the repository at
 * `static/card_faces/<slug>.webp`. Vite imports them from there at build time
 * (content-hashed assets copied into dist), so the SPA stays offline-capable and
 * we do not duplicate ~20 MB of art inside `frontend/`.
 *
 * The name -> slug table mirrors the generated `static/card_art_map.js` (48
 * unique card names). The browser gate asserts coverage, so a missing entry
 * fails loudly instead of silently rendering a blank card.
 */

const ART_MODULES = import.meta.glob('../../../static/card_faces/*.webp', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>

const CARD_ART_SLUGS: Record<string, string> = {
  '亡羊补牢': 'wangyang-bulao',
  '仁王之盾': 'renwang-zhidun',
  '余音绕梁': 'yuyin-raoliang',
  '卧薪尝胆': 'woxin-changdan',
  '回光返照': 'huiguang-fanzhao',
  '守株待兔': 'shouzhu-daitu',
  '无中生有': 'wuzhongshengyou',
  '无暇圣心': 'wuxia-shengxin',
  '极限增援': 'jixian-zengyuan',
  '桃园结义': 'taoyuan-jieyi',
  '火力全开': 'huoli-quankai',
  '灵气复苏': 'lingqi-fusu',
  '败者食尘': 'baizhe-shichen',
  '伊甸园': 'yidianyuan',
  '兵粮寸断': 'bingliang-cunduan',
  '命运骰子': 'mingyun-shaizi',
  '教皇旨意': 'jiaohuang-zhiyi',
  '无忧梦呓': 'wuyou-mengyi',
  '禁忌果实': 'jinji-guoshi',
  'Freezing！': 'freezing',
  '五险一金': 'wuxian-yijin',
  '克苏鲁之眼': 'kesulu-zhiyan',
  '冻结': 'dongjie',
  '探测雷达': 'tance-leida',
  '明智埋葬': 'mingzhi-maizang',
  '溅射': 'jianshe',
  '看破！': 'kanpo',
  '硫磺火焰': 'liuhuang-huoyan',
  '神威！': 'shenwei',
  '越战越勇': 'yuezhan-yueyong',
  '轰炸': 'hongzha',
  '雷达子弹': 'leida-zidan',
  '饮血': 'yinxue',
  '恶魔契约': 'emo-qiyue',
  '八方来财': 'bafang-laicai',
  '加百列之光': 'jiabailie-zhiguang',
  '增援': 'zengyuan',
  '失灵！': 'shiling',
  '平等条约': 'pingdeng-tiaoyue',
  '死者苏生': 'sizhe-susheng',
  '滥竽充数': 'lanyu-chongshu',
  '疗愈': 'liaoyu',
  '百亿补贴': 'baiyi-butie',
  '盗亦有道': 'daoyi-youdao',
  '神之宣告': 'shenzhi-xuangao',
  '神机妙算': 'shenji-miaosuan',
  '绝处逢生': 'juechu-fengsheng',
  '钢筋铁骨': 'gangjin-tiegu',
}

export const CARD_ART_NAMES: readonly string[] = Object.keys(CARD_ART_SLUGS)

function moduleKey(slug: string): string {
  return '../../../static/card_faces/' + slug + '.webp'
}

/** Bundled URL for one card name, or null when the card has no face entry. */
export function cardArtUrl(name: string): string | null {
  const slug = CARD_ART_SLUGS[name]
  if (!slug) return null
  return ART_MODULES[moduleKey(slug)] ?? null
}

/** Card names the build knows about but whose webp did not make it into the bundle. */
export function missingCardArt(): string[] {
  return CARD_ART_NAMES.filter((name) => cardArtUrl(name) === null)
}

export const CARD_ART_COUNT = CARD_ART_NAMES.length
