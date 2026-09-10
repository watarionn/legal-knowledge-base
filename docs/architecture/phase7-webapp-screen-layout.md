# Phase 7-1 Web App Screen Layout

## 目的

Phase 7-1の画面は、法令AIとの「会話」を主役にせず、**質問 → 回答 → 根拠 → 原文**を最短距離で辿れることを主役にします。

初期版は1画面構成とし、画面遷移を増やしません。詳細情報はdrawer / expandable panelで段階的に開きます。

## 情報優先順位

画面上の優先順位を次の順に固定します。

1. 質問
2. 対象時点
3. 回答
4. temporal resolution status
5. 根拠条文 / Evidence
6. 原文 / provenance
7. 技術的metadata

AI回答より根拠を下位に隠しすぎないことを重要ルールとします。

## Desktop Layout

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 法令ナレッジベース                                            v1 / Phase 7 │
│ 根拠へ戻れる法令リサーチ                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ 基準日 [ 2024-04-01 ]                                                      │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ 建設業法で請負契約に関係する規定を教えて                               │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                            [ 調べる ]      │
├───────────────────────────────────────────────┬─────────────────────────────┤
│ 回答                                          │ 根拠                        │
│                                               │                             │
│ 建設業法では……                               │ Evidence 1                  │
│                                               │ 第○条 / Paragraph …         │
│ [E1] ……                                      │ 「原文抜粋……」              │
│ [E2] ……                                      │ [原文を見る]                │
│                                               │                             │
│                                               │ Evidence 2                  │
│                                               │ 第○条 …                     │
│                                               │ 「原文抜粋……」              │
│                                               │ [原文を見る]                │
├───────────────────────────────────────────────┴─────────────────────────────┤
│ 対象: 建設業法 | 基準日: 2024-04-01 | temporal: resolved | revision: …     │
└─────────────────────────────────────────────────────────────────────────────┘
```

Desktopでは回答とEvidenceを2カラムで同時表示します。

- 左: answer / claims
- 右: Evidence cards
- 下: resolved law/revision/status summary

回答内の`[E1]`等を選択すると、右側の対応Evidence cardへfocusします。

## Narrow / Mobile Layout

```text
┌──────────────────────────┐
│ 法令ナレッジベース       │
├──────────────────────────┤
│ 基準日                   │
│ [2024-04-01]             │
│                          │
│ 質問                     │
│ [......................] │
│ [ 調べる ]               │
├──────────────────────────┤
│ temporal: resolved       │
│ 建設業法 / revision …    │
├──────────────────────────┤
│ 回答                     │
│ …… [E1] ……              │
├──────────────────────────┤
│ 根拠                     │
│ E1 第○条                 │
│ 原文抜粋                 │
│ [原文を見る]             │
├──────────────────────────┤
│ E2 …                     │
└──────────────────────────┘
```

狭い画面では1カラムへ落とし、回答の直後にEvidenceを並べます。

## 初期表示

検索前は空白の回答欄を大きく見せません。

表示内容:

- アプリ名
- 説明文「法令について質問すると、回答と根拠条文を一緒に表示します。」
- 基準日
- 質問欄
- 例示質問 2〜3件

例示質問は入力補助であり、自動送信しません。

## Query Form

### 基準日

- `<input type="date">`
- 任意
- 未指定時は「現行を意図した質問」としてapplication layerへ渡すが、内部で勝手に今日の日付を法的適用日として断定しない
- requestに基準日がないことを明示的に保持する

### 質問

- textarea
- 1〜数行
- 空白のみを拒否
- 入力文字数上限をapplication layerでも検証

### 送信

- 二重送信を防止
- 処理中はbutton disabled
- 「検索中」「Evidence構築中」「回答生成中」を区別できる設計にする

Phase 7-1の最小実装では単一のloading表示でもよいが、API responseには処理時間を残せるようにします。

## Temporal Status Banner

回答より先に、対象revisionの確定状態を表示します。

### `resolved`

表示例:

```text
✓ 2024-04-01 時点の対象版を確定
建設業法 / revision: xxxxx
```

### `ambiguous`

```text
! この日付には複数のrevision候補があります。
Phase 7-1では推測して1件を選択しません。
```

回答生成は原則停止し、候補metadataを表示します。

### `unresolved`

```text
! 候補はありますが、時点境界を十分な品質で確定できません。
```

### `not-found`

```text
対象日時点のrevisionを確認できませんでした。
```

### body unavailable

```text
対象revisionは確定しましたが、本文が現在の構造DBに収録されていません。
別revisionの本文では代用しません。
```

## Answer Panel

Answer panelは次の要素だけを表示します。

- answer status
- answer text
- claimごとのEvidence marker
- answer provider metadataは通常折りたたむ

禁止:

- Evidenceなしの断定文
- confidence percentageを法的正確性の確率として表示すること
- 「正しい回答です」「法的に保証されています」等の表示

answer provider未設定時は、回答欄をエラーにせず次のように表示します。

```text
生成回答は未設定です。下の検索根拠を確認できます。
```

## Evidence Card

Evidence cardはPhase 7-1の主役となるUI部品です。

### 常時表示

- Evidence ID
- law nameまたはlaw ID
- 条文・構造label
- 原文抜粋
- revision ID短縮値
- 「原文を見る」

### 展開時表示

- full revision ID
- XML path
- source node ID / source document order
- source XML SHA-256
- retrieval rank / score metadata
- provenance verification state

技術metadataはデフォルトで折りたたみ、一般利用者の視界を埋めないようにします。

## Source Drawer

「原文を見る」で画面右または下からdetail drawerを開きます。

表示:

- 法令名
- revision
- 条文位置
- Evidenceに対応する原文
- 前後の最小context
- XML path
- RAW SHA

Phase 7-1では法令全文viewerを作りません。Evidenceのsource nodeへ戻れれば完了とします。

## Empty / Failure States

### Retrieval hit 0

```text
根拠として提示できる検索結果が見つかりませんでした。
質問の語句または対象時点を変えてください。
```

LLMによる一般知識回答へfallbackしません。

### Evidence rebuild failure

```text
検索候補は見つかりましたが、原文への来歴を検証できませんでした。
この候補は根拠として表示しません。
```

### Provider failure

Evidenceが完成していればEvidenceは表示し、answerだけをfailedとして扱います。

## Accessibility

- statusを色だけで伝えない
- keyboardのみで質問送信、Evidence展開、drawer closeが可能
- focus orderは Query → Answer → Evidence の順
- Evidence markerからcardへfocus移動可能
- HTML semantic elementを優先
- 原文引用と生成回答を視覚的・semanticに区別

## Visual Tone

Phase 7-1では装飾を増やさず、文書を読むための静かなUIを採用します。

- 明るい背景を基本
- 本文幅を読みやすく制限
- status / Evidence / generated answerをcomponent単位で明確に分離
- 法令原文は生成回答より少し「資料」らしい表示にする
- monospaceはrevision ID / SHA / XML pathなど技術値だけに使用

## Phase 7-1 UI Acceptance Criteria

1. 1画面から質問と基準日を送れる
2. temporal statusが回答より先に確認できる
3. answer内のEvidence markerとEvidence cardを対応づけられる
4. Evidence cardから原文detailへ進める
5. ambiguous / unresolved / not-foundを正常な状態として表示できる
6. provider未設定でもEvidence UIが成立する
7. narrow viewportで1カラムへ崩れる
8. keyboard操作だけで主要操作を完了できる
9. generated answerとsource textを見分けられる
10. UIだけを見ても「AI回答が法令原文そのものではない」ことが理解できる
