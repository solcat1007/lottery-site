(function() {
  'use strict';

  const CONFIG = {
    prizes: [
      { id: 1, name: '20元现金红包', level: 1, label: '一等奖', unlimited: false, total: 1 },
      { id: 2, name: '霞蝶手办', level: 2, label: '二等奖', unlimited: false, total: 10 }
    ],
    // 抽奖概率配置：一等奖(20元红包)最稀有1% | 二等奖(手办)5% | 谢谢参与: 94%
    winRates: { first: 0.01, second: 0.05 },
    // 抽奖按钮下方"人群"彩蛋：16 个热门角色分 8+8 两排；Flex 自然流永远不堆
    //   - 相对宽度 w: 每个角色的基准宽度比例(0.85~1.15)，大角色=靠前显眼，小角色=后排低调
    // ============================================================
    //  新彩蛋墙：4 张九宫格整图 (36 人) + 每格 canvas 裁出单个角色
    //   - 4 张图：b1~b4，每张 3x3 = 9 人，b1=原神+芙莉莲, b2=原创, b3=Re0+素晴, b4=咒术+间谍+火影
    //   - 布局：围绕按钮上方/下方 3 圈半环形（按极坐标），不死板等分
    //   - 单个角色：grid 坐标 (row, col) → 按比例切图后再调用抠图
    // ============================================================
    CHAR_CROWD_SHEETS: [
      { file: 'images/crowd/_batch1a.jpg', cols: 3, rows: 3 },
      { file: 'images/crowd/_batch3a.jpg', cols: 3, rows: 3 },
      { file: 'images/crowd/_batch4a.jpg', cols: 3, rows: 3 },
      { file: 'images/crowd/_batch5a.jpg', cols: 3, rows: 3 }
    ],
    // 单角色元信息：36 人，不重复，每人独立台词
    // sheetIdx 是 CHAR_CROWD_SHEETS 索引；row/col 从 0 开始；w/h 是单格在整张 sheet 中的占比（0~1，忽略白边，切完会再抠）
    // ring: 0=外圈（最大、离按钮最远）、1=中圈、2=内圈（紧贴按钮）；phase：极角位移（-1..1，-1=最左,0=中间,1=最右）；yOff：y 向小扰动
    CHAR_CROWD: [
      // ======= Sheet 0: batch1a (原神+芙莉莲) row-major =======
      { sheetIdx: 0, row: 0, col: 0, quote: '前路如何，一起去看就知道了～',                    ring: 0, phase: -0.95, w: 1.08, rotate: -4, yOff: +4, delay: 0  },
      { sheetIdx: 0, row: 0, col: 1, quote: '浮世景色百千年依旧，人之在世却如白露与泡影。', ring: 0, phase: -0.70, w: 1.12, rotate: +2, yOff: -8, delay: 60 },
      { sheetIdx: 0, row: 0, col: 2, quote: '哎呀～这不是我最喜欢的狐狸小姐吗？',              ring: 0, phase: -0.45, w: 1.10, rotate: -1, yOff: +6, delay: 120},
      { sheetIdx: 0, row: 1, col: 0, quote: '夜叉，在此。——邪魔退散。',                          ring: 0, phase: -0.22, w: 0.98, rotate: +3, yOff: -5, delay: 90 },
      { sheetIdx: 0, row: 1, col: 1, quote: '教令院的贤者大人？——其实，我也一直在哦。',        ring: 1, phase: -0.88, w: 0.92, rotate: -2, yOff: +3, delay: 150},
      { sheetIdx: 0, row: 1, col: 2, quote: '枫原家，漂泊的一抹红叶。',                          ring: 1, phase: -0.62, w: 0.96, rotate: +1, yOff: -2, delay: 70 },
      { sheetIdx: 0, row: 2, col: 0, quote: '……魔法，还有多久才能赶上呢？',                      ring: 1, phase: -0.38, w: 1.00, rotate: -3, yOff: +5, delay: 210},
      { sheetIdx: 0, row: 2, col: 1, quote: '我已经，尽力地活过了。',                              ring: 2, phase: -0.92, w: 0.82, rotate: +2, yOff: -1, delay: 40 },
      { sheetIdx: 0, row: 2, col: 2, quote: '交给我吧！我可是战士啊！',                            ring: 2, phase: -0.72, w: 0.86, rotate: -1, yOff: +2, delay: 100},

      // ======= Sheet 1: batch3a (Re0 + 素晴) =======
      { sheetIdx: 1, row: 0, col: 0, quote: '因为昴是雷姆的英雄啊！',                              ring: 0, phase: +0.00, w: 1.10, rotate: -2, yOff: +3, delay: 180},
      { sheetIdx: 1, row: 0, col: 1, quote: '拉姆，一直都很幸福。',                                ring: 0, phase: +0.25, w: 1.06, rotate: +1, yOff: -4, delay: 110},
      { sheetIdx: 1, row: 0, col: 2, quote: '我的名字是爱蜜莉雅，只是爱蜜莉雅。',                  ring: 0, phase: +0.48, w: 1.12, rotate: -3, yOff: +6, delay: 80 },
      { sheetIdx: 1, row: 1, col: 0, quote: '从现在开始，是我昴的回合！！',                        ring: 0, phase: +0.70, w: 0.98, rotate: +2, yOff: -6, delay: 140},
      { sheetIdx: 1, row: 1, col: 1, quote: 'Explosion！——Explosion！！',                          ring: 0, phase: +0.92, w: 1.14, rotate: +4, yOff: +8, delay: 200},
      { sheetIdx: 1, row: 1, col: 2, quote: '哼！没用的废物，连我都不如的东西！',                  ring: 1, phase: -0.14, w: 1.08, rotate: -1, yOff: -3, delay: 50 },
      { sheetIdx: 1, row: 2, col: 0, quote: '抱歉，让你看看我最帅的一面吧！',                      ring: 1, phase: +0.10, w: 1.02, rotate: +3, yOff: +4, delay: 90 },
      { sheetIdx: 1, row: 2, col: 1, quote: '唉……这个月又是负数了。',                              ring: 1, phase: +0.32, w: 0.94, rotate: -2, yOff: -2, delay: 170},
      { sheetIdx: 1, row: 2, col: 2, quote: '老师，这个魔法我学会了！',                            ring: 1, phase: +0.56, w: 1.00, rotate: +2, yOff: +2, delay: 130},

      // ======= Sheet 2: batch4a (咒术 + 间谍 + 火影) =======
      { sheetIdx: 2, row: 0, col: 0, quote: '领域展开 · 无量空处。',                                ring: 1, phase: +0.80, w: 1.06, rotate: -4, yOff: -8, delay: 220},
      { sheetIdx: 2, row: 0, col: 1, quote: '我，要成为像你一样强大的人！',                        ring: 1, phase: -0.50, w: 0.92, rotate: +1, yOff: +1, delay: 60 },
      { sheetIdx: 2, row: 0, col: 2, quote: '我会杀了你，毫不犹豫。',                              ring: 2, phase: -0.52, w: 0.84, rotate: -2, yOff: -3, delay: 30 },
      { sheetIdx: 2, row: 1, col: 0, quote: '先把这张脸给我打烂！',                                ring: 2, phase: -0.28, w: 0.80, rotate: +3, yOff: +4, delay: 100},
      { sheetIdx: 2, row: 1, col: 1, quote: '荆棘公主 · 约尔·福杰。请多指教。',                    ring: 2, phase: -0.06, w: 0.84, rotate: -1, yOff: -1, delay: 160},
      { sheetIdx: 2, row: 1, col: 2, quote: '我是一名间谍，代号「黄昏」。',                        ring: 2, phase: +0.18, w: 0.88, rotate: +2, yOff: +3, delay: 90 },
      { sheetIdx: 2, row: 2, col: 0, quote: '因为我，是鸣人 Uzumaki Naruto だってばよ！！',         ring: 2, phase: +0.42, w: 0.90, rotate: -3, yOff: -4, delay: 70 },
      { sheetIdx: 2, row: 2, col: 1, quote: '我是复仇者，宇智波·佐助。',                            ring: 2, phase: +0.66, w: 0.86, rotate: +1, yOff: +2, delay: 120},
      { sheetIdx: 2, row: 2, col: 2, quote: '你们两个……不要再吵了！',                              ring: 2, phase: +0.86, w: 0.82, rotate: -2, yOff: -1, delay: 180},

      // ======= Sheet 3: batch5a (原创 9 人) =======
      { sheetIdx: 3, row: 0, col: 0, quote: '今夜的月色真美——适合拔刀。',                          ring: 0, phase: -0.86, w: 1.06, rotate: +3, yOff: +2, delay: 200},
      { sheetIdx: 3, row: 0, col: 1, quote: '滑下去的感觉，谁都追不上哦～',                        ring: 0, phase: -0.60, w: 0.96, rotate: -3, yOff: +5, delay: 140},
      { sheetIdx: 3, row: 0, col: 2, quote: '紫水晶的预言……你也是被选中的人吗？',                  ring: 0, phase: -0.34, w: 1.04, rotate: +2, yOff: -7, delay: 80 },
      { sheetIdx: 3, row: 1, col: 0, quote: '小姐，甜点已经备好。别担心，我处理得很干净。',        ring: 0, phase: -0.10, w: 0.94, rotate: -1, yOff: +6, delay: 40 },
      { sheetIdx: 3, row: 1, col: 1, quote: '神乐铃响～巫女的祈愿，你听见了吗？',                  ring: 0, phase: +0.12, w: 1.02, rotate: -3, yOff: -5, delay: 110},
      { sheetIdx: 3, row: 1, col: 2, quote: '接入完毕，开始数据采集。',                            ring: 0, phase: +0.36, w: 0.98, rotate: +1, yOff: +3, delay: 210},
      { sheetIdx: 3, row: 2, col: 0, quote: '骑士团第三大队，听我号令！——冲锋！',                  ring: 0, phase: +0.60, w: 1.08, rotate: -2, yOff: -6, delay: 170},
      { sheetIdx: 3, row: 2, col: 1, quote: '喵～你是新的铲屎官吗？看起来还不错的样子～',          ring: 0, phase: +0.84, w: 0.90, rotate: +3, yOff: +5, delay: 50 },
      { sheetIdx: 3, row: 2, col: 2, quote: '影子之中……有我的归处。',                              ring: 1, phase: +0.96, w: 0.88, rotate: -4, yOff: -3, delay: 130}
    ]
  };

  const state = {
      currentPage: 'lottery',
      isRolling: false,
      firstPrizeRemaining: 10,
      secondPrizeRemaining: 1,
      isVerified: false,
      pageSwitching: false, // 页面切换锁：防止切换中途被打断
      verifyInfo: {
        cosName: '',
        wechatId: ''
      }
    };

    // 每个 crowd 角色 → 对应作品标签（用来匹配「游戏/番剧里的真实场景」背景）
    // 作品名缩写：
    //   gi-inazuma = 原神·稻妻（雷神、八重神子、万叶 → 鳴神大社 + 鳥居 + 樱花）
    //   gi-liyue  = 原神·璃月（魈 → 层岩巨渊 / 璃月港云海）
    //   gi-sumeru = 原神·须弥（纳西妲 → 教令院拱门 / 须弥城丛林）
    //   gi-mondstadt = 原神·蒙德（琴/优菈等 → 風神像 + 风车）
    //   sf        = 葬送的芙莉莲（芙莉莲 / 战士 / 魔法使 → 魔法公会尖塔 + 草原花海）
    //   re0       = Re:从零开始异世界生活（雷姆 / 拉姆 / 爱蜜莉雅 / 昴 → 罗兹瓦尔宅邸 + 魔法阵）
    //   konosuba  = 为美好的世界献上祝福（惠惠 / 达克妮斯 / 阿克娅 / 和真 → 冒险者公会 + 爆炸圈）
    //   jjk       = 咒术回战（五条悟 / 虎杖 / 伏黑 / 宿傩 → 東京呪術高専 + 领域展开方格）
    //   spyfamily = 间谍过家家（约尔 / 黄昏 / 阿尼亚 → 东柏林/东京塔 + 黄昏剪影）
    //   naruto    = 火影忍者（鸣人 / 佐助 / 小樱 → 木叶村大门 + 火影岩 + 漩涡标誌）
    //   oc        = 原创角色（9 人 → 和风神社/巫女/骑士团/机甲等多种真实游戏风场景）
    // ===================================================================================================
    const CHAR_TAGS = [
      // ===== Sheet 0: batch1a (原神+芙莉莲) — 索引 0..8 =====
      'gi-mondstadt', //  0 r0: 琴/旅行者（原·蒙德風神像+风车）
      'gi-inazuma',   //  1 r0: 雷电将军（原·稻妻鳴神大社·鳥居·櫻花）
      'gi-inazuma',   //  2 r0: 八重神子（原·稻妻鳴神大社·櫻花紛飛）
      'gi-liyue',     //  3 r0: 魈（原·璃月港雲海·層岩）
      'gi-sumeru',    //  4 r1: 納西妲（原·須彌教令院拱門·雨林）
      'gi-inazuma',   //  5 r1: 楓原萬葉（原·稻妻·孤島楓橋·海風）
      'sf',           //  6 r1: 芙莉蓮（葬送·魔法公會尖塔·草原花海）
      'sf',           //  7 r2: 欣梅爾/戰士（葬送·勇者小鎮·夕陽山丘）
      'sf',           //  8 r2: 費倫/魔法使（葬送·魔法學院圖書館·滿天書頁）

      // ===== Sheet 1: batch3a (Re0 + 素晴) — 索引 9..17 =====
      're0',          //  9 r0: 雷姆（Re0·羅茲瓦爾宅邸·月光魔法陣）
      're0',          // 10 r0: 拉姆（Re0·羅茲瓦爾宅邸·夜櫻書房）
      're0',          // 11 r0: 愛蜜莉雅（Re0·結冰精靈之森·冰晶教堂）
      're0',          // 12 r0: 菜月昴（Re0·王都小巷·街燈黃昏）
      'konosuba',     // 13 r0: 惠惠（素晴·Explosion 爆炸火球·大草原）
      'konosuba',     // 14 r1: 達克妮絲（素晴·冒險者公會·木質大廳）
      'konosuba',     // 15 r1: 和真（素晴·公會任務板·小鎮清晨）
      'konosuba',     // 16 r1: 阿克婭（素晴·女神祭壇·藍光噴泉）
      'sf',           // 17 r1: 尤蓓麗亞/其他魔法師（葬送·魔法陣·森之小屋）→ 歸到 sf 作為魔法師場景

      // ===== Sheet 2: batch4a (咒術 + 間諜 + 火影) — 索引 18..26 =====
      'jjk',          // 18 r1: 五條悟（咒術·東京呪術高專·領域方格·紫電）
      'jjk',          // 19 r1: 虎杖悠仁（咒術·澀谷街頭·高樓霓虹）
      'jjk',          // 20 r2: 宿儺 / 伏黑（咒術·領域展開·伏魔御廚子）
      'jjk',          // 21 r2: 釘崎 / 真人（咒術·澀谷車站·柱列夜）
      'spyfamily',    // 22 r2: 約爾·佛傑（間諜過家家·東京鐵塔·月黑刺殺之夜）
      'spyfamily',    // 23 r2: 黃昏（間諜過家家·西柏林諜報大樓·黃昏剪影）
      'naruto',       // 24 r2: 漩渦鳴人（火影·木葉村火影岩·藍天白雲）
      'naruto',       // 25 r2: 宇智波佐助（火影·終結之谷·千鳥雷柱）
      'naruto',       // 26 r2: 春野櫻 / 卡卡西（火影·木葉訓練場·7班合照樹）

      // ===== Sheet 3: batch5a (原创 9 人) — 索引 27..35 =====
      'oc-samurai',   // 27 r0: 原創武士·月夜拔刀·櫻花滿天
      'oc-skate',     // 28 r0: 原創滑板少女·街頭霓虹·深夜半管
      'oc-crystal',   // 29 r0: 原創水晶占卜師·紫水晶帳篷·星盤
      'oc-maid',      // 30 r0: 原創女僕/殺手·東洋洋館·紅茶午後
      'oc-miko',      // 31 r0: 原創巫女·神樂鈴·神社參道·朱紅鳥居
      'oc-cyber',     // 32 r1: 原創駭客·賽博霓虹·數據矩陣
      'oc-knight',    // 33 r1: 原創騎士團長·中世城堡·王旗飄揚
      'oc-neko',      // 34 r1: 原創貓娘咖啡廳·奶油蛋糕·蝴蝶結
      'oc-ninja'      // 35 r1: 原創忍者·月影樓閣·風鈴飛鏢
    ];

    // ======================================================
    // B2【用户要求】符合角色特色的经典台词（36人 · 每人一条，对应 CHAR_TAGS 索引）
    // 用户说：每个特色的话语要一模一样（贴合角色）
    // ======================================================
    const CHAR_QUOTES = [
      // ===== 原神 batch1a 0..8 =====
      '巴巴托斯，请保佑蒙德风调雨顺，让风永远自由。',                 // 0 琴/旅行者 · 蒙德
      '永恒的稻妻，在雷的庇护下存续，我会守护这片土地。',          // 1 雷电将军 · 稻妻鸣神大社
      '哎呀，这可是神社的秘密哦~ 想知道的话，可得多来几趟呢。',    // 2 八重神子 · 樱花纷飞
      '靖妖傩舞——诸邪退散。',                                       // 3 魈 · 璃月云海
      '教令院的大门，为所有人敞开，一起学习吧。',                    // 4 纳西妲 · 须弥
      '飘游风中的，是枫叶，还是旅途的回忆？',                       // 5 枫原万叶 · 孤岛枫桥
      '千年的时光，眨眼之间就过去了啊……',                         // 6 芙莉莲 · 草原花海
      '只要我们还在，勇者的旗帜就永不倒下！',                      // 7 欣梅尔 · 夕阳山丘
      '古老的魔法啊，回应我的呼唤吧！',                            // 8 费伦 · 图书馆书页

      // ===== Re0 + 素晴 9..17 =====
      '昴，无论发生什么，雷姆都会陪着你。',                         // 9 雷姆
      '哼，你烧洗澡水的本事还差得远呢，弟弟。',                    // 10 拉姆
      '以精灵之名，我会保护罗兹瓦尔宅邸的所有人。',                // 11 爱蜜莉雅
      '为什么倒霉的永远是我啊！！但是，我不会放弃的！',            // 12 菜月昴
      'Explosion！！吾之究极爆裂魔法，一睹为快吧！！',               // 13 惠惠
      '请更严厉地鞭挞我吧！这就是我的使命！',                      // 14 达克妮丝
      '虽然不甘心，但我好像是全队最赚的那个……',                    // 15 和真
      '什么圣水？这分明就是上等的好酒啊！',                        // 16 阿克娅
      '寒冰魔法·凝结——将前方阻碍尽数冻住！',                       // 17 尤蓓莉亚

      // ===== 咒术+间谍+火影 18..26 =====
      '领域展开·无量空处。你变强了，但我是无敌的。',                // 18 五条悟
      '前辈！！无论什么情况，我虎杖悠仁都不会认输！',              // 19 虎杖悠仁
      '嗬，这局面，变得越来越有趣了……伏魔御厨子。',                // 20 宿傩/伏黑
      '本小姐既可爱又最强，东京咒高第一刺头登场！',                // 21 钉崎/真人
      '执行任务……为了阿尼亚和福杰家的和平。',                     // 22 约尔·福杰
      '代号·黄昏——Operation Strix，行动开始。',                   // 23 黄昏
      '因为我是要当火影的男人！——忍法·螺旋丸！',                  // 24 漩涡鸣人
      '宇智波佐助——我的目标，是超越那个男人。',                   // 25 佐助
      '第七班——卡卡西班的羁绊，一个都不能少。',                   // 26 小樱/卡卡西

      // ===== 原创 9 人 27..35 =====
      '月夜拔刀——斩破黑暗，落樱如雪。',                           // 27 武士
      '深夜的半管，霓虹滑板少女，绝不认输！',                       // 28 滑板少女
      '紫水晶帐中的命运之星，请你告诉我答案。',                     // 29 水晶占卜师
      '红茶已经沏好了哦~ 主人，请问您先沐浴还是先用餐？',          // 30 女仆杀手
      '神乐铃响起的瞬间，愿神明听见我们的祈愿。',                   // 31 巫女
      '数据矩阵的洪流中，我就是那个幽灵——ZeroDay！',              // 32 骇客
      '骑士团旗下，我以团长之名——诸君，随我冲锋！',                // 33 骑士团长
      '喵~ 这是您点的特制猫娘草莓蛋糕~ 请慢用哦！',                 // 34 猫娘咖啡厅
      '月影忍法——风铃飞镖，无声一击制敌。',                        // 35 忍者
    ];

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => document.querySelectorAll(selector);

  // 缩略图 URL 转换（列表/九宫格用缩略图节省带宽，点击大图才加载原图）
  function getThumbUrl(photoUrl) {
    if (!photoUrl) return photoUrl;
    return photoUrl.replace('/data/photos/', '/data/thumb/');
  }

  // 加载站点配置：QQ/微信二维码图片 + 联系方式
  function loadSiteConfig() {
    fetch('/api/config', { cache: 'no-store' })
      .then(r => r.ok ? r.json() : null)
      .then(cfg => {
        if (!cfg) return;
        // QQ 二维码
        const qqImg = document.getElementById('qqQrImg');
        const qqPh = document.getElementById('qqQrPlaceholder');
        const qqNum = document.getElementById('qqNumber');
        if (cfg.qq_code) {
          if (qqImg) { qqImg.src = cfg.qq_code; qqImg.style.display = 'block'; }
          if (qqPh) qqPh.style.display = 'none';
        }
        if (qqNum && cfg.qq_number) qqNum.textContent = 'QQ：' + cfg.qq_number;
        // 微信二维码
        const wcImg = document.getElementById('wechatQrImg');
        const wcPh = document.getElementById('wechatQrPlaceholder');
        const wcNum = document.getElementById('wechatContactNum');
        if (cfg.wechat_code) {
          if (wcImg) { wcImg.src = cfg.wechat_code; wcImg.style.display = 'block'; }
          if (wcPh) wcPh.style.display = 'none';
        }
        if (wcNum && cfg.wechat_id) wcNum.textContent = '微信：' + cfg.wechat_id;
      })
      .catch(() => {});
  }

  // 苹果风格滚动渐入动画
  function initStaggerAnim() {
    const els = document.querySelectorAll('[data-stagger]');
    if (!('IntersectionObserver' in window) || els.length === 0) {
      els.forEach(el => el.classList.add('visible'));
      return;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });
    els.forEach(el => io.observe(el));
  }

  function init() {
    // 【容错关键】先注册 load 监听器，保证加载条一定能走完（即使后续 init 抛错）
    window.addEventListener('load', () => {
      completeLoadingBar();
      setTimeout(() => {
        try { checkUserStatus(); } catch (e) { console.error('checkUserStatus error:', e); }
      }, 400);
    });
    let _resizeTimer = null;
    window.addEventListener('resize', () => {
      if (_resizeTimer) clearTimeout(_resizeTimer);
      _resizeTimer = setTimeout(() => { try { resetWheel(); } catch(e) {} }, 200);
    });

    // 加载站点配置（QQ/微信二维码、联系方式）
    try { loadSiteConfig(); } catch (e) { console.error('loadSiteConfig:', e); }

    // 【关键】在初始化其他组件前先检查用户身份，避免已验证用户看到抽奖页再闪跳
    let preVerified = false;
    try {
      const savedInfo = localStorage.getItem('lottery_user_info');
      if (savedInfo) {
        const info = JSON.parse(savedInfo);
        // 【去微信号】只校验 COS 名称即可
        if (info.cosName) {
          state.verifyInfo.cosName = info.cosName;
          state.verifyInfo.wechatId = info.wechatId || '';
          state.isVerified = true;
          preVerified = true;
        }
      }
    } catch (e) {}

    // 已验证用户：直接把 gallery 设为初始激活页（避免从 lottery 闪跳）
    if (preVerified) {
      try {
        const lotteryEl = $('#page-lottery');
        const galleryEl = $('#page-gallery');
        if (lotteryEl && galleryEl) {
          lotteryEl.classList.remove('active');
          galleryEl.classList.add('active');
          state.currentPage = 'gallery';
          navItemsSetActive('gallery');
        }
      } catch (e) {}
    }

    // 【容错】每个初始化函数独立 try/catch，一个失败不影响其他
    const safeInit = (name, fn) => { try { fn(); } catch (e) { console.error('[init] ' + name + ' failed:', e); } };
    safeInit('loadingBar', initLoadingBar);
    safeInit('staggerAnim', initStaggerAnim);
    safeInit('lotteryWheel', initLotteryWheel);
    safeInit('lotteryBtn', initLotteryBtn);
    safeInit('rulesToggle', initRulesToggle);
    safeInit('prizeModal', initPrizeModal);
    safeInit('verifyModal', initVerifyModal);
    safeInit('navClicks', initNavClicks);
    safeInit('pageScroll', initPageScroll);
    safeInit('stars', initStars);
    safeInit('particles', initParticles);
    safeInit('bgm', initBgm);
    safeInit('firstPrize', loadFirstPrizeRemaining);
    safeInit('charCrowd', renderCharCrowd);

    // 【底部重置按钮】防止用户因脏 localStorage 被误判为「已抽过奖」或身份丢失
    try {
      const resetBtn = document.getElementById('pfResetBtn');
      if (resetBtn) {
        resetBtn.addEventListener('click', () => {
          if (!confirm('确定要重置本地身份吗？\n\n重置后需要重新填写 COS名，再参与抽奖。\n（不会删除服务器上的任何数据）')) return;
          hardResetIdentity(false);
          setTimeout(() => {
            if (state.currentPage !== 'lottery') try { switchPage('lottery'); } catch(e) {}
            setTimeout(() => {
              try { showVerifyModal(); } catch(e) {}
            }, 120);
          }, 100);
        });
      }
    } catch (e) {}
  }

  function checkUserStatus() {
    const savedInfo = localStorage.getItem('lottery_user_info');
    if (savedInfo) {
      try {
        const info = JSON.parse(savedInfo);
        // 【去微信号】只校验 COS 名称即可
        if (info.cosName) {
          state.verifyInfo.cosName = info.cosName;
          state.verifyInfo.wechatId = info.wechatId || '';
          state.isVerified = true;
          checkUserOnServer();
          return;
        }
      } catch (e) {
        console.error('Parse saved info error:', e);
      }
    }
    // 没有登录信息 → 直接弹登记窗（无法关闭）
    showVerifyModal();
  }

  function checkUserOnServer() {
    // 【修复】优先从 localStorage 取（因为它不会被意外清空），state 作为 fallback，DOM 再兜底
    // 避免 state.verifyInfo 被意外清空后，传给 check 接口空字符串
    let cosName = '', wechatId = '';
    try {
      const cached = localStorage.getItem('lottery_user_info');
      if (cached) { const o = JSON.parse(cached || '{}'); cosName = (o.cosName || '').trim(); wechatId = (o.wechatId || '').trim(); }
    } catch (e) {}
    if (!cosName) cosName = (localStorage.getItem('verify_cosName') || '').trim();
    if (!wechatId) wechatId = (localStorage.getItem('verify_wechatId') || '').trim();
    if (!cosName) cosName = (state.verifyInfo.cosName || '').trim();
    if (!wechatId) wechatId = (state.verifyInfo.wechatId || '').trim();
    // 最后兜底：从 DOM 输入框再取一次
    try {
      const cosInput = document.getElementById('cosName');
      const wxInput = document.getElementById('wechatId');
      if (!cosName && cosInput) cosName = (cosInput.value || '').trim();
      if (!wechatId && wxInput) wechatId = (wxInput.value || '').trim();
    } catch (e) {}
    // 同步回 state（保证后续用的都是有效值）
    if (cosName) state.verifyInfo.cosName = cosName;
    if (wechatId) state.verifyInfo.wechatId = wechatId;
    if (cosName) state.isVerified = true;

    if (!cosName) {
      // 没有任何身份信息（新用户）：不调 check，避免传空值
      return;
    }

    fetch('/api/lottery/check', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        cosName: cosName,
        wechatId: wechatId
      })
    })
    .then(res => res.json())
    .then(data => {
      // 【不再区分管理员】所有人都按普通用户流程处理
      if (data.success && data.exists && data.record) {
        localStorage.setItem('current_record_id', data.record.id.toString());
        state.verifyInfo.recordId = data.record.id;
        _persistFullIdentity(cosName, wechatId);
        switchPage('gallery');
      } else {
        state.isVerified = true;
        localStorage.setItem('is_verified', '1');
        _persistFullIdentity(cosName, wechatId);
        // 【重点修复】后端 no_record_hint: 服务器确认没有此身份的记录
        // 立刻清掉本地残留的脏 current_record_id（否则仍会被误判为"已抽过奖"，但后台啥也没有）
        if (data && data.no_record_hint) {
          try { localStorage.removeItem('current_record_id'); } catch (e) {}
          try { state.verifyInfo.recordId = null; } catch (e) {}
        }
        const hasRecord = !!localStorage.getItem('current_record_id') || !!state.verifyInfo.recordId;
        if (hasRecord) {
          if (state.currentPage !== 'gallery') switchPage('gallery');
        } else {
          // ★ 没有记录 → 切换到抽奖页（让用户可以重新开始抽奖，避免停留在照片页却没法操作）
          if (state.currentPage !== 'lottery') switchPage('lottery');
          const btn = $('#lotteryBtn');
          if (btn) {
            btn.disabled = false;
            const t = btn.querySelector('.btn-text');
            if (t) t.textContent = '开始抽奖';
          }
        }
      }
    })
    .catch(err => {
      console.error('Check user on server error:', err);
      // 网络错误：绝对不清除任何身份信息
    });
  }

  // 初始化星空背景
  function initStars() {
    const container = $('#starsLayer');
    if (!container) return;

    const starColors = ['#ffffff', '#cfe8ff', '#ffe4b5', '#e6e6fa', '#b0e0e6'];

    // 【大幅减少装饰】：星星从120→15颗，透明度降低，避免页面太"花"
    for (let i = 0; i < 15; i++) {
      const star = document.createElement('div');
      star.className = 'star';
      const size = Math.random() * 1.8 + 0.3;
      const left = Math.random() * 100;
      const top = Math.random() * 100;
      const duration = Math.random() * 5 + 3;
      const delay = Math.random() * 6;
      const color = starColors[Math.floor(Math.random() * starColors.length)];
      const opacity = Math.random() * 0.18 + 0.08;  // 更淡

      star.style.cssText = `
        width: ${size}px;
        height: ${size}px;
        left: ${left}%;
        top: ${top}%;
        opacity: ${opacity};
        animation-duration: ${duration}s;
        animation-delay: ${delay}s;
        background: ${color};
        box-shadow: 0 0 ${size * 1.5}px ${color};
      `;
      container.appendChild(star);
    }

    // 生成流星（大幅减少，视觉干扰
    initMeteors(container);
  }

  // 流星生成
  function initMeteors(container) {
    // 【大幅减少装饰】：流星取消常驻0颗，完全不生成，避免闪烁干扰抽奖
    const meteorCount = 0;

    for (let i = 0; i < meteorCount; i++) {
      setTimeout(() => {
        createMeteor(container);
      }, i * 5000 + Math.random() * 4000);
    }

    // 定时创建新流星
    setInterval(() => {
      createMeteor(container);
    }, 14000);
  }

  function createMeteor(container) {
    // 如果屏幕上流星数量>=2，就先不新增（避免刷屏）
    const exist = container.querySelectorAll('.meteor').length;
    if (exist >= 2) return;

    const meteor = document.createElement('div');
    meteor.className = 'meteor';
    const left = Math.random() * 70 + 15;
    const duration = Math.random() * 1.5 + 2.0;
    const height = Math.random() * 40 + 40;
    const opacity = Math.random() * 0.25 + 0.2;  // 更淡

    meteor.style.cssText = `
      left: ${left}%;
      top: -10%;
      height: ${height}px;
      opacity: ${opacity};
      animation-duration: ${duration}s;
    `;

    container.appendChild(meteor);

    // 动画结束后删除
    setTimeout(() => {
      if (meteor.parentNode) {
        meteor.parentNode.removeChild(meteor);
      }
    }, duration * 1000 + 150);
  }

  // 初始化抽奖页背景粒子
  function initParticles() {
    const container = $('#particles');
    if (!container) return;

    const colors = ['#00B4D8', '#90E0EF', '#FFD700', '#FFB800', '#fff'];
    // 【大幅减少装饰】：粒子 10 → 3 个，透明度调低
    const count = 3;

    for (let i = 0; i < count; i++) {
      const p = document.createElement('div');
      p.className = 'particle';
      const size = Math.random() * 2 + 0.6;
      const left = Math.random() * 100;
      const duration = Math.random() * 18 + 14;
      const delay = Math.random() * 18;
      const color = colors[Math.floor(Math.random() * colors.length)];
      const opacity = Math.random() * 0.18 + 0.08;

      p.style.cssText = `
        width: ${size}px;
        height: ${size}px;
        left: ${left}%;
        background: ${color};
        animation-duration: ${duration}s;
        animation-delay: -${delay}s;
        --p-opacity: ${opacity};
      `;
      container.appendChild(p);
    }
  }

  // 彩纸爆散特效
  function triggerConfetti() {
    const container = $('#confettiContainer');
    if (!container) return;
    container.innerHTML = '';

    const colors = ['#FFD700', '#FFB800', '#00B4D8', '#90E0EF', '#FF6B8A', '#A78BFA', '#4ADE80', '#fff'];
    const count = 60;

    for (let i = 0; i < count; i++) {
      const c = document.createElement('div');
      c.className = 'confetti-piece';
      const left = Math.random() * 100;
      const duration = Math.random() * 2 + 2;
      const delay = Math.random() * 0.5;
      const color = colors[Math.floor(Math.random() * colors.length)];
      const size = Math.random() * 6 + 4;
      const rotate = Math.random() * 360;

      c.style.cssText = `
        left: ${left}%;
        background: ${color};
        animation-duration: ${duration}s;
        animation-delay: ${delay}s;
        width: ${size}px;
        height: ${size}px;
        transform: rotate(${rotate}deg);
      `;
      container.appendChild(c);
    }

    // 3秒后清理
    setTimeout(() => {
      if (container) container.innerHTML = '';
    }, 4000);
  }

  // 从服务器加载奖品剩余数量（每次刷新避免缓存）
  function loadFirstPrizeRemaining() {
    fetch('/api/lottery/first-prize-remaining?_t=' + Date.now())
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          state.firstPrizeRemaining = data.remaining;
          state.secondPrizeRemaining = data.secondRemaining || 1;
        }
      })
      .catch(() => {});
  }

  // ============ 背景音乐 ============
  function initBgm() {
    const btn = $('#bgmControl');
    const audio = $('#bgmAudio');
    if (!btn || !audio) return;

    // 【音量降低】：默认较淡，避免太吵；默认不自动播放（避免浏览器拦截自动播放+避免一上来就响）
    audio.volume = 0.35;
    audio.muted = false;

    // 读取用户上次的开关选择（默认：关，需要用户点一次才开，避免浏览器拦截自动播放）
    let lastState = localStorage.getItem('bgm_playing');
    let isPlaying = false;
    let sourceLoaded = false;

    // 先检测音乐文件是否存在（不存在就隐藏控件）
    fetch('audio/bgm.mp3', { method: 'HEAD' })
      .then(res => {
        if (res.ok) sourceLoaded = true;
      })
      .catch(() => {
        // 再试一下其他格式
        return fetch('audio/bgm.ogg', { method: 'HEAD' })
          .then(res => { if (res.ok) sourceLoaded = true; })
          .catch(() => {});
      })
      .finally(() => {
        if (!sourceLoaded) {
          // 音频文件不存在：先隐藏按钮，等用户上传后会自动检测到
          btn.style.display = 'none';
        } else {
          btn.style.display = '';
        }
      });

    function setBgmUi(playing) {
      btn.classList.toggle('playing', playing);
      btn.classList.toggle('paused', !playing);
    }

    function playBgm() {
      if (!sourceLoaded) return;
      // 确保每次都用低音量播放
      audio.volume = 0.35;
      audio.muted = false;
      const p = audio.play();
      if (p && typeof p.then === 'function') {
        p.then(() => {
          isPlaying = true;
          localStorage.setItem('bgm_playing', '1');
          setBgmUi(true);
        }).catch(() => {
          // 被浏览器拦截，等用户第一次交互后再弹提示
          isPlaying = false;
          setBgmUi(false);
        });
      } else {
        isPlaying = true;
        setBgmUi(true);
      }
    }

    function pauseBgm() {
      audio.pause();
      isPlaying = false;
      localStorage.setItem('bgm_playing', '0');
      setBgmUi(false);
    }

    btn.addEventListener('click', () => {
      if (isPlaying) {
        pauseBgm();
      } else {
        playBgm();
      }
    });

    // 用户第一次交互后，如果上次是打开状态，自动恢复播放
    function tryAutoplayOnce() {
      if (lastState === '1' && !isPlaying && sourceLoaded) {
        playBgm();
      }
      document.removeEventListener('click', tryAutoplayOnce);
      document.removeEventListener('touchstart', tryAutoplayOnce);
    }
    document.addEventListener('click', tryAutoplayOnce);
    document.addEventListener('touchstart', tryAutoplayOnce);

    // 音频出错：不反复报错
    audio.addEventListener('error', () => {
      pauseBgm();
    });

    // 默认UI：暂停态
    setBgmUi(false);
  }

  // 动态获取格子宽度（cell + gap，用于计算移动距离）
  function getCellWidth() {
    const cell = $('.prize-cell');
    if (!cell) return 116;
    const width = cell.offsetWidth;
    const gap = parseFloat(window.getComputedStyle($('#wheelContainer')).gap) || 16;
    return width + gap;
  }

  // 获取轨道内边距
  function getTrackPadding() {
    const track = $('#wheelContainer');
    const style = window.getComputedStyle(track);
    return parseFloat(style.paddingLeft) || 20;
  }

  // 计算让 cell_0 居中所需的 centerOffset
  // translateX = -centerOffset 时，第一个格子刚好在轨道中央
  function getCenterOffset() {
    const container = $('#wheelContainer');
    const trackWidth = container.parentElement.offsetWidth;
    const padding = getTrackPadding();
    const cell = $('.prize-cell');
    if (!cell) return 0;
    const cellRealWidth = cell.offsetWidth;
    // cell_0 中心在 wheel 坐标系 = padding + cellRealWidth/2
    // 要让它在 track 中心：translateX = trackWidth/2 - (padding + cellRealWidth/2)
    // centerOffset = -(translateX) = padding + cellRealWidth/2 - trackWidth/2
    return padding + cellRealWidth / 2 - trackWidth / 2;
  }

  function resetWheel() {
    if (state.isRolling) return;
    const container = $('#wheelContainer');
    if (!container) return;
    container.style.transform = 'translateX(0)';
  }

  function initLoadingBar() {
    const bar = $('#loading-bar');
    setTimeout(() => {
      bar.style.transform = 'scaleX(0.85)';
    }, 100);
  }

  function completeLoadingBar() {
    const bar = $('#loading-bar');
    bar.style.transform = 'scaleX(1)';
    setTimeout(() => {
      bar.classList.add('loading-complete');
    }, 100);
  }

  function initNavClicks() {
    const navItems = $$('.nav-item');
    navItems.forEach(item => {
      item.addEventListener('click', () => {
        let targetPage = item.dataset.page;
        if (targetPage === state.currentPage) return;
        // 切返图/反馈前必须先登记
        if ((targetPage === 'gallery' || targetPage === 'messages') && !state.isVerified) {
          showToast('请先登记信息');
          showVerifyModal();
          return;
        }
        switchPage(targetPage);
      });
    });

    // 🆕 快速入口按钮绑定（"全部"页面顶部：💬我的反馈、📤上传返图）
    setTimeout(() => {
      const quickMsgBtn = $('#galleryQuickMsgBtn');
      const quickUploadBtn = $('#galleryQuickUploadBtn');
      if (quickMsgBtn) {
        quickMsgBtn.addEventListener('click', () => {
          if (!state.isVerified) { showToast('请先登记信息'); showVerifyModal(); return; }
          jumpToGalleryMessageSection(true);
        });
      }
      if (quickUploadBtn) {
        quickUploadBtn.addEventListener('click', () => {
          if (!state.isVerified) { showToast('请先登记信息'); showVerifyModal(); return; }
          // 跳转到返图区并滚动到上传/返图区
          if (state.currentPage !== 'gallery') switchPage('gallery');
          setTimeout(() => {
            const photoArea = $('#photoArea');
            if (photoArea) photoArea.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }, 120);
        });
      }
    }, 200);
  }

  // 🆕 跳转到gallery页 + 滚动到反馈留言板（可选：自动聚焦输入框）
  function jumpToGalleryMessageSection(focusTextarea) {
    if (!state.isVerified) { showToast('请先登记信息'); showVerifyModal(); return; }
    const needSwitch = state.currentPage !== 'gallery';
    const afterSwitch = needSwitch ? 520 : 60;
    if (needSwitch) switchPage('gallery');
    setTimeout(() => {
      const msgSection = $('#photographerMsgSection');
      if (msgSection) {
        msgSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        // 高亮一下提示
        msgSection.animate([
          { boxShadow: '0 0 0 0 rgba(251,191,36,0)' },
          { boxShadow: '0 0 0 6px rgba(251,191,36,0.45)' },
          { boxShadow: '0 0 0 0 rgba(251,191,36,0)' }
        ], { duration: 1600, easing: 'ease-in-out' });
      }
      if (focusTextarea) {
        setTimeout(() => {
          const ta = $('#msgTextarea');
          if (ta) { try { ta.focus(); } catch(e) {} }
        }, 400);
      }
    }, afterSwitch);
  }

  // ============================================================
  // 【重置身份】彻底清空所有 localStorage + state，真·重置（不会残留脏 record_id）
  // ============================================================
  const _IDENTITY_KEYS = [
    'current_record_id',
    'lottery_user_info',
    'verify_cosName',
    'verify_wechatId',
    'is_verified'
  ];
  function hardResetIdentity(silent) {
    try { _IDENTITY_KEYS.forEach(k => localStorage.removeItem(k)); } catch(e) {}
    try {
      state.verifyInfo.cosName = '';
      state.verifyInfo.wechatId = '';
      state.verifyInfo.recordId = null;
      state.isVerified = false;
      _msgCurrentRecordId = null;
    } catch(e) {}
    if (silent !== true) showToast('已重置身份，可以重新抽奖啦');
  }
  window.__hardResetIdentity = hardResetIdentity;

  function switchPage(targetPage) {
    // 🆕 messages 页是 gallery 的子视图（跳转到 gallery + 滚动到反馈区）
    let actualPage = targetPage;
    let needScrollToMessages = false;
    if (targetPage === 'messages') {
      actualPage = 'gallery';
      needScrollToMessages = true;
    }
    // 【防卡顿修复】正在切换时，重复的 switchPage 直接丢（不再并发触发）
    if (state.pageSwitching) {
      // 唯一例外：已经到 gallery 但需要滚动到反馈区
      if (actualPage === state.currentPage && needScrollToMessages) {
        clearTimeout(switchPage._pendingScroll);
        switchPage._pendingScroll = setTimeout(() => jumpToGalleryMessageSection(false), 450);
      }
      return;
    }
    // 重复进入 → 跳过（但如果是在 gallery 里再点"反馈"，仍要滚动到反馈区）
    if (actualPage === state.currentPage) {
      if (needScrollToMessages && targetPage === 'messages') {
        jumpToGalleryMessageSection(false);
      }
      return;
    }
    state.pageSwitching = true;

    // 切返图二次检查：必须有记录或已登记
    if (actualPage === 'gallery') {
      if (!state.isVerified) {
        state.pageSwitching = false;
        showVerifyModal();
        return;
      }
    }
    const currentPageEl = $(`#page-${state.currentPage}`);
    const targetPageEl = $(`#page-${actualPage}`);
    const pages = ['lottery', 'gallery', 'publicwall'];
    const currentIndex = pages.indexOf(state.currentPage);
    const targetIndex = pages.indexOf(actualPage) === -1 ? 0 : pages.indexOf(actualPage);
    const isForward = targetIndex > currentIndex;

    // 🆕 导航栏激活状态：messages 页也显示为激活（把反馈tab也点亮）
    if (targetPage === 'messages') {
      const allNav = $$('.nav-item');
      allNav.forEach(item => {
        const dp = item.dataset.page;
        item.classList.toggle('active', dp === 'messages');
      });
    } else {
      navItemsSetActive(actualPage);
    }
    currentPageEl.classList.add(isForward ? 'slide-left' : 'slide-right');
    targetPageEl.classList.add(isForward ? 'enter-right' : 'enter-left');

    void targetPageEl.offsetWidth;

    // 单层 RAF + 下一帧直接切换（避免双层 RAF 导致 iOS Safari 闪屏）
    requestAnimationFrame(() => {
      currentPageEl.classList.remove('active', isForward ? 'slide-left' : 'slide-right');
      targetPageEl.classList.add('active');
      targetPageEl.classList.remove(isForward ? 'enter-right' : 'enter-left');
    });

    setTimeout(() => {
      state.pageSwitching = false;
    }, 420);

    state.currentPage = actualPage;

    if (actualPage === 'gallery') {
      checkPhotoStatus();
      startPhotoPolling();
      stopPublicWallPolling();
      // 🆕 点击反馈Tab进来的：自动跳到反馈区 + 高亮
      if (needScrollToMessages) {
        setTimeout(() => jumpToGalleryMessageSection(false), 500);
      }
    } else if (actualPage === 'publicwall') {
      stopPhotoPolling();
      initPublicWall();
      startPublicWallPolling();
    } else {
      stopPhotoPolling();
      stopPublicWallPolling();
    }
  }

  let photoPollTimer = null;
  let msgPollTimer = null;

  // 【性能优化】轮询频率降低 + 标签页隐藏时暂停，避免占用网络/CPU导致卡顿
  function startPhotoPolling() {
    stopPhotoPolling();
    startMsgPolling();
    photoPollTimer = setInterval(() => {
      if (document.hidden) return;
      if (state.currentPage !== 'gallery') return;
      const photoWrapper = $('#photoWrapper');
      if (photoWrapper && photoWrapper.style.display === 'none') {
        checkPhotoStatus();
      }
    }, 12000); // 5s → 12s
  }

  function stopPhotoPolling() {
    if (photoPollTimer) {
      clearInterval(photoPollTimer);
      photoPollTimer = null;
    }
    stopMsgPolling();
  }

  // 留言板轮询：管理员回复后用户端可见
  function startMsgPolling() {
    stopMsgPolling();
    msgPollTimer = setInterval(() => {
      if (document.hidden) return;
      if (state.currentPage !== 'gallery') return;
      const recordId = localStorage.getItem('current_record_id') || _msgCurrentRecordId;
      if (!recordId) return;
      loadMessagesAndRender(recordId);
    }, 18000); // 10s → 18s
  }
  function stopMsgPolling() {
    if (msgPollTimer) {
      clearInterval(msgPollTimer);
      msgPollTimer = null;
    }
  }

  // 标签页切换可见性：前台进入可见状态时，立刻拉一次最新数据
  (function installVisibilityRefresh() {
    try {
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
          // 每次切回前台都刷新统计（防止缓存导致的旧数据）
          loadFirstPrizeRemaining();
          if (state.currentPage === 'gallery') {
            clearTimeout(installVisibilityRefresh._t);
            installVisibilityRefresh._t = setTimeout(() => {
            checkPhotoStatus();
            const rid = localStorage.getItem('current_record_id') || _msgCurrentRecordId;
            if (rid) loadMessagesAndRender(rid);
          }, 300);
          }
        }
      });
    } catch (e) {}
  })();

  function checkPhotoStatus() {
    // 【修复】进入返图页前先同步一次身份，确保 state 里有 cosName/wechatId
    // 这样留言板初始化时就不会出现「身份丢失」
    const id = getIdentity();
    const recordId = localStorage.getItem('current_record_id') || id.recordId;
    if (!recordId) {
      showWaitingState(null);
      return Promise.resolve(null);
    }

    // 先把留言板拉起来——不管有没有返图，用户都可以先给摄影师提修图需求
    initMsgBoard(recordId);
    loadMessagesAndRender(recordId);

    return fetch(`/api/lottery/photo/${recordId}`)
      .then(res => res.json())
      .then(data => {
        if (data.success && data.photos && data.photos.length > 0) {
          showPhotos(data.photos, recordId);
          return data;
        } else {
          showWaitingState(recordId);
          return null;
        }
      })
      .catch(() => { showWaitingState(recordId); return null; });
  }

  function showPhotos(photos, recordId) {
    const waitingState = $('#waitingState');
    const photoWrapper = $('#photoWrapper');
    const grid = $('#galleryPhotoGrid');
    const countSpan = $('#galleryPhotoCount');
    const msgSection = $('#photographerMsgSection');

    if (waitingState) waitingState.style.display = 'none';
    if (photoWrapper) photoWrapper.style.display = 'block';
    if (msgSection) msgSection.style.display = 'block';

    // 刷新上传区的身份状态（解除禁用等）
    if (typeof window.__refreshSimpleUploader === 'function') {
      try { window.__refreshSimpleUploader(); } catch (e) {}
    }

    // === 同步已占用位置给九宫格上传弹窗（让用户一眼看到哪些位置已经有图）
    try {
      const ps = Array.isArray(photos)
        ? photos.map(p => Number(p.photoPosition)).filter(n => n >= 1 && n <= 9)
        : [];
      if (typeof window.__setSimpleUploaderTakenPositions === 'function') {
        window.__setSimpleUploaderTakenPositions(ps);
      }
    } catch (e) {}
    // 上传简单区：用户要求必须永远显示两个白框
    if (typeof window.__toggleSimpleUploaderVisibility === 'function') {
      window.__toggleSimpleUploaderVisibility(true);
    }

    if (grid) {
      const count = photos.length;
      if (countSpan) countSpan.textContent = String(count);

      // 按photoPosition排序
      const sorted = [...photos].sort((a, b) => (a.photoPosition || 999) - (b.photoPosition || 999));
      grid.innerHTML = sorted.map(p => renderGalleryPhotoCard(p, recordId)).join('');

      // 绑定approve按钮
      grid.querySelectorAll('.gallery-approve-btn').forEach(btn => {
        btn.addEventListener('click', () => handleGalleryApprove(btn, recordId));
      });
      // 绑定撤回按钮
      grid.querySelectorAll('.gallery-withdraw-btn').forEach(btn => {
        btn.addEventListener('click', () => handleGalleryWithdraw(btn, recordId));
      });
      // 绑定删除按钮
      grid.querySelectorAll('.gallery-delete-btn').forEach(btn => {
        btn.addEventListener('click', () => handleGalleryDelete(btn, recordId));
      });
    }

    // 初始化并加载摄影师留言板（返图下面）——如果checkPhotoStatus里还没做的话，这里兜底再做一次
    initMsgBoard(recordId);
    loadMessagesAndRender(recordId);
  }

  let _msgBoardInited = false;
  let _msgCurrentRecordId = null;

  function initMsgBoard(recordId) {
    if (!recordId) return;
    _msgCurrentRecordId = String(recordId);
    if (_msgBoardInited) return;
    const txt = $('#msgTextarea');
    const cnt = $('#msgWordCount');
    const btn = $('#msgSendBtn');
    if (txt && cnt) {
      txt.addEventListener('input', () => {
        const len = (txt.value || '').length;
        if (cnt) cnt.textContent = String(len);
      });
    }
    if (btn && txt) {
      btn.addEventListener('click', () => handleSendMsg());
      // Ctrl / Cmd + Enter 发送
      txt.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && (e.key === 'Enter' || e.keyCode === 13)) {
          e.preventDefault();
          handleSendMsg();
        }
      });
    }
    _msgBoardInited = true;
  }

  function handleSendMsg() {
    const txt = $('#msgTextarea');
    const btn = $('#msgSendBtn');
    if (!txt || !btn) return;
    const text = (txt.value || '').trim();
    if (!text) {
      showToast('写点什么再发送吧～');
      txt.focus();
      return;
    }
    // 【修复】使用统一 getIdentity() 从 localStorage + state 双重读取，避免身份丢失
    const id = getIdentity();
    if (!_msgCurrentRecordId) {
      const fallback = localStorage.getItem('current_record_id') || (id && id.recordId ? String(id.recordId) : null);
      if (fallback) {
        _msgCurrentRecordId = String(fallback);
        initMsgBoard(fallback);
        loadMessagesAndRender(fallback);
      }
    }
    if (!_msgCurrentRecordId && id.recordId) {
      _msgCurrentRecordId = String(id.recordId);
    }
    if (!_msgCurrentRecordId) {
      showToast('请先完成抽奖，获得记录后再留言～');
      // 找不到记录：自动跳转到抽奖页，让用户先完成抽奖
      if (state.currentPage !== 'lottery') switchPage('lottery');
      return;
    }
    const cosName = id.cosName || '';
    const wechatId = id.wechatId || '';
    // 【去微信号】只需 COS 名称即可发送留言
    if (!cosName) {
      let extraCos = '';
      try {
        const s = localStorage.getItem('lottery_user_info');
        if (s) { const o = JSON.parse(s||'{}'); extraCos = (o.cosName||'').trim(); }
      } catch(e) {}
      if (!extraCos) extraCos = (localStorage.getItem('verify_cosName') || '').trim();
      if (extraCos) {
        state.verifyInfo.cosName = extraCos;
        return _doSendMsg(txt, btn, extraCos, wechatId, text);
      }
      // 【修复用户反馈】身份缺失时，不再只提示找不到入口，直接弹出身份登记模态框，用户填完就能继续留言
      showToast('需要先填写身份信息');
      // 给弹窗里预填当前正在写的留言，填完身份后自动回到这里
      try { localStorage.setItem('msg_pending_text', text); } catch (e) {}
      if (typeof showVerifyModal === 'function') showVerifyModal();
      return;
    }
    _doSendMsg(txt, btn, cosName, wechatId, text);
  }

  function _doSendMsg(txt, btn, cosName, wechatId, text) {
    const rid = _msgCurrentRecordId || localStorage.getItem('current_record_id');
    if (!rid) {
      showToast('请先完成抽奖再留言');
      return;
    }
    btn.disabled = true;
    const originalText = btn.innerHTML;
    btn.innerHTML = '⏳ 正在发送…';
    fetch(`/api/lottery/message/${_msgCurrentRecordId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cosName, wechatId, text })
    })
      .then(r => r.json())
      .then(data => {
        btn.disabled = false;
        btn.innerHTML = originalText;
        if (data.success) {
          showToast(data.message || '✅ 留言已发送');
          txt.value = '';
          const cnt = $('#msgWordCount');
          if (cnt) cnt.textContent = '0';
          loadMessagesAndRender(_msgCurrentRecordId);
        } else {
          showToast('❌ ' + (data.message || '发送失败，请重试'));
        }
      })
      .catch(err => {
        btn.disabled = false;
        btn.innerHTML = originalText;
        console.error('Send msg error:', err);
        showToast('❌ 网络错误，请稍后重试');
      });
  }

  function loadMessagesAndRender(recordId) {
    const list = $('#msgList');
    if (!list) return;
    if (!recordId) return;
    // 【修复】使用统一 getIdentity() 双重读取，避免身份丢失导致消息加载不出来
    const id = getIdentity();
    let cosName = id.cosName || '';
    let wechatId = id.wechatId || '';
    // 【去微信号】只校验 COS 名称
    if (!cosName) {
      try {
        const s = localStorage.getItem('lottery_user_info');
        if (s) { const o = JSON.parse(s||'{}'); cosName = (o.cosName||'').trim(); wechatId = (o.wechatId||'').trim(); }
      } catch(e) {}
    }
    if (!cosName) {
      // 静默失败，但至少不影响其他功能（消息加载失败不影响返图）
      console.warn('[loadMessagesAndRender] 身份信息缺失，跳过加载留言');
      return;
    }
    const qs = new URLSearchParams({ cosName, wechatId }).toString();
    fetch(`/api/lottery/message/${recordId}?${qs}`)
      .then(r => r.json())
      .then(data => {
        if (data.success) {
          renderMessageList(data.messages || []);
        } else if (data.message && data.message.indexOf('身份') >= 0) {
          console.warn('[留言] 身份校验失败:', data.message);
        }
      })
      .catch(err => console.error('Load msgs error:', err));
  }

  function renderMessageList(messages) {
    const list = $('#msgList');
    if (!list) return;
    if (!messages || messages.length === 0) {
      list.innerHTML = `<div class="msg-empty">还没有留言哦～ 上传完照片后，在这里告诉摄影师你想修成什么风格吧！</div>`;
      updateMsgUnreadBadge(0, 0);
      return;
    }
    const esc = (s) => String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

    // 🆕 计算未读回复数量（后端用 m.replyRead=false 或没有 replyRead 字段代表未读回复）
    let replyCount = 0;
    let unreadReplyCount = 0;
    messages.forEach(m => {
      if (m && typeof m === 'object' && m.reply && String(m.reply).trim()) {
        replyCount += 1;
        const readFlag = m.replyRead;
        // 如果后端没返回 replyRead 字段（旧数据），用 localStorage 记一下
        let localRead = null;
        try {
          const key = `msg_reply_read_${localStorage.getItem('current_record_id') || ''}_${m.id || ''}`;
          localRead = localStorage.getItem(key);
        } catch(e) {}
        const isUnread = readFlag === false || (readFlag == null && localRead !== '1');
        if (isUnread) unreadReplyCount += 1;
      }
    });
    updateMsgUnreadBadge(replyCount, unreadReplyCount);

    list.innerHTML = messages.map(m => {
      const by = (m.by || 'user') === 'photographer' ? 'photographer' : 'user';
      const tagText = by === 'photographer' ? '📷 摄影师 回复' : '✨ 我的留言';
      // 🆕 检测这条有没有未读回复
      let hasUnreadReply = false;
      const hasReply = m.reply && String(m.reply).trim();
      if (hasReply) {
        const readFlag = m.replyRead;
        let localRead = null;
        try {
          const key = `msg_reply_read_${localStorage.getItem('current_record_id') || ''}_${m.id || ''}`;
          localRead = localStorage.getItem(key);
        } catch(e) {}
        hasUnreadReply = readFlag === false || (readFlag == null && localRead !== '1');
        // 渲染完标记为本地已读（避免下次重复提示，等后端接口补上 replyRead 字段后再统一联动）
        if (hasUnreadReply) {
          try {
            const key = `msg_reply_read_${localStorage.getItem('current_record_id') || ''}_${m.id || ''}`;
            localStorage.setItem(key, '1');
          } catch(e) {}
        }
      }
      const replyClass = hasReply ? 'has-reply' : '';
      const unreadClass = hasUnreadReply ? 'unread-reply' : '';
      const replyHtml = hasReply
        ? `<div class="msg-reply ${unreadClass}">
            <div class="msg-reply-head">
              <span>📷 摄影师 回复${hasUnreadReply ? ' <span class="reply-unread-dot" title="新回复">●</span>' : ''}</span>
              ${m.replyAt ? `<span class="msg-time">${esc(m.replyAt)}</span>` : ''}
            </div>
            <p class="msg-reply-text">${esc(m.reply)}</p>
          </div>`
        : '';
      return `<div class="msg-item ${replyClass}">
        <div class="msg-head">
          <span class="msg-role-tag by-${by}">${tagText}</span>
          <span class="msg-time">${esc(m.createdAt || '')}</span>
        </div>
        <p class="msg-text">${esc(m.text || '')}</p>
        ${replyHtml}
      </div>`;
    }).join('');
  }

  // 🆕 更新未读回复徽章（顶栏反馈Tab + 快速入口按钮）
  function updateMsgUnreadBadge(replyCount, unreadReplyCount) {
    try {
      const navTab = $('#navMessagesTab');
      const navBadge = $('#navMsgBadge');
      const quickBtn = $('#galleryQuickMsgBtn');
      const quickBadge = $('#galleryQuickBadge');
      const uploadBtn = $('#galleryQuickUploadBtn');
      // 用户登录后才显示反馈Tab
      const isLogged = state.isVerified && !!(localStorage.getItem('current_record_id') || state.verifyInfo.cosName);
      if (navTab) navTab.style.display = isLogged ? 'inline-flex' : 'none';
      if (quickBtn) {
        quickBtn.style.display = isLogged ? 'inline-flex' : 'none';
      }
      if (uploadBtn) {
        uploadBtn.style.display = isLogged ? 'inline-flex' : 'none';
      }
      // 更新未读徽章
      const hasUnread = unreadReplyCount > 0;
      const badgeText = String(unreadReplyCount > 99 ? '99+' : unreadReplyCount);
      if (navBadge) {
        if (hasUnread) {
          navBadge.style.display = 'inline-flex';
          navBadge.textContent = badgeText;
          navBadge.title = `你有 ${unreadReplyCount} 条摄影师新回复`;
        } else {
          navBadge.style.display = 'none';
          navBadge.textContent = '';
        }
      }
      if (quickBadge) {
        if (hasUnread) {
          quickBadge.style.display = 'inline-flex';
          quickBadge.textContent = badgeText;
          quickBadge.title = `你有 ${unreadReplyCount} 条摄影师新回复`;
        } else {
          quickBadge.style.display = 'none';
          quickBadge.textContent = '';
        }
      }
    } catch(e) {}
  }

  function showWaitingState(recordId) {
    const waitingState = $('#waitingState');
    const photoWrapper = $('#photoWrapper');
    const msgSection = $('#photographerMsgSection');
    if (waitingState) waitingState.style.display = 'block';
    if (photoWrapper) photoWrapper.style.display = 'none';
    // 留言板一直显示：没返图也要能给摄影师提修图需求
    if (msgSection) msgSection.style.display = 'block';

    // 刷新上传区的身份状态（抽奖完成后解除禁用）
    if (typeof window.__refreshSimpleUploader === 'function') {
      try { window.__refreshSimpleUploader(); } catch (e) {}
    }
    // recordId 在 checkPhotoStatus 里已经初始化过留言板了，这里仅在特殊情况下再尝试兜底
    if (recordId) {
      initMsgBoard(recordId);
      loadMessagesAndRender(recordId);
    } else {
      const fallback = localStorage.getItem('current_record_id');
      if (fallback) {
        initMsgBoard(fallback);
        loadMessagesAndRender(fallback);
      }
    }
  }

  function renderGalleryPhotoCard(p, recordId) {
    const pos = p.photoPosition || '-';
    const approved = !!p.publicApproved;
    const disabledAttr = approved ? ' disabled' : '';
    const btnClass = approved
      ? 'gallery-approve-btn approved'
      : 'gallery-approve-btn';
    const btnText = approved
      ? '✅ 已公开'
      : '🔓 同意公开到大家照片';
    // 撤回按钮（仅已公开的照片显示）
    const withdrawHtml = approved
      ? `<button type="button" class="gallery-withdraw-btn" data-photo-id="${p.id}" data-record-id="${recordId}">↩ 撤回公开</button>`
      : '';
    // 删除按钮（仅未公开的照片显示，已公开的需先撤回）
    const deleteHtml = !approved
      ? `<button type="button" class="gallery-delete-btn" data-photo-id="${p.id}" data-record-id="${recordId}">🗑 删除</button>`
      : '';

    const cardClass = 'gallery-photo-card';
    const imgWrapClass = 'gallery-photo-img-wrap';

    return `
      <div class="${cardClass}" data-photo-id="${p.id}" data-record-id="${recordId}">
        <div class="${imgWrapClass}">
          <img class="gallery-photo-img" src="${getThumbUrl(p.photoUrl)}" alt="照片 ${pos}" loading="lazy" referrerpolicy="no-referrer">
        </div>
        <div class="gallery-photo-meta">
          <div class="gallery-photo-pos">
            位置序号 <span class="pos-badge">#${pos}</span>
          </div>
          <div class="gallery-photo-actions">
            <button type="button" class="${btnClass}" data-photo-id="${p.id}" data-record-id="${recordId}" data-approved="${approved}"${disabledAttr}>
              ${btnText}
            </button>
            ${withdrawHtml}
            ${deleteHtml}
          </div>
        </div>
      </div>
    `;
  }

  async function handleGalleryApprove(btn, recordId) {
    const photoId = btn.dataset.photoId;
    const alreadyApproved = btn.dataset.approved === 'true';
    if (alreadyApproved || btn.disabled || btn.classList.contains('approved')) return;

    // 二次确认
    const confirmed = window.confirm(
      '确认把这张照片公开到「大家的照片」吗？\n\n' +
      '· 公开后所有进入网站的人都能看到这张照片\n' +
      '· 公开后可以随时撤回（撤回后他人不可见）\n\n' +
      '点击「确定」即同意公开。'
    );
    if (!confirmed) return;

    btn.disabled = true;
    btn.classList.add('approving');
    const originalText = btn.innerHTML;
    btn.innerHTML = '⏳ 正在公开...';

    try {
      // 读取用户身份（localStorage存）
      const savedInfo = localStorage.getItem('lottery_user_info');
      let cosName = '', wechatId = '';
      if (savedInfo) {
        try {
          const info = JSON.parse(savedInfo);
          cosName = info.cosName || '';
          wechatId = info.wechatId || '';
        } catch (e) {}
      }
      if (!cosName) cosName = localStorage.getItem('verify_cosName') || '';
      if (!wechatId) wechatId = localStorage.getItem('verify_wechatId') || '';
      if (!cosName) cosName = state.verifyInfo.cosName || '';
      if (!wechatId) wechatId = state.verifyInfo.wechatId || '';

      if (!cosName) {
        showToast('请先完成抽奖和信息登记，再公开照片哦~');
        btn.classList.remove('approving');
        btn.innerHTML = originalText;
        btn.disabled = false;
        return;
      }

      const res = await fetch(`/api/lottery/photo/${recordId}/${photoId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cosName, wechatId })
      });
      const data = await res.json();
      if (data.success) {
        btn.classList.remove('approving');
        btn.classList.add('approved');
        btn.dataset.approved = 'true';
        btn.setAttribute('disabled', 'disabled');
        btn.innerHTML = '✅ 已公开';
        const card = btn.closest('.gallery-photo-card');
        if (card) {
          card.style.border = '1px solid #10b981';
          const imgWrap = card.querySelector('.gallery-photo-img-wrap');
          if (imgWrap && !imgWrap.querySelector('.gallery-approved-tag')) {
            const tag = document.createElement('div');
            tag.className = 'gallery-approved-tag';
            tag.textContent = '已公开';
            Object.assign(tag.style, {
              position: 'absolute', top: '6px', right: '6px',
              background: '#10b981', color: '#fff', fontSize: '10px',
              fontWeight: '700', padding: '2px 6px', borderRadius: '3px',
              letterSpacing: '0.3px', zIndex: '2',
            });
            imgWrap.appendChild(tag);
          }
        }
        showToast('✅ 照片已公开到「大家的照片」');
      } else {
        showToast('提交失败：' + (data.message || '请稍后重试'));
        btn.classList.remove('approving');
        btn.innerHTML = originalText;
        btn.disabled = false;
      }
    } catch (err) {
      btn.classList.remove('approving');
      btn.innerHTML = originalText;
      btn.disabled = false;
      showToast('网络错误，请稍后重试');
    }
  }

  // 撤回已公开的照片
  async function handleGalleryWithdraw(btn, recordId) {
    const photoId = btn.dataset.photoId;
    const confirmed = window.confirm(
      '确定要撤回这张照片的公开吗？\n\n' +
      '· 撤回后，这张照片将不再显示在「大家的照片」中\n' +
      '· 照片本身不会被删除，仍保留在你的相册中\n' +
      '· 之后可以随时再次同意公开\n\n' +
      '点击「确定」撤回公开。'
    );
    if (!confirmed) return;

    btn.disabled = true;
    const originalText = btn.innerHTML;
    btn.innerHTML = '⏳ 撤回中...';

    try {
      const savedInfo = localStorage.getItem('lottery_user_info');
      let cosName = '', wechatId = '';
      if (savedInfo) {
        try { const info = JSON.parse(savedInfo); cosName = info.cosName || ''; wechatId = info.wechatId || ''; } catch (e) {}
      }
      if (!cosName) cosName = state.verifyInfo.cosName || '';
      if (!wechatId) wechatId = state.verifyInfo.wechatId || '';

      if (!cosName) {
        showToast('请先完成抽奖和信息登记');
        btn.disabled = false;
        btn.innerHTML = originalText;
        return;
      }

      const res = await fetch(`/api/lottery/photo/${recordId}/${photoId}/withdraw`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cosName, wechatId })
      });
      const data = await res.json();
      if (data.success) {
        showToast('✅ 已撤回公开');
        // 重新加载照片列表，刷新卡片状态
        checkPhotoStatus();
      } else {
        showToast('撤回失败：' + (data.message || '请稍后重试'));
        btn.disabled = false;
        btn.innerHTML = originalText;
      }
    } catch (err) {
      btn.disabled = false;
      btn.innerHTML = originalText;
      showToast('网络错误，请稍后重试');
    }
  }

  // 删除自己未公开的照片
  async function handleGalleryDelete(btn, recordId) {
    const photoId = btn.dataset.photoId;
    const confirmed = window.confirm(
      '确定要删除这张照片吗？\n\n' +
      '· 删除后不可恢复\n' +
      '· 如果已经公开，请先撤回再删除\n\n' +
      '点击「确定」删除。'
    );
    if (!confirmed) return;

    btn.disabled = true;
    const originalText = btn.innerHTML;
    btn.innerHTML = '⏳ 删除中...';

    try {
      const savedInfo = localStorage.getItem('lottery_user_info');
      let cosName = '', wechatId = '';
      if (savedInfo) {
        try { const info = JSON.parse(savedInfo); cosName = info.cosName || ''; wechatId = info.wechatId || ''; } catch (e) {}
      }
      if (!cosName) cosName = state.verifyInfo.cosName || '';
      if (!wechatId) wechatId = state.verifyInfo.wechatId || '';

      if (!cosName) {
        showToast('请先完成抽奖和信息登记');
        btn.disabled = false;
        btn.innerHTML = originalText;
        return;
      }

      const res = await fetch(`/api/lottery/photo/${recordId}/${photoId}/user-delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cosName, wechatId })
      });
      const data = await res.json();
      if (data.success) {
        showToast('✅ 已删除');
        // 重新加载照片列表
        checkPhotoStatus();
      } else {
        showToast('删除失败：' + (data.message || '请稍后重试'));
        btn.disabled = false;
        btn.innerHTML = originalText;
      }
    } catch (err) {
      btn.disabled = false;
      btn.innerHTML = originalText;
      showToast('网络错误，请稍后重试');
    }
  }

  function navItemsSetActive(pageName) {
    const navItems = $$('.nav-item');
    navItems.forEach(item => {
      item.classList.toggle('active', item.dataset.page === pageName);
    });
  }

  function initLotteryWheel() {
    const container = $('#wheelContainer');
    const prizes = CONFIG.prizes;
    const repeatCount = 15;
    let html = '';

    const displayPrizes = [
      prizes.find(p => p.level === 2),
      prizes.find(p => p.level === 1)
    ].filter(Boolean);

    for (let i = 0; i < repeatCount * displayPrizes.length; i++) {
      const prize = displayPrizes[i % displayPrizes.length];
      html += `
        <div class="prize-cell" data-prize-id="${prize.id}" data-prize-level="${prize.level}">
          <div class="prize-text-card level-${prize.level}">
            <span class="prize-label-text">${prize.label}</span>
            <span class="prize-name-text">${prize.name}</span>
          </div>
        </div>
      `;
    }

    container.innerHTML = html;

    requestAnimationFrame(() => {
      resetWheel();
    });
  }

  function initLotteryBtn() {
    const btn = $('#lotteryBtn');
    btn.addEventListener('click', async () => {
      if (state.isRolling) return;
      if (!state.isVerified) {
        showVerifyModal();
        return;
      }
      const localRecordId = localStorage.getItem('current_record_id');
      if (localRecordId) {
        // 【修复之前的误判】：不能只看 localStorage.current_record_id 就说「已抽过」
        // 管理员可能在后台点了「重置抽奖」把对应记录删了（或 JSON 文件被清空），
        // 这时浏览器里还残留着一个脏 ID，导致用户永远无法再抽奖，而且后台看不到该记录。
        // 修复：先异步调 /api/lottery/check 拿真实的 exists 状态，决定是否清脏数据。
        btn.disabled = true;
        const origText = btn.querySelector('.btn-text').innerHTML;
        try { btn.querySelector('.btn-text').textContent = '核对中…'; } catch (e) {}
        const id = getIdentity();
        let cosName = id.cosName || '';
        let wechatId = id.wechatId || '';
        if (!cosName) {
          try {
            const cached = localStorage.getItem('lottery_user_info');
            if (cached) { const o = JSON.parse(cached || '{}'); cosName = o.cosName || ''; wechatId = o.wechatId || ''; }
          } catch (e) {}
        }
        if (!cosName) {
          btn.disabled = false;
          try { btn.querySelector('.btn-text').innerHTML = origText; } catch (e) {}
          showVerifyModal();
          return;
        }
        try {
          const r = await fetch('/api/lottery/check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cosName: cosName, wechatId: wechatId })
          });
          const d = await r.json();
          if (d && d.exists && d.record && d.record.id) {
            // 真实存在：更新本地 recordId（若与后端不一致以后端为准），跳转 gallery
            localStorage.setItem('current_record_id', String(d.record.id));
            state.verifyInfo.recordId = d.record.id;
            showToast('您已经参与过抽奖了');
            if (state.currentPage !== 'gallery') switchPage('gallery');
          } else {
            // 【重点修复】后台没这条记录，说明用户已重置或数据被清理
            // 清掉脏的 current_record_id，让用户能重新抽奖
            hardResetIdentity(true);
            showToast('身份记录已重置，您可以重新抽奖啦');
            drawAndStartLottery();
            return;
          }
        } catch (e) {
          // 网络错误：不武断跳 gallery，保持原状可重试
          showToast('网络异常，请重试');
        } finally {
          btn.disabled = false;
          try { btn.querySelector('.btn-text').innerHTML = origText; } catch (e) {}
        }
      } else {
        drawAndStartLottery();
      }
    });
  }

  // 【50人抽奖池】先提交后端获取中奖结果，再播放动画
  async function drawAndStartLottery() {
    const btn = $('#lotteryBtn');
    btn.disabled = true;
    try { btn.querySelector('.btn-text').textContent = '抽奖中...'; } catch(e) {}

    try {
      // 从 localStorage 取身份（多重兜底）
      let cosName = '', wechatId = '';
      try {
        const cached = localStorage.getItem('lottery_user_info');
        if (cached) { const o = JSON.parse(cached || '{}'); cosName = (o.cosName || '').trim(); wechatId = (o.wechatId || '').trim(); }
      } catch(e) {}
      if (!cosName) cosName = (localStorage.getItem('verify_cosName') || '').trim();
      if (!wechatId) wechatId = (localStorage.getItem('verify_wechatId') || '').trim();
      if (!cosName) cosName = (state.verifyInfo.cosName || '').trim();
      if (!wechatId) wechatId = (state.verifyInfo.wechatId || '').trim();

      // 提交后端，由服务端50人抽奖池决定结果
      const resp = await fetch('/api/lottery/record', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cosName: cosName, wechatId: wechatId, timestamp: new Date().toISOString() })
      });
      const result = await resp.json();

      if (resp.status === 409 && result.existing && result.record) {
        localStorage.setItem('current_record_id', String(result.record.id));
        state.verifyInfo.recordId = result.record.id;
        _persistFullIdentity(cosName, wechatId);
        showToast('您已经参与过抽奖了');
        if (state.currentPage !== 'gallery') switchPage('gallery');
        btn.disabled = false;
        try { btn.querySelector('.btn-text').textContent = '开始抽奖'; } catch(e) {}
        return;
      }

      if (result.success && result.record) {
        localStorage.setItem('current_record_id', String(result.record.id));
        state.verifyInfo.recordId = result.record.id;
        _persistFullIdentity(cosName, wechatId);
        const lv = result.record.prizeLevel;
        const winningPrize = {
          id: lv === 1 ? 1 : lv === 2 ? 2 : 0,
          name: result.record.prizeName,
          level: lv,
          label: lv === 1 ? '一等奖' : lv === 2 ? '二等奖' : '谢谢参与',
          unlimited: lv === 0
        };
        startLottery(winningPrize);
      } else {
        showToast(result.message || '抽奖失败，请重试');
        btn.disabled = false;
        try { btn.querySelector('.btn-text').textContent = '开始抽奖'; } catch(e) {}
      }
    } catch(e) {
      console.error('Draw lottery error:', e);
      showToast('网络异常，请重试');
      btn.disabled = false;
      try { btn.querySelector('.btn-text').textContent = '开始抽奖'; } catch(e) {}
    }
  }

  function getWinningPrize() {
    const rates = CONFIG.winRates;
    const rand = Math.random();
    const firstPrize = CONFIG.prizes.find(p => p.level === 1);
    const secondPrize = CONFIG.prizes.find(p => p.level === 2);
    // 一等奖（20元红包）：1%，且库存 > 0（最稀有）
    if (firstPrize && state.firstPrizeRemaining > 0 && rand < rates.first) {
      return firstPrize;
    }
    // 二等奖（手办）：5%，且库存 > 0
    if (secondPrize && state.secondPrizeRemaining > 0 && rand < rates.first + rates.second) {
      return secondPrize;
    }
    // 谢谢参与：剩余 94%
    return { id: 0, name: '谢谢参与', level: 0, label: '谢谢参与', unlimited: true };
  }

  function startLottery(winningPrize) {
    state.isRolling = true;
    const btn = $('#lotteryBtn');
    btn.disabled = true;
    btn.querySelector('.btn-text').textContent = '抽奖中...';

    const container = $('#wheelContainer');
    const cellWidth = getCellWidth();
    const centerOffset = getCenterOffset();

    // 优先使用后端返回的结果；未传入时fallback到前端计算（兼容管理员模式）
    if (!winningPrize) winningPrize = getWinningPrize();
    const displayPrizes = [
      CONFIG.prizes.find(p => p.level === 2),
      CONFIG.prizes.find(p => p.level === 1)
    ].filter(Boolean);
    let winningPrizeIndex = displayPrizes.findIndex(p => p.id === winningPrize.id);
    // 谢谢参与（id=0）不在 displayPrizes 中 → 随机落在某个格子上（视觉效果）
    if (winningPrizeIndex < 0) {
      winningPrizeIndex = Math.floor(Math.random() * Math.max(displayPrizes.length, 1));
    }

    const targetCycle = 6;
    const totalCells = targetCycle * displayPrizes.length + winningPrizeIndex + displayPrizes.length * 3;
    const totalDistance = totalCells * cellWidth;

    const startTime = performance.now();
    const duration = 4000;
    const startX = 0;
    const endX = -centerOffset - totalDistance;

    let lastActiveIndex = -1;

    function animate(currentTime) {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);

      // 平滑缓动：加速(0~15%) → 匀速(15~55%) → 减速(55~100%)
      let easeProgress;
      if (progress < 0.15) {
        // 二次加速
        const t = progress / 0.15;
        easeProgress = 0.15 * t * t;
      } else if (progress < 0.55) {
        // 匀速
        easeProgress = 0.15 + (progress - 0.15) / 0.4 * 0.4;
      } else {
        // 三次减速
        const t = (progress - 0.55) / 0.45;
        easeProgress = 0.55 + (1 - Math.pow(1 - t, 3)) * 0.45;
      }

      const currentX = startX + (endX - startX) * easeProgress;
      container.style.transform = `translateX(${currentX}px)`;

      // 只更新变化的 active cell
      const centerPosition = -currentX - centerOffset;
      const centerCellIndex = Math.round(centerPosition / cellWidth);
      if (centerCellIndex !== lastActiveIndex) {
        const cells = container.children;
        if (lastActiveIndex >= 0 && cells[lastActiveIndex]) {
          cells[lastActiveIndex].classList.remove('active');
        }
        if (cells[centerCellIndex]) {
          cells[centerCellIndex].classList.add('active');
        }
        lastActiveIndex = centerCellIndex;
      }

      if (progress < 1) {
        requestAnimationFrame(animate);
      } else {
        finishLottery(winningPrize, endX, cellWidth, centerOffset);
      }
    }

    requestAnimationFrame(animate);
  }

  function finishLottery(winningPrize, finalX, cellWidth, centerOffset) {
    const baseline = $('#prizeBaseline');
    if (baseline) baseline.classList.add('winning-flash');

    const container = $('#wheelContainer');

    // 用已知的 finalX 精确计算中奖格子
    const centerPosition = -finalX - centerOffset;
    const centerCellIndex = Math.round(centerPosition / cellWidth);

    const cells = container.children;
    const winningCell = cells[centerCellIndex];
    if (winningCell) {
      winningCell.classList.add('winning');
    }

    // 小幅弹跳效果
    const bounceDistance = 3;
    container.style.transition = 'transform 0.08s ease-out';
    container.style.transform = `translateX(${finalX - bounceDistance}px)`;

    setTimeout(() => {
      container.style.transform = `translateX(${finalX}px)`;
      setTimeout(() => {
        container.style.transition = '';
      }, 160);
    }, 80);

    setTimeout(() => {
      showPrizeModal(winningPrize);
      // 记录已在动画前由后端50人抽奖池决定并提交，此处不再重复提交
      loadFirstPrizeRemaining();
    }, 600);

    if (winningPrize.level === 1 && state.firstPrizeRemaining > 0) {
      state.firstPrizeRemaining--;
    }
    if (winningPrize.level === 2 && state.secondPrizeRemaining > 0) {
      state.secondPrizeRemaining--;
    }
  }

  function initRulesToggle() {
    // 规则已改为始终显示，无需切换
  }

  function initPrizeModal() {
    const modal = $('#prizeModal');
    const confirmBtn = $('#modalConfirm');
    const goGalleryBtn = $('#modalGoGallery');

    // 【核心修复】普通用户抽奖完成后绝对不能清身份信息！
    // 之前的 bug：switchPage('gallery') 后 600ms 调用 resetForNextPerson()，
    //  直接把 localStorage 的 current_record_id + lottery_user_info 全清掉，
    //  把 state.verifyInfo 也清空，导致用户进入返图页点"发送给摄影师"
    //  时立刻报错「身份丢失」/「请先完成抽奖」。
    // 修复：普通用户只跳 gallery，永远不主动清除身份！
    function closeModalAction() {
      hidePrizeModal();
      switchPage('gallery');
    }

    if (confirmBtn) {
      confirmBtn.addEventListener('click', closeModalAction);
    }

    if (goGalleryBtn) {
      goGalleryBtn.addEventListener('click', () => {
        hidePrizeModal();
        switchPage('gallery');
      });
    }

    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModalAction();
      });
    }
  }

  // 【彻底禁用身份清除】抽奖完成后只做 UI 重置，绝不清除身份/recordId/localStorage
  // 之前的 resetForNextPerson 会清除 state.verifyInfo、current_record_id、lottery_user_info，
  // 直接导致用户留言时提示「身份丢失」。现在只保留视觉层重置（滚轮/按钮高亮），
  // 身份信息和抽奖记录永久保留在 localStorage。
  function resetForNextPerson() {
    state.isRolling = false;
    const btn = $('#lotteryBtn');
    if (btn) {
      btn.disabled = false;
      const t = btn.querySelector('.btn-text');
      if (t) t.textContent = '开始抽奖';
    }
    // 清除验证弹窗里的输入框（不影响身份，只是UI清爽）
    const cosNameInput = $('#cosName');
    const wechatInput = $('#wechatId');
    if (cosNameInput) cosNameInput.value = '';
    if (wechatInput) wechatInput.value = '';
    resetWheel();
    // 清除中奖高亮
    try {
      const cells = document.querySelectorAll('.prize-cell');
      cells.forEach(cell => cell.classList.remove('active', 'winning'));
    } catch (e) {}
    const baseline = $('#prizeBaseline');
    if (baseline) baseline.classList.remove('winning-flash');
    loadFirstPrizeRemaining();
    // ⚠️ 绝对不要再清 current_record_id / lottery_user_info / state.verifyInfo / state.isVerified / localStorage！
  }

  function showPrizeModal(prize) {
    const modal = $('#prizeModal');
    const nameEl = $('#prizeName');
    const badgeEl = $('#modalBadge');
    const imgWrap = $('#modalPrizeImageWrap');

    if (nameEl) nameEl.textContent = prize.name;
    if (badgeEl) {
      const levelNames = { 1: '一等奖', 2: '二等奖', 0: '谢谢参与' };
      badgeEl.textContent = levelNames[prize.level] || '谢谢参与';
    }
    if (imgWrap) {
      imgWrap.innerHTML = `
        <div class="modal-prize-text-card level-${prize.level}">
          <span class="modal-prize-label">${prize.label}</span>
          <span class="modal-prize-name">${prize.name}</span>
        </div>
      `;
    }

    if (modal) {
      modal.classList.add('show');
    }
  }

  function hidePrizeModal() {
    const modal = $('#prizeModal');
    if (modal) {
      modal.classList.remove('show');
    }
  }

  function initVerifyModal() {
    const modal = $('#verifyModal');
    const confirmBtn = $('#verifyConfirm');
    const cosNameInput = $('#cosName');
    const wechatInput = $('#wechatId');

    // 统一的按钮状态刷新：只需填 COS 名称 → 启用；否则禁用（已去掉微信号必填）
    function refreshVerifyBtn() {
      if (!confirmBtn) return;
      const cos = cosNameInput ? cosNameInput.value.trim() : '';
      const ok = !!cos;
      confirmBtn.disabled = !ok;
      confirmBtn.style.opacity = ok ? '1' : '0.55';
      confirmBtn.style.pointerEvents = ok ? 'auto' : 'none';
      confirmBtn.style.cursor = ok ? 'pointer' : 'not-allowed';
    }

    if (confirmBtn) {
      confirmBtn.addEventListener('click', handleVerifyConfirm);
      // 初始化一次按钮状态（以防弹窗初始显示时输入框有值）
      refreshVerifyBtn();
    }

    if (cosNameInput) {
      cosNameInput.addEventListener('input', () => {
        state.verifyInfo.cosName = cosNameInput.value.trim();
        refreshVerifyBtn();
      });
    }

    if (wechatInput) {
      wechatInput.addEventListener('input', () => {
        state.verifyInfo.wechatId = wechatInput.value.trim();
        refreshVerifyBtn();
      });
    }

    // 暴露给外部：弹窗显示时立即同步一次状态（避免历史值不触发 input）
    window.__refreshVerifyBtn = refreshVerifyBtn;
  }

  function showVerifyModal() {
    const modal = $('#verifyModal');
    if (modal) {
      modal.classList.add('show');
    }
    // 弹窗显示时：根据当前输入框或 state 的值刷新按钮状态
    const cosInput = $('#cosName');
    const wxInput = $('#wechatId');
    const confirmBtn = $('#verifyConfirm');
    try {
      // 如果输入框是空的，但 state 里有值（例如登录过），预填到输入框
      if (cosInput && !cosInput.value.trim() && state.verifyInfo.cosName) {
        cosInput.value = state.verifyInfo.cosName;
      }
      if (wxInput && !wxInput.value.trim() && state.verifyInfo.wechatId) {
        wxInput.value = state.verifyInfo.wechatId;
      }
      // 刷新按钮
      if (confirmBtn) {
        const cos = (cosInput ? cosInput.value : '').trim() || state.verifyInfo.cosName || '';
        const ok = !!cos;
        confirmBtn.disabled = !ok;
        confirmBtn.style.opacity = ok ? '1' : '0.55';
        confirmBtn.style.pointerEvents = ok ? 'auto' : 'none';
        confirmBtn.style.cursor = ok ? 'pointer' : 'not-allowed';
      }
    } catch (e) {}
    // 调一下 initVerifyModal 暴露的刷新函数（兜底）
    try { if (typeof window.__refreshVerifyBtn === 'function') window.__refreshVerifyBtn(); } catch (e) {}
  }

  function hideVerifyModal() {
    const modal = $('#verifyModal');
    if (modal) {
      modal.classList.remove('show');
    }
  }

  function handleVerifyConfirm() {
    // 【修复】优先从 DOM 输入框实际值读取，避免 state 因异步/时序问题丢值
    //   （例如：用户填完后、点击确认前，state 被意外清空的极端情况）
    //   兜底再回退到 state.verifyInfo，最后再回退 localStorage
    const cosInput = $('#cosName');
    const wxInput = $('#wechatId');
    let cosName = (cosInput ? cosInput.value : '').trim();
    let wechatId = (wxInput ? wxInput.value : '').trim();
    if (!cosName) cosName = (state.verifyInfo.cosName || '').trim();
    if (!wechatId) wechatId = (state.verifyInfo.wechatId || '').trim();
    // 最后兜底：从 localStorage 读取（极端防丢失）
    try {
      if (!cosName || !wechatId) {
        const cached = localStorage.getItem('lottery_user_info');
        if (cached) {
          try {
            const o = JSON.parse(cached || '{}');
            if (!cosName) cosName = (o.cosName || '').trim();
            if (!wechatId) wechatId = (o.wechatId || '').trim();
          } catch (e) {}
        }
      }
      if (!cosName) cosName = (localStorage.getItem('verify_cosName') || '').trim();
      if (!wechatId) wechatId = (localStorage.getItem('verify_wechatId') || '').trim();
    } catch (e) {}
    // 同步回 state（保证后续逻辑一致）
    if (cosName) state.verifyInfo.cosName = cosName;
    if (wechatId) state.verifyInfo.wechatId = wechatId;

    if (!cosName) {
      showToast('请输入COS名称');
      return;
    }

    const confirmBtn = $('#verifyConfirm');
    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.textContent = '验证中...';
    }

    fetch('/api/lottery/check', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        cosName: cosName,
        wechatId: wechatId
      })
    })
    .then(res => res.json())
    .then(data => {
      // 【不再区分管理员】固定按普通用户处理
      _persistFullIdentity(cosName, wechatId);

      // 【待发消息恢复】如果用户是在"写留言过程中"因为身份缺失被打断，那么用户填完身份后，
      //   自动回到 gallery 的留言区，把刚才写的文案放回去。
      let pendingMsg = '';
      try { pendingMsg = localStorage.getItem('msg_pending_text') || ''; } catch (e) {}

      if (data.success && data.exists && data.record) {
        localStorage.setItem('current_record_id', data.record.id.toString());
        state.verifyInfo.recordId = data.record.id;
        state.isVerified = true;
        // 【关键】先切到返图页（后台先切，动画已经开始），再关登记弹窗 → 用户永远看不到中间态
        if (pendingMsg) {
          if (state.currentPage !== 'gallery') switchPage('gallery');
          setTimeout(() => jumpToGalleryMessageSection(false), 420);
          setTimeout(() => {
            const ta = document.getElementById('msgTextarea');
            if (ta && pendingMsg) {
              ta.value = pendingMsg;
              try { ta.dispatchEvent(new Event('input', { bubbles: true })); } catch (e) {}
              try { ta.focus(); } catch (e) {}
            }
            try { localStorage.removeItem('msg_pending_text'); } catch (e) {}
          }, 800);
          setTimeout(hideVerifyModal, 320);
        } else {
          if (state.currentPage !== 'gallery') switchPage('gallery');
          // 等页面切换动画进行到快完成，再关掉弹窗（避免底下露出来）
          setTimeout(() => {
            hideVerifyModal();
            showToast('欢迎回来！');
          }, 300);
        }
      } else {
        state.isVerified = true;
        try { if (pendingMsg) localStorage.removeItem('msg_pending_text'); } catch (e) {}
        // 【修复：登记后不再自动开始抽奖】必须由用户手动点击「开始抽奖」才触发4秒动画
        if (state.currentPage !== 'lottery') switchPage('lottery');
        hideVerifyModal();
        const btn2 = $('#lotteryBtn');
        if (btn2) {
          btn2.disabled = false;
          const t2 = btn2.querySelector('.btn-text');
          if (t2) t2.textContent = '开始抽奖';
        }
        showToast('已登记，点击下方「开始抽奖」按钮即可参与抽奖');
      }
    })
    .catch(err => {
      console.error('Check error:', err);
      let pendingMsg = '';
      try { pendingMsg = localStorage.getItem('msg_pending_text') || ''; } catch (e) {}
      // 网络出错仍然允许进入（防止完全无法使用），但仍保存信息，不再自动抽
      // 【修复】同样用统一的持久化函数
      _persistFullIdentity(cosName, wechatId);
      state.isVerified = true;
      hideVerifyModal();
      try { if (pendingMsg) localStorage.removeItem('msg_pending_text'); } catch (e) {}
      const btn3 = $('#lotteryBtn');
      if (btn3) {
        btn3.disabled = false;
        const t3 = btn3.querySelector('.btn-text');
        if (t3) t3.textContent = '开始抽奖';
      }
      showToast('已登记，点击下方「开始抽奖」按钮参与抽奖');
    })
    .finally(() => {
      if (confirmBtn) {
        confirmBtn.disabled = false;
        confirmBtn.textContent = '确认参与';
      }
    });
  }

  function submitLotteryRecord(prize) {
    try {
      // 【修复】提交抽奖记录前，强制从 localStorage 取值（因为它不会被意外清空）
      // 避免 state.verifyInfo 因时序/异步问题临时为空，导致提交空字符串
      let cosName = '', wechatId = '';
      try {
        const cached = localStorage.getItem('lottery_user_info');
        if (cached) { const o = JSON.parse(cached || '{}'); cosName = (o.cosName || '').trim(); wechatId = (o.wechatId || '').trim(); }
      } catch (e) {}
      if (!cosName) cosName = (localStorage.getItem('verify_cosName') || '').trim();
      if (!wechatId) wechatId = (localStorage.getItem('verify_wechatId') || '').trim();
      if (!cosName) cosName = (state.verifyInfo.cosName || '').trim();
      if (!wechatId) wechatId = (state.verifyInfo.wechatId || '').trim();
      if (cosName) state.verifyInfo.cosName = cosName;
      if (wechatId) state.verifyInfo.wechatId = wechatId;

      fetch('/api/lottery/record', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          cosName: cosName,
          wechatId: wechatId,
          prizeLevel: prize.level,
          prizeName: prize.name,
          timestamp: new Date().toISOString()
        })
      })
      .then(res => {
        const status = res.status;
        return res.json().then(data => ({ data, status }));
      })
      .then(({ data, status }) => {
        if (status === 409 && data.existing && data.record) {
          localStorage.setItem('current_record_id', data.record.id.toString());
          state.verifyInfo.recordId = data.record.id;
          _persistFullIdentity(cosName, wechatId);
          showToast('您已经参与过抽奖了');
          if (state.currentPage !== 'gallery') switchPage('gallery');
        } else if (data.success && data.record) {
          localStorage.setItem('current_record_id', data.record.id.toString());
          state.verifyInfo.recordId = data.record.id;
          _persistFullIdentity(cosName, wechatId);
        }
      })
      .catch(err => {
        console.error('Failed to submit record:', err);
      });
    } catch (e) {
      console.error('Submit record error:', e);
    }
  }

  // 【修复】统一的身份持久化函数：写 localStorage 的 3 个 key + 同步 state
  function _persistFullIdentity(cosName, wechatId) {
    try {
      // 【去微信号】只要有 COS 名称就认为是有效身份
      if (!cosName) return;
      const saveInfo = { cosName: String(cosName).trim(), wechatId: String(wechatId || '').trim() };
      localStorage.setItem('lottery_user_info', JSON.stringify(saveInfo));
      localStorage.setItem('verify_cosName', saveInfo.cosName);
      localStorage.setItem('verify_wechatId', saveInfo.wechatId);
      localStorage.setItem('is_verified', '1');
      // 同步回 state
      state.verifyInfo.cosName = saveInfo.cosName;
      state.verifyInfo.wechatId = saveInfo.wechatId;
      state.isVerified = true;
    } catch (e) {
      console.error('Persist identity error:', e);
    }
  }

  // ====================================================
  // 【核心修复】身份信息同步：统一入口，确保 state 和 localStorage 永远一致
  // 解决问题：抽奖后切到返图页留言时 state.verifyInfo.cosName/wechatId 丢失
  // ====================================================
  function syncIdentityFromStorageToState() {
    // 从 localStorage 读 → 回填到 state（兜底：防止 state 在切换页面/刷新后丢数据）
    try {
      const s = localStorage.getItem('lottery_user_info');
      if (s) {
        const o = JSON.parse(s || '{}');
        if (o.cosName) state.verifyInfo.cosName = String(o.cosName).trim();
        if (o.wechatId) state.verifyInfo.wechatId = String(o.wechatId).trim();
      }
    } catch (e) {}
    const rid = localStorage.getItem('current_record_id');
    if (rid) {
      const n = parseInt(rid, 10);
      if (!isNaN(n)) state.verifyInfo.recordId = n;
    }
    if (state.verifyInfo.cosName) {
      state.isVerified = true;
      localStorage.setItem('is_verified', '1');
    }
  }

  function getIdentity() {
    // 先执行一次同步：确保 state 没丢
    syncIdentityFromStorageToState();
    const recordId = localStorage.getItem('current_record_id')
      || (state && state.verifyInfo && state.verifyInfo.recordId)
      || null;
    let cosName = '', wechatId = '';
    try {
      const s = localStorage.getItem('lottery_user_info');
      if (s) { const o = JSON.parse(s || '{}'); cosName = (o.cosName || '').trim(); wechatId = (o.wechatId || '').trim(); }
    } catch (e) {}
    if (!cosName) cosName = (localStorage.getItem('verify_cosName') || (state && state.verifyInfo && state.verifyInfo.cosName) || '').trim();
    if (!wechatId) wechatId = (localStorage.getItem('verify_wechatId') || (state && state.verifyInfo && state.verifyInfo.wechatId) || '').trim();
    // 最后兜底：再从 state 读一次（防止 localStorage 还没写进去的极端时机）
    if (!cosName && state && state.verifyInfo && state.verifyInfo.cosName) cosName = state.verifyInfo.cosName.trim();
    if (!wechatId && state && state.verifyInfo && state.verifyInfo.wechatId) wechatId = state.verifyInfo.wechatId.trim();
    const isVerified = !!(state && state.isVerified)
      || (localStorage.getItem('is_verified') === '1')
      || (!!cosName && !!recordId);
    return { recordId, cosName, wechatId, isVerified };
  }

  function showToast(message) {
    const toast = $('#toast');
    if (!toast) {
      const newToast = document.createElement('div');
      newToast.id = 'toast';
      newToast.className = 'toast';
      document.body.appendChild(newToast);
    }

    const toastEl = $('#toast');
    toastEl.textContent = message;
    toastEl.classList.add('show');

    setTimeout(() => {
      toastEl.classList.remove('show');
    }, 2000);
  }

  function initPageScroll() {
    const galleryPage = $('#page-gallery');
    const navbar = $('#navbar');

    if (galleryPage && navbar) {
      let _scrollTimer = null;
      galleryPage.addEventListener('scroll', () => {
        if (_scrollTimer) return;
        _scrollTimer = requestAnimationFrame(() => {
          if (galleryPage.scrollTop > 100) {
            navbar.classList.add('scrolled');
          } else {
            navbar.classList.remove('scrolled');
          }
          _scrollTimer = null;
        });
      });
    }
  }

  // ===== 抽奖按钮下方：人物围绕按钮 3 圈半环形彩蛋（九宫格切图 + 抠图 + 弧线排列） =====

  function loadSheetImage(url) {
    return new Promise(function(resolve, reject) {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = function() { resolve(img); };
      img.onerror = function(e) { reject(e); };
      img.src = url;
    });
  }

  // ============================================================
  // A2【用户要求】：AI图片不再把背景和人物分开来 —— 直接单张裁取（背景+人物完整一整张，不抠不透明不分离）
  // 移除之前把纯白色背景抠成透明的复杂算法，只做：九宫格整图 → 按row/col裁成9格 → 输出为整幅JPG卡片
  // （这样绝对不会出现「抠图失败导致缺头缺腿、五官悬浮、人物只有半个」的bug）
  // ============================================================
  function cutoutCellFromSheet(sheetImg, row, col, rows, cols, maxDim) {
    const W = sheetImg.naturalWidth || sheetImg.width;
    const H = sheetImg.naturalHeight || sheetImg.height;
    if (!W || !H) return Promise.resolve('');
    const cellW = Math.max(1, Math.round(W / cols));
    const cellH = Math.max(1, Math.round(H / rows));
    // 轻微去边（防止每格边界的细分割线露出）
    const insetX = Math.max(2, Math.round(cellW * 0.012));
    const insetY = Math.max(2, Math.round(cellH * 0.012));
    const sx = Math.max(0, col * cellW + insetX);
    const sy = Math.max(0, row * cellH + insetY);
    const sw = Math.min(W - sx, cellW - insetX * 2);
    const sh = Math.min(H - sy, cellH - insetY * 2);
    if (sw <= 4 || sh <= 4) return Promise.resolve('');
    const maxS = maxDim || 720;  // 用户要清晰，放大一点（之前560 → 720）
    let dw = sw, dh = sh;
    const ratio = Math.min(1.5, maxS / Math.max(sw, sh));
    if (ratio < 1) { dw = Math.max(1, Math.round(sw * ratio)); dh = Math.max(1, Math.round(sh * ratio)); }
    else { dw = sw; dh = sh; }
    const cvs = document.createElement('canvas');
    cvs.width = dw; cvs.height = dh;
    const ctx = cvs.getContext('2d', { alpha: false, willReadFrequently: false });
    if (!ctx) return Promise.resolve('');
    // 先刷一层白底（JPG不支持透明，避免canvas默认透明在输出时变黑色）
    ctx.fillStyle = '#FFFFFF';
    ctx.fillRect(0, 0, dw, dh);
    // 直接整幅draw（不做任何抠图处理）→ 就是单张有人物+有完整背景的画面
    ctx.drawImage(sheetImg, sx, sy, sw, sh, 0, 0, dw, dh);
    try { return Promise.resolve(cvs.toDataURL('image/jpeg', 0.92)); }
    catch (e) { try { return Promise.resolve(cvs.toDataURL('image/png')); } catch (e2) { return Promise.resolve(''); } }
  }

  function cutoutWhiteBackgroundCVS(cvs, ctx) {
    return new Promise(function(resolve) {
      try {
        const cw = cvs.width, ch = cvs.height;
        const imgData = ctx.getImageData(0, 0, cw, ch);
        const buf = imgData.data;
        const N = cw * ch;
        const LArr = new Float32Array(N);
        const SArr = new Float32Array(N);
        // ===== Step 0: 预计算 L/S/RGB方差 数组 =====
        for (let i = 0; i < N; i++) {
          const o = i * 4;
          const r = buf[o], g = buf[o+1], b = buf[o+2];
          LArr[i] = 0.299 * r + 0.587 * g + 0.114 * b;
          const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
          SArr[i] = mx > 0 ? (mx - mn) / mx : 0;
        }
        function rgbDifAt(i) {
          const o = i * 4;
          const r = buf[o], g = buf[o+1], b = buf[o+2];
          return Math.max(Math.abs(r-g), Math.abs(g-b), Math.abs(b-r));
        }
        // ===== Step 1: 候选标记（更激进，更彻底抠净白边） =====
        const BG = 1, EDGE = 2;
        const tag = new Uint8Array(N);
        for (let i = 0; i < N; i++) {
          const L = LArr[i], S = SArr[i];
          const d = rgbDifAt(i);
          // 白/近白背景候选（阈值比之前低，保证连半透明白点也清掉）
          if      (S < 0.06 && L >= 200) tag[i] = BG;
          else if (S < 0.12 && L >= 218) tag[i] = BG;
          else if (S < 0.22 && L >= 232) tag[i] = BG;
          else if (S < 0.38 && L >= 244) tag[i] = EDGE;
          else if (d <= 14 && L >= 230)  tag[i] = BG;
          else if (d <= 24 && L >= 244)  tag[i] = EDGE;
        }
        const queue = new (N < 65536 ? Uint16Array : Uint32Array)(N * 3);
        let qh = 0, qt = 0;
        const visited = new Uint8Array(N);
        function enqueue(i) {
          if (visited[i]) return;
          visited[i] = 1;
          queue[qt++] = i;
        }
        // ===== Step 1-2: 边框 4px 强制种子 + 四角 8×8 扩散 =====
        const BAND = 4;
        for (let x = 0; x < cw; x++) {
          for (let b = 0; b < BAND; b++) {
            enqueue(b * cw + x);
            enqueue((ch - 1 - b) * cw + x);
          }
        }
        for (let y = BAND; y < ch - BAND; y++) {
          for (let b = 0; b < BAND; b++) {
            enqueue(y * cw + b);
            enqueue(y * cw + (cw - 1 - b));
          }
        }
        const CORNER = Math.min(10, Math.round(Math.min(cw,ch) * 0.10));
        for (let yy = 0; yy < CORNER; yy++) for (let xx = 0; xx < CORNER; xx++) { enqueue(yy*cw+xx); enqueue(yy*cw+(cw-1-xx)); enqueue((ch-1-yy)*cw+xx); enqueue((ch-1-yy)*cw+(cw-1-xx)); }
        // ===== Step 2: 第一轮 BFS 扩散（更激进） =====
        while (qh < qt) {
          const i = queue[qh++];
          const L = LArr[i], S = SArr[i], d = rgbDifAt(i);
          const isClear =
            tag[i] === BG || tag[i] === EDGE ||
            (S < 0.08 && L >= 208) ||
            (S < 0.16 && L >= 224) ||
            (S < 0.30 && L >= 238) ||
            (S < 0.46 && L >= 248) ||
            (d <= 14 && L >= 228) ||
            (d <= 26 && L >= 244);
          if (!isClear) continue;
          buf[i * 4 + 3] = 0;
          const y = (i / cw) | 0, x = i - y * cw;
          for (let dy = -1; dy <= 1; dy++) {
            for (let dx = -1; dx <= 1; dx++) {
              if (!dx && !dy) continue;
              const nx = x + dx, ny = y + dy;
              if (nx < 0 || nx >= cw || ny < 0 || ny >= ch) continue;
              enqueue(ny * cw + nx);
            }
          }
        }
        // ===== Step 2-1: 二次 BFS 反扫（更激进收紧边缘残留白点） =====
        const visited2 = new Uint8Array(N);
        qh = 0; qt = 0;
        for (let y = 0; y < ch; y++) {
          for (let x = 0; x < cw; x++) {
            const i = y * cw + x;
            if (buf[i*4+3] > 0) continue;
            for (let dy = -1; dy <= 1; dy++) {
              for (let dx = -1; dx <= 1; dx++) {
                if (!dx && !dy) continue;
                const nx = x + dx, ny = y + dy;
                if (nx < 0 || nx >= cw || ny < 0 || ny >= ch) continue;
                const ni = ny * cw + nx;
                if (buf[ni * 4 + 3] > 0 && !visited2[ni]) {
                  const L2 = LArr[ni], S2 = SArr[ni], d2 = rgbDifAt(ni);
                  const ok =
                    (S2 < 0.18 && L2 >= 224) ||
                    (S2 < 0.08 && L2 >= 208) ||
                    (d2 <= 16 && L2 >= 232) ||
                    (d2 <= 28 && L2 >= 244);
                  if (ok) { visited2[ni] = 1; queue[qt++] = ni; }
                }
              }
            }
          }
        }
        while (qh < qt) {
          const i = queue[qh++];
          const a0 = buf[i*4+3];
          if (a0 > 0) { buf[i*4+3] = Math.max(0, Math.round(a0 * 0.38)); }
          const y = (i / cw) | 0, x = i - y * cw;
          for (let dy = -1; dy <= 1; dy++) {
            for (let dx = -1; dx <= 1; dx++) {
              if (!dx && !dy) continue;
              const nx = x + dx, ny = y + dy;
              if (nx < 0 || nx >= cw || ny < 0 || ny >= ch) continue;
              const ni = ny * cw + nx;
              if (buf[ni * 4 + 3] <= 0 || visited2[ni]) continue;
              const L3 = LArr[ni], S3 = SArr[ni], d3 = rgbDifAt(ni);
              const ok3 =
                (S3 < 0.18 && L3 >= 222) ||
                (S3 < 0.08 && L3 >= 206) ||
                (d3 <= 16 && L3 >= 230) ||
                (d3 <= 28 && L3 >= 242);
              if (ok3) { visited2[ni] = 1; queue[qt++] = ni; }
            }
          }
        }
        // ===== Step 3: 边缘像素分级软化（更彻底清灰边） =====
        let pixelCount = 0;
        const edgeMask = new Uint8Array(N);
        for (let y = 0; y < ch; y++) {
          for (let x = 0; x < cw; x++) {
            const i = y * cw + x;
            if (buf[i * 4 + 3] === 0) continue;
            let hasTrans = false;
            for (let dy = -1; dy <= 1 && !hasTrans; dy++) {
              for (let dx = -1; dx <= 1 && !hasTrans; dx++) {
                if (!dx && !dy) continue;
                const nx = x + dx, ny = y + dy;
                if (nx < 0 || nx >= cw || ny < 0 || ny >= ch) { hasTrans = true; break; }
                if (buf[(ny * cw + nx) * 4 + 3] === 0) hasTrans = true;
              }
            }
            if (hasTrans) edgeMask[i] = 1;
          }
        }
        for (let i = 0; i < N; i++) {
          if (!edgeMask[i]) {
            if (buf[i * 4 + 3] > 0) pixelCount++;
            continue;
          }
          const a = buf[i * 4 + 3];
          if (a === 0) continue;
          const L = LArr[i], S = SArr[i], d = rgbDifAt(i);
          // 更激进：阈值整体下移 4~6
          let thrHi = 226, thrLo = 210;
          if      (S < 0.06) { thrHi = 214; thrLo = 198; }
          else if (S < 0.12) { thrHi = 224; thrLo = 208; }
          else if (S < 0.22) { thrHi = 234; thrLo = 220; }
          else if (S < 0.36) { thrHi = 244; thrLo = 232; }
          else               { thrHi = 251; thrLo = 242; }
          if (d <= 16) { thrHi = Math.min(thrHi, 228); thrLo = Math.min(thrLo, 210); }
          else if (d <= 28) { thrHi = Math.min(thrHi, 238); thrLo = Math.min(thrLo, 222); }
          if (L >= thrHi)       buf[i * 4 + 3] = 0;
          else if (L > thrLo) {
            const t = (L - thrLo) / Math.max(1, (thrHi - thrLo));
            buf[i * 4 + 3] = Math.max(0, Math.round(a * (1 - t)));
          }
          if (buf[i * 4 + 3] > 0) pixelCount++;
        }
        if (pixelCount < 12) return resolve(cvs.toDataURL('image/png'));
        // ===== Step 4: 5 轮 8 邻域边缘衰减（更多轮，更柔和） =====
        for (let pass = 0; pass < 5; pass++) {
          const copy = new Uint8ClampedArray(buf);
          let passK;
          if      (pass < 2) passK = 0.64 + pass * 0.06;
          else if (pass < 4) passK = 0.80 + (pass - 2) * 0.05;
          else               passK = 0.90;
          for (let y = 0; y < ch; y++) {
            for (let x = 0; x < cw; x++) {
              const idx = (y * cw + x) * 4;
              const a = copy[idx + 3];
              if (a === 0) continue;
              let t0 = 0, t1 = 0, t2 = 0;
              for (let dy = -1; dy <= 1; dy++) {
                for (let dx = -1; dx <= 1; dx++) {
                  if (!dx && !dy) continue;
                  const nx = x + dx, ny = y + dy;
                  let na;
                  if (nx < 0 || nx >= cw || ny < 0 || ny >= ch) na = 0;
                  else na = copy[(ny * cw + nx) * 4 + 3];
                  if      (na < 16)  t0++;
                  else if (na < 80)  t1++;
                  else if (na < 176) t2++;
                }
              }
              if (t0 === 0) continue;
              let newA = a;
              if      (t0 >= 6) newA = 0;
              else if (t0 >= 5) newA = Math.round(a * 0.10);
              else if (t0 >= 4) newA = Math.round(a * 0.24 * passK);
              else if (t0 >= 3) newA = Math.round(a * 0.50 * passK);
              else if (t0 >= 2) newA = Math.round(a * 0.76 * passK);
              else if (t0 + t1 >= 4) newA = Math.round(a * 0.86);
              if (newA < 14) newA = 0;
              buf[idx + 3] = newA;
            }
          }
        }
        // ===== Step 5: 边缘像素去色（更彻底，范围扩大 18%） =====
        const purify = new Uint8ClampedArray(buf);
        for (let y = 0; y < ch; y++) {
          for (let x = 0; x < cw; x++) {
            const idx = (y * cw + x) * 4;
            const curA = buf[idx + 3];
            if (curA === 0 || curA >= 220) continue;
            let nearTransparent = false;
            for (let dy = -1; dy <= 1 && !nearTransparent; dy++) {
              for (let dx = -1; dx <= 1 && !nearTransparent; dx++) {
                if (!dx && !dy) continue;
                const nx = x + dx, ny = y + dy;
                if (nx < 0 || nx >= cw || ny < 0 || ny >= ch) { nearTransparent = true; break; }
                if (purify[(ny * cw + nx) * 4 + 3] < 28) nearTransparent = true;
              }
            }
            if (!nearTransparent) continue;
            const S = SArr[y * cw + x], L = LArr[y * cw + x];
            if (buf[idx + 3] > 0 && buf[idx + 3] < 210 && S < 0.20 && L >= 200) {
              const gv = Math.round(0.299 * buf[idx] + 0.587 * buf[idx+1] + 0.114 * buf[idx+2]);
              buf[idx]   = Math.round(buf[idx]   * 0.54 + gv * 0.46);
              buf[idx+1] = Math.round(buf[idx+1] * 0.54 + gv * 0.46);
              buf[idx+2] = Math.round(buf[idx+2] * 0.54 + gv * 0.46);
            }
          }
        }
        // ===== Step 6: 羽化（用 5×5 小核 + 3×3 核组合，边缘更柔和） =====
        // 6a: 先 3×3 一次（主羽化）
        let feather = new Uint8ClampedArray(buf);
        const K3 = [[1,2,1],[2,4,2],[1,2,1]];
        const KS3 = 16;
        for (let y = 0; y < ch; y++) {
          for (let x = 0; x < cw; x++) {
            const idx = (y * cw + x) * 4;
            const curA = buf[idx + 3];
            if (curA >= 252) continue;
            let hasEdge = false;
            for (let dy = -1; dy <= 1 && !hasEdge; dy++) {
              for (let dx = -1; dx <= 1 && !hasEdge; dx++) {
                if (!dx && !dy) continue;
                const nx = x + dx, ny = y + dy;
                if (nx < 0 || nx >= cw || ny < 0 || ny >= ch) { hasEdge = true; break; }
                const na = feather[(ny * cw + nx) * 4 + 3];
                if (na === 0 || na < curA * 0.55) hasEdge = true;
              }
            }
            if (!hasEdge && curA > 0) continue;
            let sum = 0, wsum = 0;
            for (let dy = -1; dy <= 1; dy++) {
              for (let dx = -1; dx <= 1; dx++) {
                const nx = x + dx, ny = y + dy;
                if (nx < 0 || nx >= cw || ny < 0 || ny >= ch) continue;
                const k = K3[dy + 1][dx + 1];
                sum += feather[(ny * cw + nx) * 4 + 3] * k;
                wsum += k;
              }
            }
            if (wsum <= 0) continue;
            const avg = sum / wsum;
            let blended;
            if (curA === 0) blended = Math.round(avg * 0.20);
            else            blended = Math.round(curA * 0.52 + avg * 0.48);
            buf[idx + 3] = Math.max(0, Math.min(255, blended));
          }
        }
        // 6b: 再一轮（细节平滑）
        feather = new Uint8ClampedArray(buf);
        for (let y = 0; y < ch; y++) {
          for (let x = 0; x < cw; x++) {
            const idx = (y * cw + x) * 4;
            const curA = buf[idx + 3];
            if (curA >= 253) continue;
            let hasEdge = false;
            for (let dy = -1; dy <= 1 && !hasEdge; dy++) {
              for (let dx = -1; dx <= 1 && !hasEdge; dx++) {
                if (!dx && !dy) continue;
                const nx = x + dx, ny = y + dy;
                if (nx < 0 || nx >= cw || ny < 0 || ny >= ch) { hasEdge = true; break; }
                const na = feather[(ny * cw + nx) * 4 + 3];
                if (na === 0) hasEdge = true;
              }
            }
            if (!hasEdge && curA > 0) continue;
            let sum = 0, wsum = 0;
            for (let dy = -1; dy <= 1; dy++) {
              for (let dx = -1; dx <= 1; dx++) {
                const nx = x + dx, ny = y + dy;
                if (nx < 0 || nx >= cw || ny < 0 || ny >= ch) continue;
                const k = K3[dy + 1][dx + 1];
                sum += feather[(ny * cw + nx) * 4 + 3] * k;
                wsum += k;
              }
            }
            if (wsum <= 0) continue;
            const avg = sum / wsum;
            let blended;
            if (curA === 0) blended = Math.round(avg * 0.16);
            else            blended = Math.round(curA * 0.62 + avg * 0.38);
            buf[idx + 3] = Math.max(0, Math.min(255, blended));
          }
        }
        // ===== Step 7: 孤立小斑点清除（阈值放宽，更彻底） =====
        const finalClean = new Uint8ClampedArray(buf);
        for (let y = 1; y < ch - 1; y++) {
          for (let x = 1; x < cw - 1; x++) {
            const idx = (y * cw + x) * 4;
            const a = finalClean[idx + 3];
            if (a === 0 || a > 64) continue;
            let s = 0;
            for (let dy = -1; dy <= 1; dy++) {
              for (let dx = -1; dx <= 1; dx++) {
                if (!dx && !dy) continue;
                s += finalClean[((y+dy) * cw + (x+dx)) * 4 + 3];
              }
            }
            if (s < 120) buf[idx + 3] = 0;
          }
        }
        // ===== Step 7b: 内侧黑丝 / 细发丝噪点再清理（2 次 3×3 中值式清理）=====
        for (let _pass = 0; _pass < 2; _pass++) {
          const fc2 = new Uint8ClampedArray(buf);
          for (let y = 1; y < ch - 1; y++) {
            for (let x = 1; x < cw - 1; x++) {
              const idx = (y * cw + x) * 4;
              const a = fc2[idx + 3];
              if (a === 0 || a > 200) continue;
              let aNei = 0, nNei = 0;
              for (let dy = -1; dy <= 1; dy++) {
                for (let dx = -1; dx <= 1; dx++) {
                  if (!dx && !dy) continue;
                  const ni = ((y+dy)*cw + (x+dx));
                  if (fc2[ni * 4 + 3] > 0) { aNei += fc2[ni * 4 + 3]; nNei++; }
                }
              }
              if (nNei >= 4) {
                const avg = aNei / nNei;
                if (a < avg * 0.45 && a < 100) {
                  // 被更亮的邻居包围的暗点 → 平滑一下（去除小毛刺/噪点）
                  buf[idx+3] = Math.min(255, Math.round(a*0.40 + avg*0.60));
                }
              }
            }
          }
        }
        // ===== Step 8: 裁空边（pad 稍加大） =====
        ctx.putImageData(imgData, 0, 0);
        let minX = cw, maxX = -1, minY = ch, maxY = -1;
        for (let y = 0; y < ch; y++) {
          for (let x = 0; x < cw; x++) {
            if (buf[(y * cw + x) * 4 + 3] > 0) {
              if (x < minX) minX = x;
              if (x > maxX) maxX = x;
              if (y < minY) minY = y;
              if (y > maxY) maxY = y;
            }
          }
        }
        let finalCvs = cvs;
        if (maxX >= 0 && (minX > 1 || maxX < cw - 2 || minY > 1 || maxY < ch - 2)) {
          const pad = 6;
          const cx0 = Math.max(0, minX - pad);
          const cy0 = Math.max(0, minY - pad);
          const cx1 = Math.min(cw, maxX + pad + 1);
          const cy1 = Math.min(ch, maxY + pad + 1);
          const nw = cx1 - cx0, nh = cy1 - cy0;
          if (nw > 6 && nh > 6 && (nw < cw - 4 || nh < ch - 4)) {
            const cv2 = document.createElement('canvas');
            cv2.width = nw; cv2.height = nh;
            const c2 = cv2.getContext('2d');
            c2.clearRect(0, 0, nw, nh);
            c2.putImageData(ctx.getImageData(cx0, cy0, nw, nh), 0, 0);
            finalCvs = cv2;
          }
        }
        try { resolve(finalCvs.toDataURL('image/png')); }
        catch (e) { try { resolve(cvs.toDataURL('image/png')); } catch (e2) { resolve(''); } }
      } catch (err) {
        try { resolve(cvs.toDataURL('image/png')); } catch (e3) { resolve(''); }
      }
    });
  }

  function cutoutWhiteBackground(imgEl, maxDim) {
    return new Promise(function(resolve) {
      try {
        const w = imgEl.naturalWidth || imgEl.width;
        const h = imgEl.naturalHeight || imgEl.height;
        if (!w || !h) return resolve(imgEl.src || '');
        const maxSide = maxDim || 640;
        let cw = w, ch = h;
        if (w > h && w > maxSide) { cw = maxSide; ch = Math.round(h * maxSide / w); }
        else if (h > maxSide) { ch = maxSide; cw = Math.round(w * maxSide / h); }
        const cvs = document.createElement('canvas');
        cvs.width = cw; cvs.height = ch;
        const ctx = cvs.getContext('2d', { willReadFrequently: true });
        if (!ctx) return resolve(imgEl.src || '');
        ctx.clearRect(0, 0, cw, ch);
        ctx.drawImage(imgEl, 0, 0, cw, ch);
        cutoutWhiteBackgroundCVS(cvs, ctx).then(resolve).catch(function() { resolve(imgEl.src || ''); });
      } catch (e) { resolve(imgEl.src || ''); }
    });
  }

  function renderCharCrowd() {
    const wrap = document.getElementById('charCrowd');
    if (!wrap || !CONFIG.CHAR_CROWD || CONFIG.CHAR_CROWD.length === 0) return;

    // ========== 0. wrap 自身坐标 ==========
    let wrapRectTop = 0;
    let wrapRectLeft = 0;
    let wrapRectW = 1000;
    try {
      const wr = wrap.getBoundingClientRect();
      wrapRectTop  = wr.top;
      wrapRectLeft = wr.left;
      // 【修复】某些浏览器下 #charCrowd 初始 width=0，fallback 用 VW
      const rawW = wr.width || 0;
      wrapRectW = (rawW > 80) ? rawW : (document.documentElement.clientWidth || window.innerWidth || 1000);
    } catch(e) {
      wrapRectW = (document.documentElement.clientWidth || window.innerWidth || 1000);
    }

    // ========== 1. 视窗尺寸 ==========
    const VW = Math.max(320, Math.min(3200, window.innerWidth  || document.documentElement.clientWidth  || 1000));
    const VH = Math.max(480, Math.min(2400, window.innerHeight || document.documentElement.clientHeight || 700));
    // 最终用于居中对齐的 wrapInnerW：以 wrapRectW 为主，VW 兜底
    const EFF_W = Math.max(wrapRectW, Math.min(VW * 0.98, wrapRectW));

    // ========== 2. 四排×9 = 36 人（用户要求：36张完整合成卡全部显示，一个都不能少） ==========
    //   9 + 9 + 9 + 9 = 36，四排交替微错位，视觉上不挤在中间
    const KEEP = 36;
    const ROWS = [
      { N: 9, rowIdx: 0, par: 'odd'  },   // 后排（9人）
      { N: 9, rowIdx: 1, par: 'even' },   // 中后（9人）
      { N: 9, rowIdx: 2, par: 'odd'  },   // 中前（9人）
      { N: 9, rowIdx: 3, par: 'even' }    // 前排（9人）
    ];

    // ========== 3. BASE_W：36人要放得下，整体比 20 人再紧凑一档 ==========
    const MAX_PER_ROW = 9;
    // 【修复 · 放大】用 EFF_W 且去掉 1900px 上限，让宽屏人物放得更大
    const wrapInnerW = Math.min(EFF_W * 0.995, 3600);

    // 人物最小尺寸分档：36 人四排，整体再紧凑一档（保证 9 人一排放得下）
    //  手机小屏(<520)     →  86px（保证9人不溢出横向）
    //  手机大屏(<820)     → 108px
    //  平板/小笔记本(<1024)→ 140px
    //  电脑 (≥1024)      → 170px  （桌面1080p清晰可见）
    //  大宽屏(≥1440)     → 196px
    let BASE_W_MIN;
    if      (VW < 520)  BASE_W_MIN = 86;
    else if (VW < 820)  BASE_W_MIN = 108;
    else if (VW < 1024) BASE_W_MIN = 140;
    else if (VW < 1440) BASE_W_MIN = 170;
    else                BASE_W_MIN = 196;

    // 人物最大封顶：屏幕短边的 22%（4 排 × 2.2 ≈ 97%，留出顶部按钮区）
    const BASE_W_CAP_BY_SCREEN = Math.max(
      BASE_W_MIN + 20,
      Math.round(Math.min(VH, VW) * 0.220)
    );

    // 先算「紧密排列不超出视窗」的 BASE_W（用紧凑步距 1.00，脚步紧挨）
    let BASE_W_byViewport_tight = Math.floor(wrapInnerW / (MAX_PER_ROW * 1.005));
    // 紧密 BASE_W 与最小尺寸比大小：若紧密 < min，则说明屏幕窄，接受轻微肩并肩重叠
    let BASE_W;
    if (BASE_W_byViewport_tight >= BASE_W_MIN) {
      // 宽松模式：有富余
      const BASE_W_MAX_BY_VW = Math.round(wrapInnerW / (MAX_PER_ROW * 1.040));
      BASE_W = Math.round(wrapInnerW / (MAX_PER_ROW * 1.020));
      const BASE_W_MAX = Math.max(BASE_W_MIN + 8, Math.min(BASE_W_MAX_BY_VW, BASE_W_CAP_BY_SCREEN));
      BASE_W = Math.max(BASE_W_MIN, Math.min(BASE_W_MAX, BASE_W));
    } else {
      BASE_W = BASE_W_MIN;
    }

    // STEP_H：横向间距，保证 9 个人一排放得下且视觉饱满
    const IDEAL_STEP = (wrapInnerW - BASE_W * 1.00) / (MAX_PER_ROW - 1);
    let targetStep = IDEAL_STEP * 0.94;
    targetStep = Math.max(BASE_W * 0.86, targetStep);
    const STEP_H = targetStep;

    // 四排纵向间距：1.95 倍角色宽，每排之间缝隙约 15-25px
    const ROW_STEP_V = BASE_W * 1.95;
    // 按钮底部 → 第一排脚底，1.50 倍宽（留出人群顶部按钮的安全距离）
    const ROW0_FOOT_Y_rel = BASE_W * 1.50;
    // 【修复】用 EFF_W 的一半，避免 wrapRectW=0 时所有人物堆到最左
    const rowCenterX_rel = EFF_W / 2;

    // ========== 4. 取前 36 个角色分配到四排 ==========
    const chars = CONFIG.CHAR_CROWD.slice(0, KEEP);
    const rowChars = [];
    let rowPtr = 0;
    for (let r = 0; r < ROWS.length; r++) {
      rowChars.push(chars.slice(rowPtr, rowPtr + ROWS[r].N));
      rowPtr += ROWS[r].N;
    }

    let html = '';
    let globalIdx = 0;
    let maxFootY_rel = 0;
    // 后排 z-index 小，前排大（4 排）
    const zBasePerRow = [2, 3, 4, 5];

    // ============================================================
    // B2【用户要求】：每张卡片 = 一张「完整合成卡」，背景贴近角色 + 人物贴背景
    //   · 4 层结构：天空渐变色带 → 中层场景云/雾/山 → 地平线装饰 → 地面阴影
    //   · 按 charTag 匹配「游戏/番剧真实场景色」+ 专属点缀（樱花/枫叶/星粒/鸟居色）
    //   · 36 人台词保留 CHAR_QUOTES 原话（每个角色的特色话语要一模一样）
    // ============================================================
    function makePerPersonBg(idx, tag){
      tag = tag || 'oc';
      // 每 tag 一组色：[天空顶色, 天空中色(地平线), 地面色, 点缀装饰色(樱花/星/云)]
      var palette = {
        skyA: '#D9E8FF', skyB: '#9FB8E8',   // 天空上/下
        ground: 'rgba(15,23,42,0.14)',       // 地面阴影
        dust:   'rgba(255,255,255,0.55)',    // 点缀层：云/雾/樱花
        accent: 'rgba(255,255,255,0.9)'      // 点缀 accent 粒子
      };
      // 按作品/角色：定色（贴近角色，不是纯乱数渐变）
      switch(tag) {
        case 'gi-mondstadt':
          palette = { skyA:'#D4ECFF', skyB:'#87C5E8', ground:'rgba(80,130,90,0.18)', dust:'rgba(255,255,255,0.75)', accent:'#FFFFFF' };
          break;  // 蒙德：风车+蓝天+绿地（浅蓝→水蓝+淡绿草地）
        case 'gi-inazuma':
          palette = { skyA:'#FFE0F3', skyB:'#C58CC7', ground:'rgba(150,60,90,0.18)', dust:'rgba(255,182,213,0.85)', accent:'#FFB7D5' };
          break;  // 稻妻：鸣神樱花粉→紫+朱红鸟居底+樱花瓣粉
        case 'gi-liyue':
          palette = { skyA:'#FFEBC7', skyB:'#D9AB6F', ground:'rgba(130,80,40,0.20)', dust:'rgba(255,235,200,0.65)', accent:'#FFE0A8' };
          break;  // 璃月：云海暖金→土褐+璃月港橙
        case 'gi-sumeru':
          palette = { skyA:'#DCF5B8', skyB:'#B98944', ground:'rgba(120,90,40,0.18)', dust:'rgba(220,245,200,0.55)', accent:'#DFFFB0' };
          break;  // 须弥：雨林绿→沙漠金+教令院拱门黄
        case 'sf':
          palette = { skyA:'#FFF3C2', skyB:'#C7D999', ground:'rgba(90,110,60,0.16)', dust:'rgba(255,250,220,0.60)', accent:'#FFF2B0' };
          break;  // 芙莉莲：花海夕阳→草原绿+魔法公会长尖塔淡光
        case 're0':
          palette = { skyA:'#C4D4FF', skyB:'#7C86BE', ground:'rgba(40,50,100,0.20)', dust:'rgba(200,215,255,0.55)', accent:'#C0D0FF' };
          break;  // Re0：宅邸月下蓝→魔法阵紫+月白
        case 'konosuba':
          palette = { skyA:'#FFE690', skyB:'#70BD73', ground:'rgba(60,110,70,0.20)', dust:'rgba(255,235,160,0.55)', accent:'#FFD76A' };
          break;  // 素晴：爆炸草原黄昏金→草绿+爆炸橙火
        case 'jjk':
          palette = { skyA:'#162036', skyB:'#5E20B0', ground:'rgba(124,58,237,0.28)', dust:'rgba(167,139,250,0.28)', accent:'#A78BFA' };
          break;  // 咒术：深夜黑→紫电领域展开方格+咒纹紫
        case 'spyfamily':
          palette = { skyA:'#FFD3BB', skyB:'#8693B0', ground:'rgba(50,60,90,0.22)', dust:'rgba(255,205,170,0.55)', accent:'#FFBC9A' };
          break;  // 间谍家：东京塔夕橙→谍战深夜灰蓝
        case 'naruto':
          palette = { skyA:'#9ED7FF', skyB:'#325D80', ground:'rgba(40,80,120,0.22)', dust:'rgba(180,220,255,0.55)', accent:'#FBBF24' };
          break;  // 火影：木叶蓝→终结谷深青+火影岩橙
        case 'oc-samurai':
          palette = { skyA:'#F2D1D1', skyB:'#883C48', ground:'rgba(100,30,45,0.22)', dust:'rgba(255,180,190,0.65)', accent:'#FFB8C3' };
          break;  // 原创武士：樱落月夜淡粉→朱红刀鞘+樱粉
        case 'oc-skate':
          palette = { skyA:'#2A2D44', skyB:'#D21F3C', ground:'rgba(30,30,50,0.35)', dust:'rgba(239,68,68,0.22)', accent:'#EF4444' };
          break;  // 滑板：深夜赛博黑→霓虹红
        case 'oc-crystal':
          palette = { skyA:'#E7D3FF', skyB:'#7A59BE', ground:'rgba(90,70,150,0.22)', dust:'rgba(216,180,254,0.55)', accent:'#C4B5FD' };
          break;  // 水晶：紫水晶帐→星盘银紫
        case 'oc-maid':
          palette = { skyA:'#FFEBEE', skyB:'#C37687', ground:'rgba(120,60,80,0.18)', dust:'rgba(255,230,235,0.70)', accent:'#FFCDD6' };
          break;  // 女仆：洋馆粉白→红茶朱古力
        case 'oc-miko':
          palette = { skyA:'#FFDCD2', skyB:'#BE402F', ground:'rgba(130,40,30,0.22)', dust:'rgba(255,200,190,0.65)', accent:'#FFB4A2' };
          break;  // 巫女：神社樱粉→鸟居朱红
        case 'oc-cyber':
          palette = { skyA:'#0C1024', skyB:'#1DB5CE', ground:'rgba(12,25,60,0.30)', dust:'rgba(34,211,238,0.22)', accent:'#22D3EE' };
          break;  // 骇客：数据矩阵黑→赛博霓虹青
        case 'oc-knight':
          palette = { skyA:'#E1E6EC', skyB:'#656F85', ground:'rgba(70,80,100,0.22)', dust:'rgba(226,232,240,0.55)', accent:'#CBD5E1' };
          break;  // 骑士：城堡石米白→王旗深蓝
        case 'oc-neko':
          palette = { skyA:'#FFECF2', skyB:'#EE92B3', ground:'rgba(160,80,110,0.18)', dust:'rgba(255,220,235,0.70)', accent:'#FFC2D9' };
          break;  // 猫娘：奶油蛋糕粉→草莓淡粉
        case 'oc-ninja':
          palette = { skyA:'#172030', skyB:'#8891A0', ground:'rgba(40,45,55,0.30)', dust:'rgba(156,163,175,0.28)', accent:'#9CA3AF' };
          break;  // 忍者：月影夜黑→风铃银灰
        default:
          // 其他 oc 系：按 idx 柔和定色（贴近角色，不突兀）
          var base = (idx * 47) % 360;
          palette = {
            skyA:   'hsl('+base+',55%25,84%25)',
            skyB:   'hsl('+((base+35)%360)+',50%25,64%25)',
            ground: 'rgba(15,23,42,0.14)',
            dust:   'rgba(255,255,255,0.45)',
            accent: 'hsl('+base+',65%25,88%25)'
          };
      }
      // ========== 拼一张 4 层真实场景背景 SVG ==========
      // 层1 天空（顶→地渐变）；层2 中景云/雾/光斑；层3 地平线深色；层4 地面阴影 + 粒子
      var P = palette;
      var seed = (idx * 9301 + 49297) % 233280;
      var rnd = function(n){ seed = (seed * 9301 + 49297) % 233280; return (seed / 233280) * (n||1); };
      // 粒子点缀（每人生成 14~20 颗，贴近角色主题色）
      var dots = '';
      var N = 14 + Math.floor(rnd(7));
      for (var i = 0; i < N; i++) {
        var x = Math.round(rnd(400));
        var y = Math.round(rnd(460)); // 只在天空和中景撒，不盖脸
        var s = Math.max(1, Math.round(rnd(4)));
        dots += '%3Ccircle cx=%22'+x+'%22 cy=%22'+y+'%22 r=%22'+s+'%22 fill=%22'+P.accent+'%22 opacity=%22'+(0.42+rnd(0.42)).toFixed(2)+'%22/%3E';
      }
      // 中景：一朵柔和的柔光雾团（2~3 个椭圆渐变叠加），增强景深感
      var midR = 90 + Math.round(rnd(50));
      var midX = 120 + Math.round(rnd(180));
      var midY = 280 + Math.round(rnd(110));
      var cloud =
        '%3Cellipse cx=%22'+midX+'%22 cy=%22'+midY+'%22 rx=%22'+midR+'%22 ry=%22'+Math.round(midR*0.62)+'%22 fill=%22'+P.dust+'%22/%3E' +
        '%3Cellipse cx=%22'+Math.max(10, Math.min(390,midX+80))+'%22 cy=%22'+Math.min(500,midY+30)+'%22 rx=%22'+Math.round(midR*0.60)+'%22 ry=%22'+Math.round(midR*0.38)+'%22 fill=%22'+P.dust+'%22 opacity=%220.55/%3E';
      return 'data:image/svg+xml;charset=utf-8,' +
        '%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 400 608%22 preserveAspectRatio=%22xMidYMid slice%22%3E' +
        '%3Cdefs%3E' +
          '%3ClinearGradient id=%22sky%22 x1=%220%22 y1=%220%22 x2=%220%22 y2=%221%22%3E' +
            '%3Cstop offset=%220%25%22 stop-color=%22'+P.skyA+'%22/%3E' +
            '%3Cstop offset=%2255%25%22 stop-color=%22'+P.skyB+'%22/%3E' +
            '%3Cstop offset=%2278%25%22 stop-color=%22'+P.skyB+'%22/%3E' +
            '%3Cstop offset=%22100%25%22 stop-color=%22rgba(15,23,42,0.22)%22/%3E' +
          '%3C/linearGradient%3E' +
        '%3C/defs%3E' +
        // 第1层：天空底
        '%3Crect width=%22400%22 height=%22608%22 fill=%22url(%23sky)%22/%3E' +
        // 第2层：中景云雾/光斑柔光
        cloud +
        // 第3层：地平线装饰带（深色薄条，营造地平线）
        '%3Crect y=%22470%22 width=%22400%22 height=%2224%22 fill=%22rgba(15,23,42,0.10)%22/%3E' +
        // 第4层：地面阴影（让人物双脚站得更"实"，不漂）
        '%3Crect y=%22494%22 width=%22400%22 height=%22114%22 fill=%22'+P.ground+'%22/%3E' +
        // 第5层：点缀粒子（樱花瓣/星尘/光斑/火花，主题色 accent）
        dots +
        '%3C/svg%3E';
    }
    function pushItem(c, cx, cy, rot, sizeMul, zBase) {
      const wFactor = Math.max(0.85, Math.min(1.22, (c.w || 1)));
      const realW = Math.max(74, Math.round(BASE_W * sizeMul * wFactor));
      const realH = Math.round(realW * 1.52);
      const top  = Math.round(cy - realH);
      const left = Math.round(cx - realW / 2);
      const r = (c.rotate != null) ? c.rotate : (Math.round(rot * 10) / 10);
      if (cy > maxFootY_rel) maxFootY_rel = cy;
      const charTag = (CHAR_TAGS && CHAR_TAGS[globalIdx]) ? CHAR_TAGS[globalIdx] : 'oc';
      // B2【用户要求】：每人统一一张独立背景（按角色场景定色）+ 每人统一一张台词（CHAR_QUOTES 里定好的角色特色原话）
      const perPersonBg = makePerPersonBg(globalIdx, charTag);
      const roleQuote = (CHAR_QUOTES && CHAR_QUOTES[globalIdx]) ? CHAR_QUOTES[globalIdx] : (c.quote || '');
      let style =
        'left:' + left + 'px;' +
        'top:'  + top + 'px;' +
        '--w:'  + realW + 'px;' +
        '--r:'  + r + 'deg;' +
        (c.delay ? ('animation-delay:' + c.delay + 'ms;') : '') +
        'z-index:' + (zBase | 0) + ';' +
        // B2：每人独立的作品场景背景（不是共享 ::before，不是乱数 HSL，而是按角色场景色）
        'background-image:url(\'' + perPersonBg + '\');' +
        'background-size:cover;background-position:center center;background-repeat:no-repeat;';
      const qSafe = roleQuote.replace(/"/g, '&quot;');
      html +=
        '<div class="crowd-item" data-fullbg="1" data-tag-bg="'+charTag+'" data-idx="' + globalIdx + '" data-ch="' + charTag + '" data-row="' + (c.__rowIdx|0) + '" style="' + style + '">' +
          // B2：img 是一张完整人物图，贴底贴边站在自己的场景背景上
          '<img src="" alt="" loading="lazy" draggable="false" data-quote="' + qSafe + '" style="object-fit:contain;object-position:50% 95%;width:100%;height:100%;display:block;" onerror="this.style.visibility=\'hidden\';">' +
          // B2：台词气泡用 CHAR_QUOTES 固定的角色特色原话（用户要"每个特色的话语要一模一样"）
          '<div class="crowd-speech">' +
            '<div class="crowd-speech-arrow"></div>' +
            '<button class="crowd-speech-close" aria-label="关闭">&times;</button>' +
            '<p>' + roleQuote + '</p>' +
          '</div>' +
        '</div>';
      globalIdx++;
    }

    // ========== 5. 逐排渲染：近乎直排，偶排比奇排整体错位半格（更自然）==========
    for (let r = 0; r < ROWS.length; r++) {
      const N = ROWS[r].N;
      const par = ROWS[r].par;
      const totalRowW = (N - 1) * STEP_H;
      let rowStartX = rowCenterX_rel - totalRowW / 2;
      // 偶排比奇排整体错开半步（避免所有人物在同一条竖线上）
      if (par === 'even') rowStartX += STEP_H * 0.50;
      const footYBase = ROW0_FOOT_Y_rel + r * ROW_STEP_V;

      // 【修复 · 微错落 v2】把「高低差」控制在 ±10px 内，避免挤重叠
      const yJitterScale = BASE_W * (0.040 + r * 0.010);

      for (let i = 0; i < N; i++) {
        const c = rowChars[r][i];
        if (!c) continue;
        c.__rowIdx = r;

        let cx = rowStartX + i * STEP_H;
        const mid = (N - 1) / 2;
        const edgeT = (i - mid) / Math.max(1, mid);
        // 两端略向外扩一点点，疏朗好看
        cx += edgeT * (BASE_W * (0.020 + r * 0.014));

        // 错落（大幅）
        const jitterSeed = ((i * 131 + r * 17) % 29) / 29 - 0.5;
        const cy = footYBase + jitterSeed * yJitterScale * 2;

        // 近乎直立（± 0.4 度以内，几乎不歪）
        const rotBase = -edgeT * (0.22 + r * 0.06);
        const rotJit = (((i * 53 + r * 29) % 17) / 17 - 0.5) * 0.18;
        const rot = rotBase + rotJit;

        // 前排略大（±3.5%），尺寸差异极小（±5%），视觉整齐
        const rowSize = 1.0 - (ROWS.length - 1 - r) * 0.035;
        const sizeJit = 0.975 + (((i * 37 + r * 11) % 23) / 23) * 0.07;
        const sizeMul = rowSize * sizeJit;

        pushItem(c, cx, cy, rot, sizeMul, zBasePerRow[r] + (i & 1));
      }
    }

    // 容器高度 = 最后一排脚底 + 宽松底部留白
    const minHeight = Math.max(680, Math.round(maxFootY_rel + BASE_W * 0.92));
    wrap.style.minHeight = minHeight + 'px';
    wrap.style.height    = minHeight + 'px';

    wrap.innerHTML = html;

    const SHEETS = CONFIG.CHAR_CROWD_SHEETS || [];
    const sheetImgCache = [];
    function getSheet(sheetIdx) {
      if (sheetImgCache[sheetIdx]) return Promise.resolve(sheetImgCache[sheetIdx]);
      if (!SHEETS[sheetIdx]) return Promise.reject(new Error('sheet missing'));
      return loadSheetImage(SHEETS[sheetIdx].file).then(function(img) {
        sheetImgCache[sheetIdx] = img;
        return img;
      });
    }
    const items = wrap.querySelectorAll('.crowd-item');
    let ptr = 0;
    function runNext() {
      if (ptr >= items.length) return;
      const item = items[ptr++];
      const k = parseInt(item.getAttribute('data-idx'), 10) | 0;
      const c = CONFIG.CHAR_CROWD[k];
      const imgEl = item.querySelector('img');
      if (!c || !imgEl) { return setTimeout(runNext, 0); }
      const sheetDef = SHEETS[c.sheetIdx | 0];
      if (!sheetDef) { return setTimeout(runNext, 0); }
      getSheet(c.sheetIdx | 0)
        .then(function(sheetImg) {
          return cutoutCellFromSheet(sheetImg, c.row | 0, c.col | 0, sheetDef.rows | 3, sheetDef.cols | 3, 560);
        })
        .then(function(dataUrl) {
          if (dataUrl) {
            imgEl.style.visibility = 'hidden';
            imgEl.onload = function() { imgEl.style.visibility = 'visible'; imgEl.onload = null; };
            imgEl.onerror = function() { imgEl.style.visibility = 'hidden'; imgEl.onerror = null; };
            imgEl.src = dataUrl;
            imgEl.dataset.cutDone = '1';
          } else {
            imgEl.style.visibility = 'hidden';
            imgEl.dataset.cutDone = '1';
          }
          setTimeout(runNext, 0);
        })
        .catch(function() { imgEl.dataset.cutDone = '1'; setTimeout(runNext, 0); });
    }
    setTimeout(runNext, 0);
    setTimeout(runNext, 40);

    // 辅助：关闭某个speech气泡，并恢复其所属item的z-index
    function closeOneSpeech(speechEl) {
      speechEl.classList.remove('on');
      const ownerItem = speechEl.closest('.crowd-item');
      if (ownerItem) {
        ownerItem.style.zIndex = '';
      }
    }
    items.forEach(function(item) {
      const speech = item.querySelector('.crowd-speech');
      const closeBtn = item.querySelector('.crowd-speech-close');
      item.addEventListener('click', function(e) {
        e.stopPropagation();
        if (closeBtn && e.target === closeBtn) { closeOneSpeech(speech); return; }
        // 关闭其他所有气泡，并恢复对应的item z-index
        wrap.querySelectorAll('.crowd-speech.on').forEach(function(s) {
          if (s !== speech) closeOneSpeech(s);
        });
        speech.classList.remove('on');
        void speech.offsetWidth;
        // 【关键修复】：提升当前 crowd-item 的 z-index 到最上层，
        // 因为 item 有 transform 会创建独立堆叠上下文，必须提升 item 本身，
        // speech 的 z-index:9999 才能突破到其他兄弟 item 之上
        item.style.zIndex = '9998';
        speech.classList.add('on');
      });
    });
    document.addEventListener('click', function() {
      wrap.querySelectorAll('.crowd-speech.on').forEach(function(s) { closeOneSpeech(s); });
    });
  }

  // resize 时重新按新宽度渲染（保证手机转屏时也不堆叠）
  window.addEventListener('resize', function() {
    let t;
    clearTimeout(window.__crowdResizeTimer);
    window.__crowdResizeTimer = setTimeout(function() {
      const wrap = document.getElementById('charCrowd');
      if (wrap) renderCharCrowd();
    }, 160);
  });

  document.addEventListener('DOMContentLoaded', init);

  // =========================================================
  // 公共返图墙（大家的返图）逻辑
  // =========================================================
  const pwState = {
    inited: false,
    loading: false,
    loaded: false,          // 全量是否加载完（剩余=0）
    allPhotos: [],          // 全部（id倒序），用于过滤
    visible: [],            // 当前显示 id 列表，用于判断新增
    maxId: 0,
    filter: 'all',          // all / 1 / 2 / 3
    pageSize: 30,
    shownCount: 0,
    pollTimer: null,
  };

  function initPublicWall() {
    if (pwState.inited) {
      renderPublicWall({ silent: true });
      return;
    }
    pwState.inited = true;

    // 筛选按钮
    const filterRow = $('#pwFilterRow');
    if (filterRow) {
      filterRow.addEventListener('click', (e) => {
        const btn = e.target.closest('.pw-filter-btn');
        if (!btn) return;
        const f = btn.dataset.filter;
        if (!f || f === pwState.filter) return;
        pwState.filter = f;
        $$('.pw-filter-btn').forEach(b => b.classList.toggle('active', b === btn));
        renderPublicWall({ resetScroll: true });
      });
    }

    // 加载更多
    const btnMore = $('#pwBtnLoadMore');
    if (btnMore) {
      btnMore.addEventListener('click', () => loadMorePublicWall());
    }

    // Lightbox 关闭
    const lb = $('#pwLightbox');
    if (lb) {
      lb.addEventListener('click', (e) => {
        if (e.target.matches('[data-pw-close]')) closeLightbox();
      });
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && lb.classList.contains('open')) closeLightbox();
      });
    }

    // 卡片点击：事件委托
    const waterfall = $('#pwWaterfall');
    if (waterfall) {
      waterfall.addEventListener('click', (e) => {
        const card = e.target.closest('.pw-card');
        if (!card) return;
        const id = parseInt(card.dataset.id, 10);
        if (!id) return;
        const photo = pwState.allPhotos.find(p => p.id === id);
        if (photo) openLightbox(photo);
      });
    }

    fetchPublicWall({ initial: true })
      .then(data => {
        if (!data) return null;
        pwState.allPhotos = data.photos.slice();
        pwState.maxId = data.photos.reduce((m, p) => Math.max(m, p.id), 0);
        pwState.visible = data.photos.map(p => p.id);
        pwState.shownCount = data.photos.length;
        pwState.loaded = data.photos.length >= data.total;
        updatePwHeader(data.total, data.photos[0]);
        return data;
      })
      .then(() => renderPublicWall({ resetScroll: true }));
  }

  function fetchPublicWall(opt = {}) {
    if (pwState.loading) return Promise.resolve(null);
    pwState.loading = true;
    const since = opt.since_id || 0;
    const limit = opt.initial ? pwState.pageSize : 50;
    const url = `/api/lottery/photos/public?limit=${limit}${since ? '&since_id=' + since : ''}`;
    return fetch(url)
      .then(r => r.json())
      .then(data => {
        if (!data || !data.success) return null;
        return data;
      })
      .catch(() => null)
      .finally(() => { pwState.loading = false; });
  }

  function applyPublicWallFilter(list) {
    if (pwState.filter === 'all') return list.slice();
    const lv = parseInt(pwState.filter, 10);
    return list.filter(p => (p.prizeLevel || 0) === lv);
  }

  function fetchAndApplyInitial() {
    return fetchPublicWall({ initial: true }).then(data => {
      if (!data) return;
      pwState.allPhotos = data.photos.slice();
      pwState.maxId = data.photos.reduce((m, p) => Math.max(m, p.id), pwState.maxId);
      pwState.visible = data.photos.map(p => p.id);
      pwState.shownCount = data.photos.length;
      pwState.loaded = data.photos.length >= data.total;
      updatePwHeader(data.total, data.photos[0]);
    });
  }

  function updatePwHeader(total, latest) {
    const el = $('#pwTotalCount');
    if (el) el.textContent = total;
    const elT = $('#pwLatestTime');
    if (elT) elT.textContent = latest && latest.timeStr ? latest.timeStr.slice(5, 16) : '—';
  }

  function renderPublicWall(opt = {}) {
    const waterfall = $('#pwWaterfall');
    const empty = $('#pwEmpty');
    const loadMore = $('#pwLoadMore');
    if (!waterfall) return;

    const filtered = applyPublicWallFilter(pwState.allPhotos);
    // 分页显示：只取 shownCount（按 filter 后的 slice）
    const toShow = filtered.slice(0, pwState.shownCount || pwState.pageSize);
    pwState.shownCount = toShow.length;

    waterfall.innerHTML = '';
    if (filtered.length === 0) {
      if (empty) empty.style.display = 'flex';
      if (loadMore) loadMore.style.display = 'none';
      return;
    }
    if (empty) empty.style.display = 'none';

    const frag = document.createDocumentFragment();
    toShow.forEach((p, idx) => {
      frag.appendChild(buildPwCard(p, false));
    });
    waterfall.appendChild(frag);

    // 加载更多按钮
    const rest = filtered.length - toShow.length;
    if (loadMore) {
      if (rest > 0) {
        loadMore.style.display = 'block';
        const btn = $('#pwBtnLoadMore');
        if (btn) {
          btn.textContent = `加载更多（剩余 ${rest}） ↓`;
          btn.disabled = false;
        }
      } else {
        loadMore.style.display = 'none';
      }
    }

    if (opt.resetScroll) {
      const pageEl = $('#page-publicwall');
      if (pageEl) pageEl.scrollTop = 0;
    }
  }

  function loadMorePublicWall() {
    if (pwState.loaded) return;
    const filtered = applyPublicWallFilter(pwState.allPhotos);
    const rest = filtered.length - pwState.shownCount;
    if (rest <= 0) {
      pwState.loaded = true;
      renderPublicWall();
      return;
    }
    const addCount = Math.min(pwState.pageSize, rest);
    pwState.shownCount += addCount;
    if (pwState.shownCount >= filtered.length) pwState.loaded = true;
    renderPublicWall();
  }

  function startPublicWallPolling() {
    stopPublicWallPolling();
    // 首次没初始化完则先拉
    if (!pwState.inited) return;
    if (pwState.allPhotos.length === 0) {
      fetchAndApplyInitial().then(() => renderPublicWall({ resetScroll: true }));
    }
    pwState.pollTimer = setInterval(() => {
      if (!pwState.maxId) return;
      fetchPublicWall({ since_id: pwState.maxId }).then(data => {
        if (!data || !data.photos || data.photos.length === 0) return;
        // 增量 prepend
        const newOnes = data.photos.slice().sort((a, b) => b.id - a.id);
        const existSet = new Set(pwState.allPhotos.map(p => p.id));
        const add = newOnes.filter(p => !existSet.has(p.id));
        if (add.length === 0) return;
        pwState.allPhotos = add.concat(pwState.allPhotos);
        add.forEach(p => { if (p.id > pwState.maxId) pwState.maxId = p.id; });
        // 顶部显示：按当前 filter
        const isAll = pwState.filter === 'all';
        const visibleAdd = isAll ? add : add.filter(p => (p.prizeLevel || 0) === parseInt(pwState.filter, 10));
        if (visibleAdd.length > 0) {
          prependNewCards(visibleAdd);
          // 调整 shownCount 与 header
          pwState.shownCount += visibleAdd.length;
        }
        updatePwHeader(pwState.allPhotos.length, pwState.allPhotos[0]);
      });
    }, 15000);
  }

  function stopPublicWallPolling() {
    if (pwState.pollTimer) {
      clearInterval(pwState.pollTimer);
      pwState.pollTimer = null;
    }
  }

  function prependNewCards(list) {
    const waterfall = $('#pwWaterfall');
    if (!waterfall || list.length === 0) return;
    const frag = document.createDocumentFragment();
    list.forEach((p, idx) => frag.appendChild(buildPwCard(p, true)));
    // 先插入，然后移除 is-new（3s后）
    const first = waterfall.firstChild;
    if (first) waterfall.insertBefore(frag, first);
    else waterfall.appendChild(frag);
    setTimeout(() => {
      list.forEach(p => {
        const el = waterfall.querySelector(`.pw-card[data-id="${p.id}"]`);
        if (el) el.classList.remove('is-new');
      });
    }, 3200);
  }

  function buildPwCard(p, isNew) {
    const div = document.createElement('div');
    div.className = 'pw-card' + (isNew ? ' is-new' : '');
    div.dataset.id = p.id;
    const lv = p.prizeLevel || 0;
    const lvText = lv === 1 ? '🥇 一等奖' : lv === 2 ? '🧧 二等奖' : '参与奖';
    const shortTime = p.timeStr ? p.timeStr.slice(5, 16) : '';
    div.innerHTML =
      '<div class="pw-card-thumb-wrap">' +
        '<span class="pw-card-badge lv' + lv + '">' + lvText + '</span>' +
        '<img class="pw-card-thumb" src="' + getThumbUrl(p.photoUrl) + '" alt="照片" loading="lazy">' +
        '<div class="pw-card-shimmer"></div>' +
      '</div>' +
      '<div class="pw-card-info">' +
        '<div class="pw-card-prize">' + escapeHtml(p.prizeName || '神秘奖品') + '</div>' +
        '<div class="pw-card-meta">' +
          '<span class="pw-card-coser">🎭 ' + escapeHtml(p.cosNameMasked || '匿名') + '</span>' +
          '<span class="pw-card-time">' + shortTime + '</span>' +
        '</div>' +
      '</div>';
    const img = div.querySelector('.pw-card-thumb');
    if (img) {
      const onImg = () => img.classList.add('loaded');
      if (img.complete) onImg();
      else { img.onload = onImg; img.onerror = onImg; }
    }
    return div;
  }

  function openLightbox(p) {
    const lb = $('#pwLightbox');
    if (!lb) return;
    const lv = p.prizeLevel || 0;
    const badge = $('#pwLbBadge');
    if (badge) {
      badge.className = 'pw-lb-badge lv' + lv;
      badge.textContent = lv === 1 ? '🥇 一等奖' : lv === 2 ? '🧧 二等奖' : '参与奖';
    }
    const pri = $('#pwLbPrize'); if (pri) pri.textContent = p.prizeName || '—';
    const cos = $('#pwLbCoser'); if (cos) cos.textContent = '🎭 ' + (p.cosNameMasked || '匿名');
    const tim = $('#pwLbTime');  if (tim) tim.textContent = p.timeStr || '—';
    const img = $('#pwLightboxImg'); if (img) img.src = p.photoUrl;
    lb.classList.add('open');
    lb.setAttribute('aria-hidden', 'false');
    document.body.classList.add('lightbox-open');
  }
  function closeLightbox() {
    const lb = $('#pwLightbox');
    if (!lb) return;
    lb.classList.remove('open');
    lb.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('lightbox-open');
  }

  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, c => (
      c === '&' ? '&amp;' : c === '<' ? '&lt;' : c === '>' ? '&gt;' : c === '"' ? '&quot;' : '&#39;'
    ));
  }

  // ======================================================
  // A1 极简上传返图（两个必须点击的白框）—— 绑定逻辑
  //   白框1：点它 → 弹九宫格选位置 1-9（不再用原生 number input，避免手机弹键盘）
  //   白框2：点它 → 选图片文件
  //   必须两个白框都点过 → 确认上传才可用
  // ======================================================
  function installSimpleUploader() {
    try {
      const usWrap = document.getElementById('uploadSimpleWrap');
      const usBoxFile = document.getElementById('usBoxFile');
      const usFileValue = document.getElementById('usFileValue');
      const usPickFileInput = document.getElementById('usPickFileInput');
      const usPreview = document.getElementById('usPreview');
      const usPreviewImg = document.getElementById('usPreviewImg');
      const usPreviewRemove = document.getElementById('usPreviewRemove');
      const usSubmitBtn = document.getElementById('usSubmitBtn');
      const usTip = document.getElementById('usTip');
      const usBlocker = document.getElementById('usBlocker');
      const usBlockerMain = document.getElementById('usBlockerMain');
      const usBlockerBtn  = document.getElementById('usBlockerBtn');
      // 新版：不需要 usBoxPos / usPosModal / usPosGrid / usPosValue（用户要求删除「选择位置1-9」九宫格功能）
      if (!usWrap || !usBoxFile) return;

      const stateData = { file: null, fileUrl: null };

      // 「前置条件检查」—— 身份/抽奖未完成时：直接显示大提示卡片（不再依赖小 toast）
      function refreshBlocker() {
        if (!usBlocker) return;
        const id = getIdentity();
        let showBlocker = false;
        let mainText = '';
        let btnText = '';
        let btnGoTo = null;
        if (!id.recordId) {
          showBlocker = true;
          mainText = '请先参与一次抽奖，获得抽奖记录后才能上传你的照片哦～ 完成抽奖后会自动回到这里。';
          btnText = '去抽奖 →';
          btnGoTo = 'lottery';
        } else if (!id.cosName || !id.isVerified) {
          showBlocker = true;
          mainText = '请先填写信息登记（COS角色名），完成后才能上传你的照片。';
          btnText = '去登记信息 →';
          btnGoTo = 'verify';
        }
        if (showBlocker) {
          usBlocker.style.display = 'flex';
          if (usBlockerMain) usBlockerMain.textContent = mainText;
          if (usBlockerBtn) usBlockerBtn.textContent = btnText;
        } else {
          usBlocker.style.display = 'none';
        }
        return !showBlocker;
      }

      function refresh() {
        const ready = refreshBlocker();
        const fileOk = !!stateData.file;
        // 温馨提示卡片：身份验证后显示
        const tipsCard = document.getElementById('kindTipsCard');
        if (tipsCard) {
          tipsCard.style.display = ready ? 'block' : 'none';
        }
        // 白框选中高亮
        if (usBoxFile) usBoxFile.classList.toggle('picked', fileOk);
        if (usFileValue) {
          if (fileOk) {
            const name = stateData.file.name || '已选图片';
            const short = name.length > 12 ? name.slice(0, 8) + '…' + name.split('.').pop() : name;
            usFileValue.textContent = short;
          } else {
            usFileValue.textContent = '未选';
          }
        }
        // 预览
        if (usPreview) {
          if (fileOk && stateData.fileUrl) {
            usPreview.style.display = 'flex';
            if (usPreviewImg) usPreviewImg.src = stateData.fileUrl;
          } else {
            usPreview.style.display = 'none';
            if (usPreviewImg) usPreviewImg.removeAttribute('src');
          }
        }
        // 提交按钮：必须前置身份OK + 选了图
        const canSubmit = ready && fileOk;
        if (usSubmitBtn) usSubmitBtn.disabled = !canSubmit;
        if (usTip) {
          if (!ready) usTip.textContent = '请先完成「抽奖 + 信息登记」，才能上传你的照片';
          else if (!fileOk) usTip.textContent = '请先点上面的白色框选择要上传的图片';
          else usTip.textContent = '图片已选好，点击「确认上传」即可';
        }
      }

      // 引导按钮：去抽奖 / 去登记
      if (usBlockerBtn) {
        usBlockerBtn.addEventListener('click', () => {
          const id = getIdentity();
          if (!id.recordId) {
            // 抽奖tab
            try { switchTab('lottery'); } catch (e) {
              // 兼容：直接模拟点导航栏 lottery tab
              const nav = document.querySelector('#navbar .nav-item[data-page="lottery"]');
              if (nav) nav.click();
            }
          } else {
            // 信息登记 modal
            try { showVerifyModal && showVerifyModal(); } catch (e) {
              const sv = document.getElementById('verifyModal');
              if (sv) sv.style.display = 'flex';
            }
          }
        });
      }

      // 选文件
      if (usPickFileInput) {
        usPickFileInput.addEventListener('change', () => {
          const fl = usPickFileInput.files && usPickFileInput.files[0];
          if (!fl) {
            stateData.file = null;
            if (stateData.fileUrl) try { URL.revokeObjectURL(stateData.fileUrl); } catch (e) {}
            stateData.fileUrl = null;
            refresh();
            return;
          }
          stateData.file = fl;
          if (stateData.fileUrl) try { URL.revokeObjectURL(stateData.fileUrl); } catch (e) {}
          try { stateData.fileUrl = URL.createObjectURL(fl); } catch (e) { stateData.fileUrl = null; }
          refresh();
        });
      }

      // 移除预览
      if (usPreviewRemove) {
        usPreviewRemove.addEventListener('click', (e) => {
          e.preventDefault(); e.stopPropagation();
          stateData.file = null;
          if (stateData.fileUrl) try { URL.revokeObjectURL(stateData.fileUrl); } catch (e) {}
          stateData.fileUrl = null;
          if (usPickFileInput) usPickFileInput.value = '';
          refresh();
        });
      }

      // 提交：上传到用户本人接口 POST /api/lottery/self/<rid>/photo
      //   新版：不再附带 photoPosition（后端自动分配一个空位 1..9）
      if (usSubmitBtn) {
        usSubmitBtn.addEventListener('click', async () => {
          if (usSubmitBtn.disabled) return;
          const id = getIdentity();
          if (!id.recordId) { refresh(); return; }
          if (!id.cosName) { refresh(); return; }
          if (!stateData.file) return;

          usSubmitBtn.disabled = true;
          const oldTxt = usSubmitBtn.textContent;
          usSubmitBtn.textContent = '⏳ 上传中...';
          try {
            const fd = new FormData();
            fd.append('photo', stateData.file);
            fd.append('cosName', id.cosName);
            fd.append('wechatId', id.wechatId);
            // 不发 photoPosition → 后端 self_upload_photo 会自动找下一个空位（见 L1483-1486 app.py）

            const r = await fetch(`/api/lottery/self/${id.recordId}/photo`, { method: 'POST', body: fd });
            const d = await r.json().catch(() => null);
            if (!d || !d.success) throw new Error((d && d.message) || '上传失败');

            showToast('✅ 上传成功（自动放到第 #' + (d.photoPosition || '?') + ' 格）');

            // 状态清空
            stateData.file = null;
            if (stateData.fileUrl) try { URL.revokeObjectURL(stateData.fileUrl); } catch (e) {}
            stateData.fileUrl = null;
            if (usPickFileInput) usPickFileInput.value = '';
            refresh();

            // 刷新返图列表：上传响应中已包含完整 photos 数组，直接用它渲染九宫格
            try {
              if (d.photos && d.photos.length > 0) {
                showPhotos(d.photos, id.recordId);
              } else {
                // 兜底：响应中没有 photos，重新拉取一次
                checkPhotoStatus();
              }
            } catch (e) {
              try { checkPhotoStatus(); } catch (e2) {}
            }
          } catch (err) {
            showToast('❌ 上传失败：' + (err.message || '请稍后重试'));
          } finally {
            usSubmitBtn.disabled = false;
            usSubmitBtn.textContent = oldTxt;
            refresh();
          }
        });
      }

      // 兼容旧函数接口（避免其他地方调用报错）—— 新版本没有「占用位置」概念，后端自动分配
      window.__setSimpleUploaderTakenPositions = function () {};
      window.__toggleSimpleUploaderVisibility = function (hasPhotos) {
        if (!usWrap) return;
        usWrap.style.display = 'block';
      };
      // 暴露 refresh 给外部调用（抽奖完成/切页/checkPhotoStatus 后重新检查身份状态）
      window.__refreshSimpleUploader = refresh;

      // 首次刷新 + 1.5秒后再刷一次（等 state.verifyInfo 初始化完成）
      refresh();
      setTimeout(refresh, 800);
      setTimeout(refresh, 1600);
    } catch (e) {}
  }

  // 初始化时就请求一次（即便没切到tab，也预加载）
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => installSimpleUploader(), 50);
    setTimeout(() => {
      fetchPublicWall({ initial: true }).then(data => {
        if (!data) return;
        pwState.allPhotos = data.photos.slice();
        pwState.maxId = data.photos.reduce((m, p) => Math.max(m, p.id), 0);
        pwState.visible = data.photos.map(p => p.id);
        pwState.shownCount = data.photos.length;
        pwState.loaded = data.photos.length >= data.total;
        updatePwHeader(data.total, data.photos[0]);
      });
    }, 1500);
  });
})();
