from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any
import zipfile

OFFICIAL_ALL_XML_URL = (
    "https://laws.e-gov.go.jp/bulkdownload?file_section=1&only_xml_flag=true"
)
REVISION_XML_RE = re.compile(
    r"^([0-9A-Z]{15})_([0-9]{8})_([0-9A-Z]{15})\.xml$"
)


def sha256_path(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_archive(archive_path: Path, captured_on: date) -> dict[str, Any]:
    if not archive_path.is_file():
        raise FileNotFoundError(archive_path)
    archive_size = archive_path.stat().st_size
    archive_sha = sha256_path(archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise AssertionError(f"ZIP CRC failure: {bad_member}")
        xml_infos = [
            info
            for info in archive.infolist()
            if not info.is_dir() and info.filename.lower().endswith(".xml")
        ]

    if not xml_infos:
        raise AssertionError("official bulk archive contains no XML members")

    member_names = [info.filename for info in xml_infos]
    duplicate_member_count = len(member_names) - len(set(member_names))
    if duplicate_member_count:
        raise AssertionError(
            f"duplicate XML member names: {duplicate_member_count}"
        )

    revision_ids: list[str] = []
    law_ids: list[str] = []
    unparsed: list[str] = []
    for info in xml_infos:
        basename = PurePosixPath(info.filename).name
        match = REVISION_XML_RE.fullmatch(basename)
        if match is None:
            unparsed.append(info.filename)
            continue
        revision_ids.append(basename[:-4])
        law_ids.append(match.group(1))

    if unparsed:
        raise AssertionError(
            "unrecognized XML member names: " + ", ".join(unparsed[:20])
        )
    duplicate_revision_count = len(revision_ids) - len(set(revision_ids))
    if duplicate_revision_count:
        raise AssertionError(
            f"duplicate revision ids: {duplicate_revision_count}"
        )

    part = {
        "name": archive_path.name,
        "size_bytes": archive_size,
        "sha256": archive_sha,
        "xml_count": len(xml_infos),
        "parsed_revision_id_count": len(revision_ids),
        "unique_revision_id_count": len(set(revision_ids)),
        "unique_law_id_count": len(set(law_ids)),
        "unparsed_xml_name_count": 0,
    }
    return {
        "schema_version": "1.0",
        "snapshot_role": "official-xml-runtime-snapshot",
        "captured_on": captured_on.isoformat(),
        "source": {
            "provider": "e-Gov法令検索",
            "url": OFFICIAL_ALL_XML_URL,
            "download_mode": "all-laws-xml-only",
        },
        "interpretation": {
            "raw_role": "Phase 7 runtime corpus source; immutable after hash capture",
            "api_role": "e-Gov Law API Version 2 supplies revision-history metadata and reconciliation",
            "snapshot_warning": (
                "This runtime snapshot is independent from the historical "
                "2026-09-04 v1 validation snapshot."
            ),
        },
        "parts": [part],
        "totals": {
            "zip_part_count": 1,
            "size_bytes": archive_size,
            "xml_count": len(xml_infos),
            "parsed_revision_id_count": len(revision_ids),
            "unique_revision_id_count": len(set(revision_ids)),
            "unique_law_id_count": len(set(law_ids)),
            "duplicate_revision_id_count": 0,
            "duplicate_member_name_count": 0,
            "unparsed_xml_name_count": 0,
        },
        "filename_contract": {
            "regex": REVISION_XML_RE.pattern,
            "meaning": "law_id + revision effective-date token + amending-law-id token",
        },
        "verification": {
            "method": (
                "SHA-256, ZIP CRC, XML member enumeration, revision-ID filename "
                "contract, duplicate member names, and duplicate revision IDs"
            ),
            "result": "passed",
        },
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate current official e-Gov all_xml.zip and emit a Phase 4-compatible manifest"
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    parser.add_argument(
        "--captured-on",
        type=date.fromisoformat,
        default=date.today(),
        help="snapshot capture date in YYYY-MM-DD form",
    )
    args = parser.parse_args()
    manifest = inspect_archive(args.archive, args.captured_on)
    write_manifest(args.manifest_out, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
