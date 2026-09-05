# Phase 5 full-search input preflight

## Result

The four split XML archives used for the full Phase 5 search benchmark were materialized from the connected private Google Drive on 2026-09-06 and checked against `docs/validation/xml_snapshot_manifest.public.json`.

All four archive byte sizes and SHA-256 digests matched the public manifest exactly. ZIP CRC validation passed for every archive. Across the four archives there are 10,711 XML members, zero duplicate member names, and about 3.418 GiB of uncompressed data. `all_xml_01.zip` additionally contains `all_law_list.csv`; the XML count is unaffected.

The verified corpus therefore matches the Phase 4 official XML RAW snapshot and is suitable as the input to `implementation/phase4/011_full_relational_import.py`.

## Verified archives

| archive | bytes | XML | SHA-256 |
| --- | ---: | ---: | --- |
| `all_xml_01.zip` | 13,519,406 | 1,714 | `97963a154c9e22c371028acf48cd8b5721bb37c56648c36f41d25141f16d3a8e` |
| `all_xml_02.zip` | 41,443,157 | 3,090 | `f13a767583c3f8382383f18488a22d16aeaef2304d77a43ac681cc22b269ac51` |
| `all_xml_03.zip` | 86,846,266 | 3,174 | `0966585fec0937a380a80323c47f1cd2dc762365e33428a20b7cc6136f9da47e` |
| `all_xml_04.zip` | 188,842,578 | 2,733 | `8d85fbeefbf66cced7e197a5ecf33370c882500e576408b1f2dfbbb66d6592d3` |

Total compressed bytes: 330,651,407. Total XML members: 10,711.

## Execution boundary

The current chat execution container can materialize the private Drive files, but it does not provide a PostgreSQL server/client and outbound network access is unavailable. Therefore the 17 GB-class Phase 4 relational database cannot be reconstructed inside this container.

This is an execution-environment limitation, not an input-data failure. The input corpus has passed the same size/SHA/XML-count contract expected by the Phase 4 full relational importer.

## Next execution

On a PostgreSQL 16+ environment with the repository checkout and these four archives in one directory:

```text
python implementation/phase4/011_full_relational_import.py \
  --archive-dir <archive-dir> \
  --database-url <database-url> \
  --result docs/validation/phase4_full_relational_import_result.json

python implementation/phase5/008_full_search_benchmark.py \
  --database-url <database-url> \
  --result docs/validation/phase5_full_search_benchmark_result.json
```

The benchmark result must not be fabricated from the Phase 4 historical counts. It is complete only when the benchmark runner has executed against the reconstructed full database and emitted its JSON evidence.
