# Phase 7 Local RAG

## 目的

Phase 7の日常利用Webアプリに、ローカルOllamaを使った説明生成を任意追加する。
生成AIは法令のsource truthにならず、Phase 3〜4から復元したEvidenceだけを説明材料とする。

既存ロードマップのPhase 7-6は法令ウォッチ用に予約済みのため、本機能は番号を付けず `Phase 7 Local RAG` 拡張として扱う。

## 基本経路

1. deterministic law discovery
2. strict temporal resolution
3. lexical / structural retrieval
4. Evidence Bundle構築
5. substantive Evidence gate
6. local Ollama answer provider
7. claim-to-Evidence validation
8. Web UI表示

Ollamaが未設定、停止、不正JSON、未知Evidence参照、本文Evidence不足のいずれかなら生成回答をsource truthへ昇格させない。

## Source truth

生成回答の `generated_answer_is_source_truth` は常に `false` とする。
法的根拠はPhase 3〜4の法令revision、source XML SHA-256、provision node、XML pathである。

## Article本文補完

条番号のstructural retrievalでは、ArticleCaption / ArticleTitleだけが最初のchunkになる場合がある。
その場合、同一Article配下のdescendant chunkを追加する。

補完条件は次をすべて満たすことを必須とする。

- 同一 `law_id`
- 同一 `law_revision_id`
- 同一 `document_pk`
- 同一 `source_xml_sha256`
- 同一chunking config
- Article境界の内側

境界外や別revisionの本文を代用しない。

### exact Articleの検索優先順位

質問に明示的な `第○条` がある場合、lexical channelは実行せずstructural Article検索を優先する。
一般語（例: `無効`）のlexical hitがcontext上限を先に埋め、指定Articleが脱落することを防ぐためである。
質問原文はAnswer Providerへそのまま渡すため、ユーザーの説明意図は保持する。

## substantive Evidence gate

LLM生成用Evidenceは、実質的な本文ノードを含むBundleだけに限定する。
ArticleTitle / ArticleCaptionなど見出しだけのBundleはWeb上の根拠表示には残せるが、生成材料にはしない。

本文Evidenceが0件ならOllamaを呼ばず、query statusは `evidence-only` のまま返す。
警告として `ANSWER_SKIPPED_NO_SUBSTANTIVE_EVIDENCE` を付与する。

## Ollama境界

`LEGAL_KB_ANSWER_PROVIDER=ollama` の場合だけAnswer Providerを有効化する。
Ollama URLはloopback host (`127.0.0.1`, `localhost`, `::1`) のみに制限する。
既定modelは `gemma3:4b`。

モデルには質問とEvidenceだけを渡し、一般知識・記憶・判例・学説・推測で不足を補わないよう指示する。
出力はJSON claims形式とし、各claimは実在Evidence IDを1件以上引用する。
未知Evidence ID、不正JSON、空claim、上限超過はfail-closedとする。

## UI

生成回答には「AI生成の説明」であることを明示する。
法的根拠は別欄の法令原文であることを表示する。
本文Evidence不足で生成を停止した場合も、通常のprovider未設定と区別して表示する。

## 非目標

- 生成回答を法令原文の代替にしない
- Ollamaを外部ネットワークへ公開しない
- vector retrievalを本拡張の必須条件にしない
- Phase 7-6法令ウォッチの番号・責務を変更しない
