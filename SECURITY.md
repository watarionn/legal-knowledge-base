# Security Policy

## Reporting a vulnerability

このリポジトリのコードに、認証情報の漏えい、任意コード実行、SQL injection、危険なファイル処理などのセキュリティ上の問題を見つけた場合は、秘密情報や実 exploit を公開Issueへ貼り付けないでください。

GitHubのPrivate vulnerability reportingが利用可能な場合は、それを優先してください。利用できない場合は、公開Issueには最小限の概要だけを書き、機密情報を含む詳細は公開しないでください。

## Data safety

- APIキー、パスワード、DSN、アクセストークンをコミットしないでください。
- 大容量RAW法令データやDB dumpはGit履歴へ入れません。
- provenanceとして公開するlocatorは、公開情報であることを確認してください。
- parserは公式RAWを自動修正して原本を置き換えません。
