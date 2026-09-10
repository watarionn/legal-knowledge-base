# Phase 7-1 Web App API Design

## 目的

Phase 7-1 Web UIと既存Phase 3〜6のsource truthの間に、薄いapplication APIを置きます。

APIは既存のstrict temporal resolution、hybrid retrieval、Evidence Bundle、answer contractを再利用し、UIからDBやPhase 5内部関数を直接操作させません。

## 基本原則

1. UI入力をそのままSQLへ埋め込まない
2. AIに`law_id`を確定させない
3. temporal ambiguityを推測で解消しない
4. retrieval contextをcitation-readyとして扱わない
5. Evidence Bundleから再構築できた原文だけを根拠として返す
6. answer providerが失敗してもEvidenceを失わない
7. answer provider未設定でもretrieval + Evidenceまで利用できる
8. generated answerはsource truthではない

## API Version

初期内部APIは `/api/v1` とします。

Phase 7-1では外部利用者向けの長期互換性保証は行いませんが、response contractはtestで固定します。

---

# 1. Query API

## `POST /api/v1/query`

質問から法令候補解決、時点解決、retrieval、Evidence構築、任意の回答生成までを1 requestで実行します。

### Request

```json
{
  "question": "2024年4月時点の建設業法で請負契約に関係する規定を教えて",
  "as_of_date": "2024-04-01",
  "law_id": null
}
```

### fields

- `question`: required string
- `as_of_date`: optional ISO date
- `law_id`: optional explicit e-Gov law ID

`law_id`を明示した場合は質問文からのlaw discoveryを省略できます。

### validation

- `question.strip()`が空なら400
- questionは初期上限4000 characters
- `as_of_date`はISO `YYYY-MM-DD`
- `law_id`指定時は既存の15文字patternへ適合必須
- unknown request fieldは初期版では400とし、typoを黙って無視しない

---

# 2. Law Discovery

Phase 5のstrict resolverは`law_id`を必要とするため、Phase 7 application layerでlaw discoveryを行います。

## 方針

Law discoveryは「法的結論」ではなく検索対象候補の特定です。それでもLLMによる自由推測で1 lawへ固定しません。

優先順位:

1. requestのexplicit `law_id`
2. 質問中の15文字law ID完全一致
3. 法令番号完全一致
4. `law_title`完全phrase containment
5. `abbrev`完全phrase containment
6. lexical candidate discovery

同一lawの複数revisionに同名がある場合は`law_id`へgroupします。

## deterministic phrase rule

質問内に複数の法令名が含まれる場合、最長phraseを優先できます。ただし同じ最大長・同じ優先順位で複数law IDが残る場合は自動確定しません。

例:

- 「労働基準法施行令」には「労働基準法」も含まれ得るため、より長い完全phraseを優先
- 同一略称が複数lawに対応する場合はambiguous

## lexical candidate discovery

質問に法令名が含まれない場合、既存search layerを利用して関連law候補を探索できます。

この段階のhitはcitationではなく**候補発見だけ**に使います。

初期版では、explicit/title/abbrevで一意確定できない場合、lexical候補を自動で1件に断定せず、`law-candidates`としてUIに返すことを安全側の既定とします。

## LawResolution object

```json
{
  "status": "resolved",
  "method": "title-phrase",
  "selected_law_id": "...",
  "selected_law_title": "建設業法",
  "candidates": []
}
```

status:

- `resolved`
- `law-candidates`
- `law-not-found`

`law-candidates`ではretrievalとanswer generationを実行しません。

---

# 3. Temporal Resolution

lawがresolvedのときだけPhase 5.1へ進みます。

Phase 5 `TemporalResolution`を可能な限りそのままAPIへ投影します。

```json
{
  "law_id": "...",
  "as_of_date": "2024-04-01",
  "status": "resolved",
  "selected_revision_id": "...",
  "content_status": "available",
  "selected_document_pk": 123,
  "selected_document_id": "...",
  "source_xml_sha256": "...",
  "candidates": [],
  "warnings": []
}
```

既存statusを改名しません。

- `resolved`
- `ambiguous`
- `unresolved`
- `not-found`

content status:

- `available`
- `missing`
- `multiple`
- `candidate-dependent`
- `none`

### as_of_date未指定

Phase 7-1では「今日」を無条件に法的基準日へ変換しません。

application layerは次のいずれかを明示的に行う必要があります。

- current revisionを取得する専用queryを使用する
- またはrequest処理時点の日付を`effective_query_date`として利用したことをresponse metadataに明記する

最小実装では、挙動を単純化するため**未指定時はサーバーlocal dateをquery dateとして補完し、その補完を`as_of_date_source: server-date-default`として必ず返す**方式を採用します。

この日付補完はrevisionの曖昧さを解消する規則ではありません。Phase 5 strict resolverの結果がambiguousならそのまま止めます。

---

# 4. Retrieval

Temporal resultが以下を満たす場合だけ実行します。

- `status == resolved`
- `content_status == available`

Phase 5 `hybrid_retrieve()`を使用します。

初期configuration:

- lexical: enabled
- structural: query parserが明示filterを生成した場合のみ
- vector: embedding provider/profileが設定されている場合のみ
- vector未設定でもlexical retrievalで動作

`chunking_config_sha256`はDBに存在する利用可能configをapplication startup時に明示設定します。暗黙に任意のconfigを選ばないよう、環境変数またはstartup discovery結果をlogへ残します。

retrieval result status:

- `ok`
- `no-hits`
- `blocked-temporal`
- `blocked-content`

---

# 5. Evidence Projection

`build_evidence_bundles()`でPhase 4 source nodeへ戻した後のみEvidenceとして返します。

API representation:

```json
{
  "evidence_id": "sha256...",
  "retrieval_rank": 1,
  "chunk_id": "...",
  "law_id": "...",
  "law_revision_id": "...",
  "document_pk": 123,
  "source_xml_sha256": "...",
  "source_nodes": [
    {
      "document_order": 12345,
      "node_id_hex": "...",
      "xml_path": "/Law/...",
      "tag_name": "Paragraph",
      "structural_num": "1",
      "display_label": "第1項",
      "text_original": "..."
    }
  ]
}
```

Phase 5 contractと同じfieldを維持します。

UI向けに次のderived fieldを追加してもよいですが、source値を置換しません。

- `display_path`
- `quote`
- `source_xml_sha256_short`

`quote`はsource_nodesの`text_original`からdeterministicに作り、生成AIに作らせません。

---

# 6. Answer

answer providerはoptionalです。

## provider未設定

```json
{
  "status": "provider-not-configured",
  "answer_text": "",
  "claims": [],
  "provider": null,
  "citation_ready": false
}
```

Evidenceは通常どおり返します。

## provider設定済み

Phase 5 `generate_and_finalize()`または同じcontractを満たすproviderを使用します。

provider outputはPhase 5 contractによって以下を検証します。

- answer text non-empty
- claimあり
- claim text non-empty
- 各claimがEvidenceを1件以上参照
- unknown Evidence IDなし
- duplicate claim IDなし

`citation_ready=true`は参照整合性が検証済みであることだけを意味します。

`semantic_entailment_verified`はPhase 7-1では常にfalseです。

---

# 7. Query Response

成功・不確定・no-hitを同じtop-level envelopeで返します。

```json
{
  "api_version": "1",
  "query_id": "uuid",
  "question": "...",
  "requested_as_of_date": "2024-04-01",
  "effective_as_of_date": "2024-04-01",
  "as_of_date_source": "request",
  "status": "answered",
  "law_resolution": {},
  "temporal_resolution": {},
  "retrieval": {
    "status": "ok",
    "retrieval_version": "...",
    "channel_counts": {
      "lexical": 12,
      "structural": 0,
      "vector": 0
    },
    "warnings": []
  },
  "answer": {},
  "evidence": [],
  "timing_ms": {
    "law_resolution": 0,
    "temporal_and_retrieval": 0,
    "evidence": 0,
    "answer": 0,
    "total": 0
  },
  "warnings": []
}
```

## top-level status

Phase 7-1で固定するstatus:

- `answered`
- `evidence-only`
- `law-candidates`
- `law-not-found`
- `blocked-temporal`
- `blocked-content`
- `no-hits`
- `evidence-failed`
- `answer-failed`

正常な不確定状態に5xxを使いません。

---

# 8. Evidence Detail API

## `GET /api/v1/evidence/{evidence_id}`

Phase 7-1のEvidence IDはquery時に構築されるdeterministic IDです。

最小実装ではserver memoryにquery responseを保持してdetail表示できますが、プロセス再起動後の永続lookupを保証しません。

response:

```json
{
  "evidence_id": "...",
  "law_id": "...",
  "law_revision_id": "...",
  "source_xml_sha256": "...",
  "source_nodes": [],
  "citation_truth": "phase3-phase4"
}
```

Phase 7-5で検索履歴永続化を導入する場合、Evidence persistenceを再検討します。

---

# 9. Health API

## `GET /api/v1/health`

外部providerへ通信しません。

```json
{
  "status": "ok",
  "database": "configured",
  "answer_provider": "not-configured",
  "vector_provider": "not-configured",
  "app_version": "phase7-1-mvp"
}
```

DBへ軽量`SELECT 1`を行うdeep healthは別endpointに分けてもよいです。

---

# 10. HTTP status policy

- 200: answered / evidence-only / candidate / temporal blocked / no-hitsなどapplication上の正常結果
- 400: request validation error
- 404: unknown endpoint / expired Evidence detail
- 405: method not allowed
- 413: request body too large
- 500: invariant violationや予期しないserver fault
- 503: DB接続不能などapplication dependency unavailable

`ambiguous`を500へ変換しないことが重要です。

---

# 11. Error body

```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "question must not be blank",
    "query_id": "..."
  }
}
```

server traceback、DATABASE_URL、API key、内部filesystem pathをbrowserへ返しません。

---

# 12. Logging

queryごとにJSON lineまたはstructured logとして以下を記録可能にします。

- query_id
- question length
- as_of_date source
- selected law ID
- temporal status
- retrieval status
- channel counts
- Evidence count
- answer status
- provider/model/version
- timing

初期版ではquestion全文を既定ログへ残さず、必要時だけ明示設定で有効化します。

---

# 13. Configuration

secretsはrepositoryへ保存しません。

初期候補:

- `LEGAL_KB_DATABASE_URL`
- `LEGAL_KB_CHUNKING_CONFIG_SHA256`
- `LEGAL_KB_EMBEDDING_PROFILE_ID`
- `LEGAL_KB_HOST`
- `LEGAL_KB_PORT`
- answer provider固有secret

未設定のoptional providerは機能を無効化するだけで、アプリ全体を起動不能にしません。

DATABASE URLはquery実行には必須ですが、static UIの起動自体は可能にしてもよいです。

---

# 14. Minimal Implementation Boundary

次工程の最小実装では以下まで作ります。

1. Phase 7 application contract
2. deterministic law phrase resolver
3. Phase 5 temporal / hybrid / Evidence adapter
4. providerなしのEvidence-only query pipeline
5. standard HTTP API
6. 1画面HTML/CSS/JS UI
7. offline unit tests

LLM provider adapterは最小実装の必須blocking項目にしません。まず**質問から一次根拠をWebで確認できること**を完成させ、その後answer providerを接続します。
