---
name: buffett-stock-screen
description: Apply the specified five Buffett-style financial screening rules to stocks using yfinance data.
---

# 巴菲鐯五條件選股

以使用者提供的一個或多個股票代碼，逐檔計算五項條件並呈現實際數值、期間、來源和判定。

## 判斷標準
1. 近3年，每年的EPS都大於1元
2. 近12個月每股營收大於1.5元
3. 股價淨值比小於1.5
4. 近4季股東權益報酬率大於5%
5. 最近3年毛利率每年都大於10%

# 使用 yfinance-financial-data 技能來獲取個股相關資料
# 五項條件全部通過，才算通過。
# 先說明判斷結果，後續再說明每個股票在五項條件的判斷詳情
