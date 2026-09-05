from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path
import re
import zipfile
from xml.parsers import expat

REVISION_XML_RE = re.compile(r"^([0-9A-Z]{15}_[0-9]{8}_[0-9A-Z]{15})\.xml$")


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _sha256_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _blank() -> dict:
    return {
        "attempted_document_count": 0,
        "parsed_document_count": 0,
        "failed_document_count": 0,
        "total_node_count": 0,
        "total_element_count": 0,
        "total_comment_count": 0,
        "total_pi_count": 0,
        "max_nodes_per_document": 0,
        "max_nodes_document": None,
        "max_tree_depth": 0,
        "max_depth_document": None,
        "document_count_with_articleless_main_provision": 0,
        "articleless_main_provision_count": 0,
        "document_count_with_no_article_anywhere_in_main_provision": 0,
        "main_provision_count_with_no_article_anywhere": 0,
        "document_count_with_nonblank_tail_text": 0,
        "document_count_with_any_tail_text": 0,
        "document_count_with_oldnum": 0,
        "document_count_with_oldstyle": 0,
        "document_count_with_src_reference": 0,
        "attachment_reference_count": 0,
        "invalid_revision_filename_count": 0,
        "tag_document_counts": Counter(),
        "attribute_document_counts": Counter(),
        "lawbody_direct_child_occurrences": Counter(),
        "src_reference_tag_counts": Counter(),
        "parse_errors": [],
    }


def _scan_xml(fh) -> dict:
    d = {
        "nodes": 0,
        "elements": 0,
        "comments": 0,
        "pis": 0,
        "max_depth": 0,
        "tags": set(),
        "attrs": set(),
        "oldnum": False,
        "oldstyle": False,
        "src": False,
        "src_count": 0,
        "src_tags": Counter(),
        "nonblank_tail": False,
        "any_tail": False,
        "articleless_direct": 0,
        "articleless_anywhere": 0,
        "lawbody_children": Counter(),
    }
    stack: list[dict] = []
    parser = expat.ParserCreate(namespace_separator="}")
    parser.buffer_text = True

    def start(name: str, attrs: dict[str, str]) -> None:
        local = _local(name)
        if stack:
            stack[-1]["after_child"] = False
            if stack[-1]["local"] == "MainProvision" and local == "Article":
                stack[-1]["has_direct_article"] = True
            if stack[-1]["local"] == "LawBody":
                d["lawbody_children"][local] += 1
        if local == "Article":
            for frame in stack:
                if frame["local"] == "MainProvision":
                    frame["has_any_article"] = True
        stack.append(
            {
                "local": local,
                "after_child": False,
                "has_direct_article": False,
                "has_any_article": False,
            }
        )
        d["nodes"] += 1
        d["elements"] += 1
        d["max_depth"] = max(d["max_depth"], len(stack) - 1)
        d["tags"].add(local)
        for raw_name in attrs:
            attr = _local(raw_name)
            d["attrs"].add(attr)
            if attr == "OldNum":
                d["oldnum"] = True
            elif attr == "OldStyle":
                d["oldstyle"] = True
            if attr == "src":
                d["src"] = True
                d["src_count"] += 1
                d["src_tags"][local] += 1

    def end(_name: str) -> None:
        frame = stack.pop()
        if frame["local"] == "MainProvision":
            if not frame["has_direct_article"]:
                d["articleless_direct"] += 1
            if not frame["has_any_article"]:
                d["articleless_anywhere"] += 1
        if stack:
            stack[-1]["after_child"] = True

    def text(value: str) -> None:
        if stack and stack[-1]["after_child"] and value != "":
            d["any_tail"] = True
            if value.strip():
                d["nonblank_tail"] = True

    def comment(_value: str) -> None:
        d["nodes"] += 1
        d["comments"] += 1
        d["max_depth"] = max(d["max_depth"], len(stack))
        if stack:
            stack[-1]["after_child"] = True

    def pi(_target: str, _value: str) -> None:
        d["nodes"] += 1
        d["pis"] += 1
        d["max_depth"] = max(d["max_depth"], len(stack))
        if stack:
            stack[-1]["after_child"] = True

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    parser.CommentHandler = comment
    parser.ProcessingInstructionHandler = pi
    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
        parser.Parse(chunk, False)
    parser.Parse(b"", True)
    return d


def _scan_chunk(task: tuple[str, int, int]) -> dict:
    zip_path_text, start_index, end_index = task
    zip_path = Path(zip_path_text)
    m = _blank()
    m["archive_name"] = zip_path.name
    with zipfile.ZipFile(zip_path) as zf:
        members = [
            info
            for info in zf.infolist()
            if not info.is_dir() and info.filename.lower().endswith(".xml")
        ][start_index:end_index]
        for info in members:
            m["attempted_document_count"] += 1
            basename = Path(info.filename).name
            match = REVISION_XML_RE.fullmatch(basename)
            revision_id = match.group(1) if match else Path(basename).stem
            if match is None:
                m["invalid_revision_filename_count"] += 1
            try:
                with zf.open(info) as fh:
                    d = _scan_xml(fh)
            except Exception as exc:
                m["failed_document_count"] += 1
                if len(m["parse_errors"]) < 25:
                    m["parse_errors"].append(
                        {"member_path": info.filename, "error": repr(exc)}
                    )
                continue
            m["parsed_document_count"] += 1
            m["total_node_count"] += d["nodes"]
            m["total_element_count"] += d["elements"]
            m["total_comment_count"] += d["comments"]
            m["total_pi_count"] += d["pis"]
            if d["nodes"] > m["max_nodes_per_document"]:
                m["max_nodes_per_document"] = d["nodes"]
                m["max_nodes_document"] = revision_id
            if d["max_depth"] > m["max_tree_depth"]:
                m["max_tree_depth"] = d["max_depth"]
                m["max_depth_document"] = revision_id
            if d["articleless_direct"]:
                m["document_count_with_articleless_main_provision"] += 1
                m["articleless_main_provision_count"] += d["articleless_direct"]
            if d["articleless_anywhere"]:
                m["document_count_with_no_article_anywhere_in_main_provision"] += 1
                m["main_provision_count_with_no_article_anywhere"] += d["articleless_anywhere"]
            if d["nonblank_tail"]:
                m["document_count_with_nonblank_tail_text"] += 1
            if d["any_tail"]:
                m["document_count_with_any_tail_text"] += 1
            if d["oldnum"]:
                m["document_count_with_oldnum"] += 1
            if d["oldstyle"]:
                m["document_count_with_oldstyle"] += 1
            if d["src"]:
                m["document_count_with_src_reference"] += 1
            m["attachment_reference_count"] += d["src_count"]
            m["tag_document_counts"].update(d["tags"])
            m["attribute_document_counts"].update(d["attrs"])
            m["lawbody_direct_child_occurrences"].update(d["lawbody_children"])
            m["src_reference_tag_counts"].update(d["src_tags"])
    for key in (
        "tag_document_counts",
        "attribute_document_counts",
        "lawbody_direct_child_occurrences",
        "src_reference_tag_counts",
    ):
        m[key] = dict(m[key])
    return m


def _merge(parts: list[dict]) -> dict:
    total = _blank()
    per_archive: dict[str, dict] = {}
    numeric = [
        key
        for key, value in total.items()
        if isinstance(value, int) and key not in {"max_nodes_per_document", "max_tree_depth"}
    ]
    for part in parts:
        archive = per_archive.setdefault(part["archive_name"], _blank())
        for target in (total, archive):
            for key in numeric:
                target[key] += part[key]
            target["tag_document_counts"].update(part["tag_document_counts"])
            target["attribute_document_counts"].update(part["attribute_document_counts"])
            target["lawbody_direct_child_occurrences"].update(
                part["lawbody_direct_child_occurrences"]
            )
            target["src_reference_tag_counts"].update(part["src_reference_tag_counts"])
            target["parse_errors"].extend(part["parse_errors"])
            if part["max_nodes_per_document"] > target["max_nodes_per_document"]:
                target["max_nodes_per_document"] = part["max_nodes_per_document"]
                target["max_nodes_document"] = part["max_nodes_document"]
            if part["max_tree_depth"] > target["max_tree_depth"]:
                target["max_tree_depth"] = part["max_tree_depth"]
                target["max_depth_document"] = part["max_depth_document"]
    return {"totals": total, "per_archive": per_archive}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--zip-dir", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--chunk-size", type=int, default=300)
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    tasks: list[tuple[str, int, int]] = []
    archive_identity = {}
    for part in manifest["parts"]:
        zip_path = args.zip_dir / part["name"]
        actual_sha = _sha256_file(zip_path)
        if actual_sha.lower() != part["sha256"].lower():
            raise SystemExit(f"SHA-256 mismatch: {zip_path}")
        with zipfile.ZipFile(zip_path) as zf:
            count = sum(
                1 for i in zf.infolist()
                if not i.is_dir() and i.filename.lower().endswith(".xml")
            )
        if count != part["xml_count"]:
            raise SystemExit(f"XML count mismatch: {zip_path}: {count}")
        archive_identity[part["name"]] = {
            "sha256": actual_sha,
            "xml_count": count,
        }
        for start in range(0, count, args.chunk_size):
            tasks.append((str(zip_path), start, min(start + args.chunk_size, count)))

    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(_scan_chunk, task) for task in tasks]
        for future in as_completed(futures):
            results.append(future.result())

    merged = _merge(results)
    totals = merged["totals"]
    expected = manifest["totals"]["xml_count"]
    payload = {
        "schema_version": "1.0",
        "scanner": "007_full_corpus_scan.py",
        "snapshot_manifest": str(args.manifest),
        "input_identity": archive_identity,
        "totals": totals,
        "per_archive": merged["per_archive"],
        "distinct_tag_name_count": len(totals["tag_document_counts"]),
        "distinct_attribute_name_count": len(totals["attribute_document_counts"]),
        "invariants": {
            "all_inputs_attempted": totals["attempted_document_count"] == expected,
            "no_parse_failures": totals["failed_document_count"] == 0,
            "revision_filenames_valid": totals["invalid_revision_filename_count"] == 0,
        },
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["invariants"], ensure_ascii=False))
    if not all(payload["invariants"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
