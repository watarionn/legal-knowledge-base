# Phase 7 Daily Legal Assistant Web App

## 位置づけ

Phase 1〜6で完成した法令ナレッジベース v1 を、人が日常的に利用できるWebアプリへ変換するフェーズです。

Phase 7では法令本文・履歴・XML・検索/RAGの正本を作り直しません。既存のPhase 3〜6をsource of truthとして利用し、その上に薄いapplication/API/UI layerを構築します。

設計上の最重要原則は、**AIを法令の正本にしないこと**です。AIは検索・整理・説明の案内役であり、最終的な根拠は必ず既存の法令本文、revision、Evidence Bundle、RAW provenanceへ戻れることを必須とします。

## Phase 7 全体像

Phase 7は次の順序で進めます。

1. Phase 7-1 最小Webアプリ
2. Phase 7-2 時点検索・改正履歴UI
3. Phase 7-3 条文比較
4. Phase 7-4 関連資料探索
5. Phase 7-5 日常利用機能
6. Phase 7-6 法令ウォッチ。必要に応じてPhase 8へ分離可

本書ではPhase 7-1の要件を確定します。

---

# Phase 7-1 最小Webアプリ

## 目的

利用者が自然言語で法令について質問し、回答と同時に、その回答がどの法令・revision・条文・原文・RAW provenanceに基づくかを確認できる最小Webアプリを構築します。

最初の完成形は「回答がそれらしく見えること」ではなく、**回答から根拠へ迷わず潜れること**を成功条件とします。

## 対象ユーザー

初期版は個人利用を主対象とします。

- 日本の法令を自然言語で調べたい利用者
- 現行法だけでなく、指定日時点の法令を確認したい利用者
- AI回答だけではなく根拠条文を確認したい利用者
- 後から改正履歴や関連資料へ掘り下げたい利用者

Phase 7-1では組織向け権限管理や複数ユーザー運用を必須要件にしません。

## 主要ユーザーストーリー

### US-01 自然言語で質問する

利用者として、法令名や条番号を知らなくても自然言語で質問したい。

例:

- 「建設業法で請負契約に関係する規定を教えて」
- 「個人情報保護法で本人の同意が必要になる場面は？」

### US-02 時点を指定する

利用者として、「2024年4月1日時点」のように日付を指定し、その時点で適用対象となるrevisionだけを使って回答してほしい。

時点解決はPhase 5.1 strict resolverを使用し、ambiguous / unresolved / not-foundを勝手にresolvedへ丸めません。

### US-03 根拠条文を見る

利用者として、回答の各主張がどのEvidence Bundle・条文・XML pathに基づいているか確認したい。

### US-04 原文へ戻る

利用者として、要約やAI生成文ではなく、根拠となる法令原文を確認したい。

### US-05 回答不能を正しく知る

利用者として、根拠不足・時点不確定・本文未収録などの場合に、AIが推測して埋めず、回答不能または限定回答として明示してほしい。

## Phase 7-1 必須機能

### 1. 質問入力

- 自然言語の質問を入力できる
- 任意で基準日 `as_of_date` を指定できる
- 空入力を拒否する
- 初期版では1回の質問を独立requestとして扱い、会話履歴依存は必須にしない

### 2. 法令・revision解決

- 法令候補を識別する
- 基準日がある場合はPhase 5.1 strict temporal resolverを使用する
- `resolved` の場合のみ対象revisionを確定する
- `ambiguous` / `unresolved` / `not-found` を明示する
- 本文availability不足時に別revisionへfallbackしない

### 3. Retrieval

- Phase 5.3 hybrid retrievalを利用する
- lexical / structural / vectorを交換可能な検索候補として扱う
- retrieval chunkを引用正本にしない
- 検索結果は必ずPhase 4 source nodeとRAW provenanceへbacklink可能であること

### 4. Evidence Bundle

- Phase 5.3dのEvidence BundleをWeb APIの根拠単位として利用する
- 各Evidenceに一意なIDを持たせる
- Evidenceから以下へ到達できること
  - `law_id`
  - `law_revision_id`
  - 条文または構造path
  - Phase 4 source node
  - source XML SHA-256
- unknown Evidence IDを回答に使用しない

### 5. 回答生成

- 回答はsource truthではない
- 各非空claimは1件以上の既知Evidence IDを参照する
- 根拠なしclaimをfinal回答に含めない
- semantic entailmentをシステムが自動保証したとは表示しない
- LLM/providerは交換可能とし、provider/model/versionを記録できる構造にする
- LLMが未設定でもretrieval + Evidence表示だけは利用可能な構造を優先する

### 6. 回答表示

最低限、以下を表示する。

- 回答本文
- 対象法令
- 基準日
- temporal resolution status
- 対象revision
- 根拠一覧
- 根拠ごとの原文抜粋
- XML構造pathまたは条文位置
- provenance識別情報

### 7. エラー・不確定状態表示

次を通常系としてUIに表現する。

- `ambiguous`
- `unresolved`
- `not-found`
- 対象revisionは確定したが本文が未収録
- retrieval hitなし
- Evidence Bundle再構築失敗
- answer provider未設定

これらをHTTP 500相当の単純障害として隠さない。

## 画面構成の最小要件

Phase 7-1は原則1画面で開始します。

### 上部

- アプリ名
- 短い説明
- 基準日入力

### 中央

- 大きな質問入力欄
- 送信ボタン

### 回答領域

- 回答本文
- 法令名 / law ID
- 基準日
- revision ID
- temporal status

### 根拠領域

回答本文の下または横にEvidence cardを並べます。

Evidence cardの最低表示項目:

- Evidence ID
- 条文・構造位置
- 原文抜粋
- revision ID
- source XML SHA-256の短縮表示
- 「原文を見る」操作

Phase 7-1では高度なグラフ表示、履歴タイムライン、条文diffは実装しません。

## API境界

UIからPhase 3〜6のDB実装を直接呼ばせません。Phase 7 application APIを境界にします。

初期API候補:

### `POST /api/v1/query`

入力例:

```json
{
  "question": "建設業法で請負契約に関係する規定を教えて",
  "as_of_date": "2024-04-01"
}
```

出力の概念構造:

```json
{
  "query_id": "...",
  "question": "...",
  "as_of_date": "2024-04-01",
  "temporal_resolution": {
    "status": "resolved",
    "law_id": "...",
    "law_revision_id": "..."
  },
  "answer": {
    "status": "answered",
    "text": "...",
    "claims": [
      {
        "claim_id": "c1",
        "text": "...",
        "evidence_ids": ["e1"]
      }
    ]
  },
  "evidence": [
    {
      "evidence_id": "e1",
      "law_id": "...",
      "law_revision_id": "...",
      "xml_path": "...",
      "source_xml_sha256": "...",
      "quote": "..."
    }
  ]
}
```

正確なfield名はAPI設計工程で既存Phase 5 contractへ合わせて確定します。

### `GET /api/v1/evidence/{evidence_id}`

Evidenceの詳細、source node、原文、provenanceを表示するためのread endpoint候補です。

Phase 7-1では外部公開APIとしての互換性保証はまだ行いませんが、UI内部であっても境界を明確にします。

## 非機能要件

### 正確性・来歴

- AI生成文をsource truthとして保存・表示しない
- EvidenceとPhase 4 / Phase 3のbacklinkを壊さない
- ambiguousなrevisionを推測選択しない
- provenanceを確認できないEvidenceはcitation-readyとして表示しない

### セキュリティ

- SQLをUI入力から直接組み立てない
- question文字列をHTMLとして直接描画しない
- secrets、DB接続情報、LLM API keyをrepositoryへ保存しない
- 初期版はread-only applicationとして設計する

### 性能

Phase 7-1では全量global searchの最適化を完了条件にしません。

目標:

- UIの操作自体は即応する
- query処理中であることを明示する
- retrieval / answer生成の所要時間を分けて観測できる
- timeout時は根拠なし回答へfallbackしない

### 可観測性

少なくとも以下をquery単位で記録可能にする。

- query ID
- input question
- as_of_date
- temporal status
- selected law / revision
- retrieval hit数
- Evidence数
- answer status
- answer provider metadata
- elapsed time

個人利用ログに不要な秘密情報を含めない。

## 技術方針

Phase 7-1では既存Python資産を最大限再利用します。

推奨初期構成:

```text
browser
  -> Phase 7 Web UI
  -> Phase 7 Application API
  -> Phase 5 temporal / retrieval / evidence contracts
  -> Phase 3 / 4 PostgreSQL source truth
```

具体的なWeb frameworkは次の「API設計・最小実装」工程で選定します。

選定基準:

- 既存Python実装との統合が薄いこと
- ローカルで容易に起動できること
- PostgreSQLへread-only接続できること
- LLM providerなしでも動作確認できること
- 将来frontendを分離してもAPI contractを維持できること

## Phase 7-1 でやらないこと

以下は意図的に後続へ送ります。

- 条文版どうしのdiff表示
- 改正履歴タイムラインの高度なUI
- 官報・国会会議録・NDL資料の横断探索UI
- お気に入り
- 最近見た法令
- 検索履歴の永続化
- ユーザー認証
- 複数ユーザー権限管理
- 通知
- 法改正ウォッチ
- 法律相談としての結論保証
- LLMによる法的妥当性の自動保証

## Phase 7-1 完了条件

Phase 7-1は以下をすべて満たしたとき完了とします。

1. ローカルWeb UIから自然言語質問を送信できる
2. 任意の`as_of_date`を渡せる
3. strict temporal statusがUIへそのまま返る
4. resolved revisionだけを検索対象にできる
5. hybrid retrieval結果からEvidence Bundleを再構築できる
6. 回答の各claimが既知Evidence IDへ紐づく
7. 根拠条文・原文・revision・RAW provenanceをUIから確認できる
8. ambiguous / unresolved / not-foundを推測で隠さない
9. answer provider未設定時でもEvidence表示まで動作する
10. offline testsで既存Phase 3〜6のsource-truth境界を破壊していないことを確認する
11. secretsをrepositoryへ追加していない
12. READMEにローカル起動方法を記載する

## Phase 7-1 実装順

Phase 7-1の内部工程は以下で固定します。

1. 要件定義　本書
2. 画面構成
3. API設計
4. 最小実装
5. offline test
6. local PostgreSQL smoke
7. closure review

この順序を崩して、UI実装から先に始めないこととします。

## 後続Phase

### Phase 7-2 時点検索・改正履歴UI

- 日付picker改善
- revision候補表示
- 改正履歴timeline
- ambiguous候補の比較支援

### Phase 7-3 条文比較

- 旧revision / 新revision比較
- 条文単位diff
- 追加・削除・変更表示

### Phase 7-4 関連資料探索

- 官報
- 国会会議録
- 帝国議会会議録
- NDL資料
- confirmed relationだけをcitation-readyとして表示

### Phase 7-5 日常利用機能

- お気に入り法令
- 最近見た法令
- 検索履歴
- 保存テーマ

### Phase 7-6 法令ウォッチ

- 保存テーマに関連する変更検知
- 改正差分
- 対応期限・関連資料への導線

必要に応じて独立したPhase 8へ分離します。
