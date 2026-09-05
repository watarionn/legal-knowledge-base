from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
import xml.etree.ElementTree as ET
from typing import Any, Iterable

UNIT_SEPARATOR = "\x1f"
PARSER_VERSION = "phase4-xml-parser-0.1"
REVISION_ID_RE = re.compile(r"^[0-9A-Z]{15}_[0-9]{8}_[0-9A-Z]{15}$")
XML_DECL_ENCODING_RE = re.compile(
    br"^(?:\xef\xbb\xbf)?\s*<\?xml\b[^>]*\bencoding\s*=\s*['\"]([^'\"]+)['\"]",
    re.I,
)

DISPLAY_LABEL_CHILD = {
    "Article": "ArticleTitle",
    "Paragraph": "ParagraphNum",
    "Item": "ItemTitle",
    "SupplProvision": "SupplProvisionLabel",
    "AppdxTable": "AppdxTableTitle",
    "AppdxNote": "AppdxNoteTitle",
    "AppdxStyle": "AppdxStyleTitle",
    "AppdxFig": "AppdxFigTitle",
    "AppdxFormat": "AppdxFormatTitle",
    "Appdx": "AppdxTitle",
}


@dataclass(frozen=True)
class ParsedXmlDocument:
    """PostgreSQLのPhase 4テーブルへ投入できる行集合。"""

    law_document: dict[str, Any]
    nodes: list[dict[str, Any]]
    attachments: list[dict[str, Any]]
    issues: list[dict[str, Any]]


def _digest(*parts: str) -> str:
    return sha256(UNIT_SEPARATOR.join(parts).encode("utf-8")).hexdigest()


def make_document_id(law_revision_id: str, source_xml_sha256: str) -> str:
    return _digest(law_revision_id, source_xml_sha256.lower())


def make_node_id(document_id: str, node_kind: str, xml_path: str) -> str:
    return _digest(document_id, node_kind, xml_path)


def make_attachment_id(
    document_id: str,
    ref_node_id: str,
    source_attribute_name: str,
    source_src: str,
) -> str:
    return _digest(document_id, ref_node_id, source_attribute_name, source_src)


def split_expanded_name(name: str) -> tuple[str | None, str]:
    if name.startswith("{"):
        uri, local = name[1:].split("}", 1)
        return uri, local
    return None, name


def expanded_name_for_path(name: str) -> str:
    uri, local = split_expanded_name(name)
    return f"{{{uri}}}{local}" if uri is not None else local


def attributes_for_storage(attrib: dict[str, str]) -> dict[str, str]:
    """属性名をClark形式へ正規化し、namespace衝突を起こさず原値を保持する。"""

    return {expanded_name_for_path(name): value for name, value in attrib.items()}


def projected_attribute(attrib: dict[str, str], local_name: str) -> str | None:
    """Num/OldNum/OldStyle等の検索用投影。曖昧な場合は勝手に選ばない。"""

    values = [
        value
        for name, value in attrib.items()
        if split_expanded_name(name)[1] == local_name
    ]
    return values[0] if len(values) == 1 else None


def _is_comment(elem: ET.Element) -> bool:
    return elem.tag is ET.Comment


def _is_pi(elem: ET.Element) -> bool:
    return elem.tag is ET.ProcessingInstruction


def _node_kind(elem: ET.Element) -> str:
    if _is_comment(elem):
        return "comment"
    if _is_pi(elem):
        return "processing-instruction"
    return "element"


def _path_counter_key(elem: ET.Element) -> tuple[str, str | None]:
    kind = _node_kind(elem)
    if kind == "element":
        return kind, str(elem.tag)
    return kind, None


def _path_segment(elem: ET.Element, same_kind_index: int) -> str:
    kind = _node_kind(elem)
    if kind == "comment":
        return f"comment()[{same_kind_index}]"
    if kind == "processing-instruction":
        return f"processing-instruction()[{same_kind_index}]"
    return f"{expanded_name_for_path(str(elem.tag))}[{same_kind_index}]"


def _element_string_value(elem: ET.Element) -> str:
    """コメント/PI本文を除き、descendant character dataを文書順に連結する。"""

    if _node_kind(elem) != "element":
        return elem.text or ""

    pieces: list[str] = []
    if elem.text is not None:
        pieces.append(elem.text)

    for child in list(elem):
        if _node_kind(child) == "element":
            pieces.append(_element_string_value(child))
        if child.tail is not None:
            pieces.append(child.tail)

    return "".join(pieces)


def _display_label(elem: ET.Element, tag_name: str) -> str | None:
    wanted = DISPLAY_LABEL_CHILD.get(tag_name)
    if not wanted:
        return None

    for child in list(elem):
        if _node_kind(child) != "element":
            continue
        _, local = split_expanded_name(str(child.tag))
        if local == wanted:
            value = _element_string_value(child)
            return value if value != "" else None
    return None


def _pi_target(elem: ET.Element) -> str | None:
    if not _is_pi(elem) or not elem.text:
        return None
    return elem.text.split(None, 1)[0]


def _xml_decl_encoding(xml_bytes: bytes) -> str | None:
    match = XML_DECL_ENCODING_RE.search(xml_bytes[:512])
    return match.group(1).decode("ascii", errors="replace") if match else None


def _parse_root(xml_bytes: bytes) -> ET.Element:
    parser = ET.XMLParser(
        target=ET.TreeBuilder(insert_comments=True, insert_pis=True)
    )
    return ET.fromstring(xml_bytes, parser=parser)


def parse_xml_bytes(
    xml_bytes: bytes,
    *,
    law_revision_id: str,
    source_file_id: str,
    ingestion_run_id: str,
    parser_version: str = PARSER_VERSION,
    schema_validation_status: str = "not-checked",
    schema_validation_errors: Iterable[Any] = (),
) -> ParsedXmlDocument:
    """1 XMLをPhase 4の正規化行集合へ変換する。

    RAW XMLバイト列は変更しない。XSD invalidは拒否理由にせず、well-formedness
    エラーだけをparse_status=failedとしてノード生成を止める。
    """

    if not REVISION_ID_RE.fullmatch(law_revision_id):
        raise ValueError(f"invalid law_revision_id: {law_revision_id}")

    source_xml_sha256 = sha256(xml_bytes).hexdigest()
    document_id = make_document_id(law_revision_id, source_xml_sha256)
    base_document = {
        "document_id": document_id,
        "law_revision_id": law_revision_id,
        "source_file_id": source_file_id,
        "ingestion_run_id": ingestion_run_id,
        "xml_schema_version": None,
        "xml_decl_encoding": _xml_decl_encoding(xml_bytes),
        "root_tag_name": None,
        "root_namespace_uri": None,
        "root_attributes_jsonb": {},
        "source_xml_sha256": source_xml_sha256,
        "parser_version": parser_version,
        "parse_status": "pending",
        "schema_validation_status": schema_validation_status,
        "schema_validation_errors_jsonb": list(schema_validation_errors),
        "node_count": None,
        "attachment_reference_count": None,
    }

    try:
        root = _parse_root(xml_bytes)
    except ET.ParseError as exc:
        position = getattr(exc, "position", None)
        issue = {
            "document_id": document_id,
            "node_id": None,
            "issue_code": "XML_NOT_WELL_FORMED",
            "severity": "error",
            "message": str(exc),
            "source_line": position[0] if position else None,
            "details_jsonb": {"position": list(position)} if position else {},
            "ingestion_run_id": ingestion_run_id,
        }
        failed = dict(base_document)
        failed.update(
            {
                "parse_status": "failed",
                "node_count": 0,
                "attachment_reference_count": 0,
            }
        )
        return ParsedXmlDocument(failed, [], [], [issue])

    root_uri, root_local = split_expanded_name(str(root.tag))
    nodes: list[dict[str, Any]] = []
    attachments: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    document_order = 0
    node_order_by_id: dict[str, int] = {}

    def visit(
        elem: ET.Element,
        parent_node_id: str | None,
        path: str,
        ordinal: int,
        path_index: int,
        depth: int,
    ) -> str:
        nonlocal document_order

        kind = _node_kind(elem)
        node_id = make_node_id(document_id, kind, path)
        document_order += 1
        current_order = document_order
        node_order_by_id[node_id] = current_order

        if kind == "element":
            namespace_uri, tag_name = split_expanded_name(str(elem.tag))
            attrs = attributes_for_storage(elem.attrib)
            element_children = [child for child in list(elem) if _node_kind(child) == "element"]
            has_direct_nonblank_text = bool(elem.text and elem.text.strip()) or any(
                child.tail and child.tail.strip() for child in list(elem)
            )
            text_original = (
                _element_string_value(elem)
                if not element_children or has_direct_nonblank_text
                else None
            )
            structural_num = projected_attribute(elem.attrib, "Num")
            old_num = projected_attribute(elem.attrib, "OldNum")
            old_style = projected_attribute(elem.attrib, "OldStyle")
            display_label = _display_label(elem, tag_name)
            qname_original = None
        else:
            namespace_uri = None
            tag_name = None
            attrs = {}
            text_original = elem.text or ""
            structural_num = None
            old_num = None
            old_style = None
            display_label = None
            qname_original = (
                _pi_target(elem)
                if kind == "processing-instruction"
                else None
            )

        row = {
            "node_id": node_id,
            "document_id": document_id,
            "parent_node_id": parent_node_id,
            "node_kind": kind,
            "ordinal": ordinal,
            "path_index": path_index,
            "document_order": current_order,
            "depth": depth,
            "tag_name": tag_name,
            "namespace_uri": namespace_uri,
            "qname_original": qname_original,
            "structural_num": structural_num,
            "display_label": display_label,
            "old_num": old_num,
            "old_style": old_style,
            "attributes_jsonb": attrs,
            "text_original": text_original,
            "text_search_normalized": None,
            "mixed_content_jsonb": [],
            "xml_path": path,
            "source_line": None,
        }
        nodes.append(row)

        child_counters: dict[tuple[str, str | None], int] = {}
        mixed: list[dict[str, Any]] = []
        if kind == "element" and elem.text is not None:
            mixed.append({"kind": "text", "value": elem.text})

        for child_ordinal, child in enumerate(list(elem), start=1):
            key = _path_counter_key(child)
            child_counters[key] = child_counters.get(key, 0) + 1
            segment = _path_segment(child, child_counters[key])
            child_path = f"{path}/{segment}"
            child_node_id = visit(
                child,
                node_id,
                child_path,
                child_ordinal,
                child_counters[key],
                depth + 1,
            )

            if kind == "element":
                mixed.append({"kind": "child", "document_order": node_order_by_id[child_node_id]})
                if child.tail is not None:
                    mixed.append(
                        {
                            "kind": "tail",
                            "after_document_order": node_order_by_id[child_node_id],
                            "value": child.tail,
                        }
                    )

        row["mixed_content_jsonb"] = mixed

        if kind == "element":
            for raw_name, source_src in elem.attrib.items():
                _, local_attr = split_expanded_name(raw_name)
                if local_attr != "src":
                    continue

                source_attribute_name = expanded_name_for_path(raw_name)
                attachment_id = make_attachment_id(
                    document_id,
                    node_id,
                    source_attribute_name,
                    source_src,
                )
                attachments.append(
                    {
                        "attachment_id": attachment_id,
                        "document_id": document_id,
                        "law_revision_id": law_revision_id,
                        "ref_node_id": node_id,
                        "source_file_id": None,
                        "source_attribute_name": source_attribute_name,
                        "source_src": source_src,
                        "resolved_locator": None,
                        "media_type": None,
                        "sha256": None,
                        "byte_size": None,
                        "availability_status": "unresolved",
                        "resolution_detail_jsonb": {},
                        "first_seen_run_id": ingestion_run_id,
                        "last_seen_run_id": ingestion_run_id,
                    }
                )

        return node_id

    root_path = f"/{_path_segment(root, 1)}"
    visit(root, None, root_path, 1, 1, 0)

    document = dict(base_document)
    document.update(
        {
            "root_tag_name": root_local,
            "root_namespace_uri": root_uri,
            "root_attributes_jsonb": attributes_for_storage(root.attrib),
            "parse_status": (
                "succeeded-with-warnings"
                if issues or schema_validation_status in {"invalid", "error"}
                else "succeeded"
            ),
            "node_count": len(nodes),
            "attachment_reference_count": len(attachments),
        }
    )
    return ParsedXmlDocument(document, nodes, attachments, issues)


def build_source_file_member_row(
    *,
    member_source_file_id: str,
    container_source_file_id: str,
    member_path: str,
    member_ordinal: int | None = None,
    compressed_size: int | None = None,
    uncompressed_size: int | None = None,
    crc32: int | str | None = None,
) -> dict[str, Any]:
    """zipfile.ZipInfo等の値をsource_file_member行へ変換する補助関数。"""

    if crc32 is None:
        crc32_text = None
    elif isinstance(crc32, int):
        crc32_text = f"{crc32 & 0xFFFFFFFF:08x}"
    else:
        crc32_text = crc32.lower()

    return {
        "member_source_file_id": member_source_file_id,
        "container_source_file_id": container_source_file_id,
        "member_path": member_path,
        "member_ordinal": member_ordinal,
        "compressed_size": compressed_size,
        "uncompressed_size": uncompressed_size,
        "crc32": crc32_text,
    }
