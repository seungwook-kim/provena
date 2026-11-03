"""PDF 파싱: Docling(OCR 끔) 출력을 기존 IR 요소 형식으로 바꾸고, 같은 청킹 규칙(800/120)으로 청크를 만든다.

python -m backend.rag.ingest.pdf collect --from <받아 둔 PDF 폴더>   (sha256·git blob id 대조 후 data/pdf/ 로 복사)
python -m backend.rag.ingest.pdf run                                 (Docling 변환 → data/parsed/pdf_ir.jsonl → data/chunks/pdf_chunks.jsonl)
python -m backend.rag.ingest.pdf run --reuse-docling                 (저장된 Docling JSON을 쓰고 변환은 건너뜀. Docling 없이도 돈다)

Spec: docs/specs/parse.md "PDF" 절. 선택 근거: 조사/PDF 파서 비교 측정 (2026-11-03).
Docling은 운영 이미지에 넣지 않는다(backend/requirements-ingest-pdf.txt). 그래서 이 모듈의 Docling 가져오기는 convert() 안에서만 한다.
이 모듈의 나머지 함수는 파이썬 표준 라이브러리와 chunk.py만 쓰고, Docling JSON(dict)만 입력으로 받는다.
결과는 평가 색인과 분리해 data/parsed/pdf_ir.jsonl, data/chunks/pdf_chunks.jsonl 에 쓴다(chunks.jsonl·manifest는 건드리지 않음).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path

from backend.rag.ingest import chunk as chunking
from backend.rag.ingest.handbook import PINNED_COMMIT, SITE, rule_seq, sha256

PDF_REPO_RAW = f"https://gitlab.com/gitlab-com/content-sites/handbook/-/raw/{PINNED_COMMIT}/"
PDF_VERSION_DATE = "2026-10-27"      # 고정 커밋 날짜. 파일을 마지막으로 고친 날은 모르므로 version_date_before=True 로 둔다
# 고정 커밋 129243bc 의 static/pdfs 아래 파일 중 이 목록에 있는 것만 처리한다. sha256·git blob id 는 GitLab API 응답 머리글
# (X-Gitlab-Content-Sha256, X-Gitlab-Blob-Id)과 받아 둔 파일 양쪽에서 확인한 값이다(2026-11-03). 파일을 더하려면 항목을 추가한다.
# 같은 글자를 가진 파일(customer_dpa_05_01_26.pdf 와 customer_dpa_5_1_26.pdf)은 하나만 둔다.
SOURCES = [
    {"path": "static/pdfs/customer-experience/customer-success-vision/gitlab-customer-journey.pdf",
     "sha256": "75869d729d94bb4501d0be802ed14a5d8a13dba3597f4b072788dca666a02625",
     "git_blob": "0a8a07d7345999da1aaa1ddfb5f3cce30b39a278", "bytes": 87109},
    {"path": "static/pdfs/customer-experience/customer-success-vision/gitlab_customer_success_capabilities_roadmap.pdf",
     "sha256": "8af6bb94f41003d84936937fd0501715e9dcdcd7674abdd4ff3b70ea271bf17f",
     "git_blob": "49bf49125411dc87e323718107fecdb019e76692", "bytes": 90164},
    {"path": "static/pdfs/customer-experience/industry-ai-governance-question-bank.pdf",
     "sha256": "c242b6e70439a58ff6aa4e78083b18bd5b55a283162dd157b9a18b5ba74e3ca5",
     "git_blob": "4b255fe34a70aa8a0e2fb43a8cf760858bc4380c", "bytes": 273320},
    {"path": "static/pdfs/legal/privacy/customer_dpa_5_1_26.pdf",
     "sha256": "6a50187be3d1c02b42765e33b08f18d2ee3f3a289dc28de1c4bda70c89f3dd2e",
     "git_blob": "151e0ce6b9f0c98f82c7ccd113ce2a7fe9f49ca2", "bytes": 211288},
    {"path": "static/pdfs/marketing/brand-and-product-marketing/product-and-solution-marketing/roles-personas/assets/Incident_Response_Flow_SecOpsEngineer.pdf",
     "sha256": "25e4b3f7c1c0efa4e21625317e2164a8d3dc5bde757028efea2030a467f367e7",
     "git_blob": "774cd7e510188e287cbe3ed6f1804e8dc9519b55", "bytes": 54036},
    {"path": "static/pdfs/marketing/brand-and-product-marketing/product-and-solution-marketing/roles-personas/assets/Persona_SecOpsEngineer.pdf",
     "sha256": "5b10d3807b1dd989f9aacba0d5cdb19f2a5f3e065bc2f7b780b0410b6e6005b6",
     "git_blob": "89b7cbf555817a88232b994e689a20b9e6a946f5", "bytes": 137350},
    {"path": "static/pdfs/press/git-cheat-sheet.pdf",
     "sha256": "8ad44445094b4f6c2576935e13bd4215405795a4a6712c7c04dd9696d727569a",
     "git_blob": "65f37212c8cb3f7ae1ee6e7f3bf9486ece659bf7", "bytes": 290368},
]
CONFIG = "structure-s800-o120-h"      # chunk.py 기본값과 같은 설정 이름

# ── 제목 규칙 (문서별 하드코딩 없음. 모양만 본다) ──
SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "per", "the", "to",
               "under", "via", "vs", "with"}
MAX_TITLE_WORDS = 12
ABBREVIATIONS = {"inc", "corp", "ltd", "co", "llc", "no", "vs", "dr", "mr", "ms", "st", "e.g", "i.e", "etc", "u.s", "u.k"}
NUM_MARKER = re.compile(r"^\d+[.)]$")                     # 목록 표지 "13." 같은 숫자 표지
LEAD_MARK = re.compile(r"^(?:\d+[.)]?|[A-Za-z][.)])\s+")      # 제목 글자 맨 앞의 "10. ", "01 ", "A. "
SENTENCE_END = re.compile(r"^(.{1,150}?[^\s.])\.(?:\s+|$)", re.S)
APPENDIX = re.compile(r"^(exhibit|annex|appendix|schedule|attachment)\b", re.I)
TERMINAL = ".;:!?”\"'"
CONT_START = re.compile(r"^(?:\(?[ivxlcdm]+\)|\(?[a-z]\)|\d+[.)])\s", re.I)     # 새 항목 표지로 시작하면 이어진 글이 아님


def row_text(header: list[str], cells: list[str]) -> str:
    """parse.py 의 row_text 와 같은 형식(표 행 한 줄). parse.py 는 Markdown 라이브러리가 필요해 여기 사본을 둔다."""
    return " | ".join(f"{h}: {v}" if h else v for h, v in zip(header + [""] * len(cells), cells) if v)


def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# ── 수집 ──
def verify_pdf(data: bytes, src: dict) -> None:
    if len(data) != src["bytes"] or sha256(data) != src["sha256"] or git_blob_id(data) != src["git_blob"]:
        raise ValueError(f"{src['path']}: 고정 커밋 원본과 다름 (크기 {len(data)}, sha256 {sha256(data)[:12]})")


def collect(source_dir: Path | None, out: Path, collected_at: str, download: bool = False) -> dict:
    """받아 둔 PDF(source_dir/파일명)를 고정 커밋 원본과 대조해 out 으로 복사한다. download=True 면 고정 커밋 원본을 받는다."""
    files = []
    for src in SOURCES:
        rel = src["path"].removeprefix("static/pdfs/")
        if download:
            with urllib.request.urlopen(PDF_REPO_RAW + src["path"], timeout=60) as r:    # noqa: S310 (고정 https 주소)
                data = r.read()
        else:
            data = (source_dir / Path(rel).name).read_bytes()
        verify_pdf(data, src)
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        files.append({"path": src["path"], "file": rel, "sha256": src["sha256"], "git_blob": src["git_blob"],
                      "bytes": src["bytes"], "source_url": SITE + src["path"].removeprefix("static/")})
    manifest = {"commit": PINNED_COMMIT, "version_date": PDF_VERSION_DATE, "collected_at": collected_at, "files": files}
    (out / "pdf_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
                                           newline="\n")
    return manifest


# ── Docling 변환 (이 함수만 Docling 을 가져온다) ──
def convert(pdf: Path, artifacts: Path | None = None) -> dict:
    """OCR 끔, 표 구조 켬(TableFormer accurate), CPU. Docling 문서를 dict(JSON)로 돌려준다."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import AcceleratorOptions, PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    extra = {"artifacts_path": str(artifacts)} if artifacts else {}
    opts = PdfPipelineOptions(do_ocr=False, do_table_structure=True,
                              accelerator_options=AcceleratorOptions(device="cpu"), **extra)
    conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    return conv.convert(str(pdf)).document.export_to_dict()


# ── Docling JSON → 요소 ──
def split_title(body: str) -> tuple[str, str] | None:
    """글 맨 앞이 '제목 모양 구절 + 마침표 + 본문'이면 (구절, 본문). 제목 모양이 아니면 None.
    제목 모양: 12단어 이하, 작은 낱말(of, the, and …)을 뺀 모든 낱말이 대문자·숫자로 시작, 쉼표·쌍점으로 끝나지 않음."""
    body = body.strip()
    m = SENTENCE_END.match(body)
    phrase, rest = (m.group(1), body[m.end():].strip()) if m else (body, "")
    if not m and len(body.split()) > MAX_TITLE_WORDS:
        return None
    words = phrase.split()
    if not 1 <= len(words) <= MAX_TITLE_WORDS or phrase[-1] in ",;:":
        return None
    if rest and words[-1].lower() in ABBREVIATIONS:       # "GitLab Inc. Q3 …" 의 Inc. 에서 끊지 않는다
        return None
    for w in words:
        w = w.lstrip("(\"'“‘[")
        if w.lower() in SMALL_WORDS or not w:
            continue
        if not (w[0].isupper() or w[0].isdigit()):
            return None
    return phrase, rest


def _ref(doc: dict, node: dict) -> tuple[str, dict]:
    kind, _, idx = node["$ref"].lstrip("#/").partition("/")
    return kind, doc[kind][int(idx)]


def walk(doc: dict, node: dict | None = None, ctx: float | None = None):
    """본문 트리를 문서 순서대로 (종류, 객체, 숫자 표지 최상위 왼쪽 좌표) 로 낸다. 쪽 머리글·바닥글(furniture)은 호출한 쪽이 거른다."""
    node = node or doc["body"]
    for child in node.get("children", []):
        kind, obj = _ref(doc, child)
        if kind == "groups":
            sub = ctx
            if obj.get("label") == "list":
                lefts = [o["prov"][0]["bbox"]["l"] for k, o in (_ref(doc, c) for c in obj.get("children", []))
                         if k == "texts" and o.get("prov") and NUM_MARKER.match(o.get("marker") or "")]
                sub = min(lefts) if lefts else None
            yield from walk(doc, obj, sub)
        else:
            yield kind, obj, ctx
            if obj.get("children"):
                yield from walk(doc, obj, ctx)


def _prov(obj: dict) -> tuple[int, list[float]]:
    p = obj["prov"][0]
    b = p["bbox"]
    return p["page_no"], [round(b["l"], 1), round(b["b"], 1), round(b["r"], 1), round(b["t"], 1)]


def table_rows(table: dict) -> tuple[list[str], list[list[str]]]:
    """Docling 표 → (머리 칸, 본문 행들). 병합 칸은 왼쪽 위 칸에만 글자를 두고 나머지는 빈 칸. 열 제목 행은 칸마다 이어 붙인다."""
    data = table["data"]
    grid = [[""] * data["num_cols"] for _ in range(data["num_rows"])]
    head_rows = set()
    for c in data["table_cells"]:
        r, k = c["start_row_offset_idx"], c["start_col_offset_idx"]
        grid[r][k] = (c.get("text") or "").strip()
        if c.get("column_header"):
            head_rows.add(r)
    n_head = 0
    while n_head in head_rows:
        n_head += 1
    header = [" ".join(grid[r][k] for r in range(n_head) if grid[r][k]) for k in range(data["num_cols"])] if n_head else []
    rows = [row for row in grid[n_head:] if any(row)]
    return header, rows


def reorder_single_column_pages(items: list[dict]) -> int:
    """Docling 이 쪽 위쪽 제목을 그 쪽 본문 뒤로 보내는 경우가 있어(시험에서 부록 첫 쪽의 제목 하나가 본문 뒤로 밀림), 한 단짜리 쪽만 위에서 아래로 다시 세운다.
    한 쪽에서 세로로 겹치면서 가로로 떨어진 요소 쌍이 하나라도 있으면 다단으로 보고 Docling 순서를 그대로 둔다.
    위치가 바뀐 요소 수를 돌려준다."""
    moved = 0
    pages = collections.OrderedDict()
    for i, e in enumerate(items):
        pages.setdefault(e["page"], []).append(i)
    for idx in pages.values():
        group = [items[i] for i in idx]
        multi = any(min(a["bbox"][3], b["bbox"][3]) - max(a["bbox"][1], b["bbox"][1]) > 3
                    and (a["bbox"][2] <= b["bbox"][0] or b["bbox"][2] <= a["bbox"][0])
                    for k, a in enumerate(group) for b in group[k + 1:])
        if multi:
            continue
        ordered = sorted(group, key=lambda e: -round(e["bbox"][3]))
        moved += sum(1 for old, new in zip(group, ordered) if old is not new)
        for i, e in zip(idx, ordered):
            items[i] = e
    return moved


def build_ir(doc: dict, rs: int, org: str) -> tuple[list[dict], dict]:
    """Docling JSON(dict) → 요소 목록. 요소 필드는 parse.py 와 같고, 줄 번호 대신 page, page_end, bbox 를 둔다.
    bbox 는 PDF 포인트 [왼쪽, 아래, 오른쪽, 위] (원점 왼쪽 아래)."""
    stats = collections.Counter()
    raw = []

    def heading(text: str, source: str, page: int, bbox: list[float]) -> dict:
        return {"kind": "heading", "source": source, "text": text, "page": page, "page_end": page, "bbox": bbox}

    for kind, obj, group_left in walk(doc):
        if kind == "tables":
            page, bbox = _prov(obj)
            header, rows = table_rows(obj)
            raw.append({"kind": "table", "header": header, "rows": rows, "page": page, "page_end": page, "bbox": bbox})
            continue
        if kind != "texts":
            stats["dropped_" + kind] += 1
            continue
        if obj.get("content_layer") != "body" or obj["label"] in ("page_header", "page_footer"):
            stats["dropped_page_furniture"] += 1
            continue
        text = (obj.get("text") or "").strip()
        if not text:
            continue
        label, marker = obj["label"], (obj.get("marker") or "").strip()
        page, bbox = _prov(obj)
        if label == "text" and re.fullmatch(r"\d{1,3}", text):
            stats["dropped_page_number"] += 1
            continue
        if label in ("title", "section_header"):
            lead = LEAD_MARK.match(text)
            head = text[lead.end():] if lead else text
            sp = split_title(head)
            if sp and sp[1]:
                raw.append(heading((text[:lead.end()] if lead else "") + sp[0], "native", page, bbox))
                raw.append({"kind": "paragraph", "text": sp[1], "page": page, "page_end": page, "bbox": bbox})
                stats["heading_split_from_sentence"] += 1
            else:
                raw.append(heading(text.rstrip(".") if lead else text, "native", page, bbox))
            continue
        if label == "list_item":
            eligible = NUM_MARKER.match(marker) and group_left is not None and \
                obj["prov"][0]["bbox"]["l"] <= group_left + 6          # 같은 목록에서 가장 왼쪽 숫자 표지 = 조항 단계
            sp = split_title(text) if eligible else None
            if sp:
                raw.append(heading(f"{marker} {sp[0]}", "list", page, bbox))
                if sp[1]:
                    raw.append({"kind": "paragraph", "text": sp[1], "page": page, "page_end": page, "bbox": bbox})
                stats["heading_from_list_item"] += 1
            else:
                raw.append({"kind": "list_item", "text": f"{marker} {text}".strip(), "page": page, "page_end": page,
                            "bbox": bbox, "marker": bool(marker)})
            continue
        raw.append({"kind": "code" if label == "code" else "paragraph", "text": text, "page": page, "page_end": page,
                    "bbox": bbox, "marker": False})

    # 쪽 경계에서 끊긴 글 잇기: 표지 없는 문단/목록 항목이 바로 앞 쪽에서 끝난 문장 없는 글 뒤에 오면 앞 요소에 붙인다
    merged = []
    for e in raw:
        prev = merged[-1] if merged else None
        if (prev and e["kind"] in ("paragraph", "list_item") and prev["kind"] in ("paragraph", "list_item")
                and not e.get("marker") and e["page"] == prev["page_end"] + 1
                and prev["text"][-1] not in TERMINAL and not CONT_START.match(e["text"])):
            prev["text"] += " " + e["text"]
            prev["page_end"] = e["page_end"]
            stats["merged_page_break"] += 1
            continue
        merged.append(e)

    stats["reordered_items"] = reorder_single_column_pages(merged)
    seen_heading, in_appendix = False, False
    for e in merged:                 # 제목 수준: 문서 첫 제목 = 1, 부록(Exhibit 등) 제목 = 2, 부록 안의 제목 = 3, 그 밖 = 2
        if e["kind"] != "heading":
            continue
        if not seen_heading and e["source"] == "native" and e["page"] == 1:
            e["level"] = 1
        elif APPENDIX.match(e["text"]):
            e["level"], in_appendix = 2, True
        else:
            e["level"] = 3 if in_appendix else 2
        seen_heading = True

    elements, stack, last_head, table_n = [], [], None, 0
    for e in merged:
        if e["kind"] == "heading":
            while stack and stack[-1][0] >= e["level"]:
                stack.pop()
            parent = stack[-1][2] if stack else None
        else:
            parent = last_head
        path = [t for _, t, _ in stack] + ([e["text"]] if e["kind"] == "heading" else [])

        def add(kind: str, text: str, **extra) -> dict:
            el = {"element_id": f"{rs}-{len(elements):04d}", "rule_seq": rs, "org": org, "kind": kind,
                  "heading_path": list(path), "parent_id": parent, "order": len(elements), "line_start": None,
                  "line_end": None, "text": text, "links": [], "review": None, "page": e["page"],
                  "page_end": e["page_end"], "bbox": e["bbox"], **extra}
            elements.append(el)
            return el

        if e["kind"] == "heading":
            el = add("heading", e["text"], level=e["level"])
            stack.append((e["level"], e["text"], el["element_id"]))
            last_head = el["element_id"]
        elif e["kind"] == "table":
            table_n += 1
            table_id = f"{rs}-t{table_n}"
            for i, row in enumerate(e["rows"]):
                add("table_row", row_text(e["header"], row), table_id=table_id, row=i, header=e["header"], cells=row,
                    private_cells=[])
            stats["tables"] += 1
        else:
            add(e["kind"], e["text"])
    stats.update({"elements": len(elements)})
    return elements, dict(stats)


# ── 청킹 ──
def pdf_chunks(page: dict, elements: list[dict]) -> tuple[list[dict], list[str]]:
    """chunk.py 의 구조 청킹을 그대로 쓰고(800/120), 쪽은 source_url 의 #page=N 에 넣는다(Chunk 계약 칸을 늘리지 않음)."""
    chunks = chunking.chunk_structure(page, elements, 800, 120, True, CONFIG)
    missing = chunking.covered(elements, chunks)
    by_id = {e["element_id"]: e for e in elements}
    for c in chunks:
        pages = sorted({p for eid in c["element_ids"] for p in range(by_id[eid]["page"], by_id[eid]["page_end"] + 1)})
        c["pages"] = pages
        c["source_url"] = f"{page['source_url']}#page={pages[0]}"
    return chunks, missing


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def run(pdf_dir: Path, parsed: Path, chunks_dir: Path, reuse_docling: bool = False, artifacts: Path | None = None) -> dict:
    manifest = json.loads((pdf_dir / "pdf_manifest.json").read_text(encoding="utf-8"))
    all_elements, all_chunks, docs, missing_all = [], [], [], []
    for f in manifest["files"]:
        pdf = pdf_dir / f["file"]
        verify_pdf(pdf.read_bytes(), next(s for s in SOURCES if s["path"] == f["path"]))
        cache = parsed / "pdf_docling" / (pdf.stem + ".docling.json")
        if reuse_docling and cache.exists():
            doc = json.loads(cache.read_text(encoding="utf-8"))
        else:
            doc = convert(pdf, artifacts)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8", newline="\n")
        org = f["path"].split("/")[2]
        rs = rule_seq(f["path"])
        elements, stats = build_ir(doc, rs, org)
        title = next((e["text"] for e in elements if e["kind"] == "heading" and e["level"] == 1), pdf.stem)
        page = {"rule_seq": rs, "org": org, "title": title, "version_id": manifest["commit"][:12],
                "version_date": manifest["version_date"], "version_date_before": True,
                "fetched_at": manifest["collected_at"], "source_url": f["source_url"]}
        chunks, missing = pdf_chunks(page, elements)
        all_elements += elements
        all_chunks += chunks
        missing_all += missing
        docs.append({"path": f["path"], "rule_seq": rs, "org": org, "title": title, "pages": len(doc["pages"]),
                     "docling": {"schema": doc.get("schema_name"), "version": doc.get("version")},
                     "elements": stats, "chunks": len(chunks)})
    write_jsonl(parsed / "pdf_ir.jsonl", all_elements)
    for c in all_chunks:
        c.pop("_body", None)
    write_jsonl(chunks_dir / "pdf_chunks.jsonl", all_chunks)
    report = {"config": CONFIG, "commit": manifest["commit"], "documents": docs, "elements": len(all_elements),
              "elements_by_kind": dict(collections.Counter(e["kind"] for e in all_elements)),
              "chunks": len(all_chunks), "g3_unique_body_sha256": len({c["body_sha256"] for c in all_chunks}),
              "missing_elements": len(missing_all), "missing_ids": missing_all[:20]}
    (parsed / "pdf_parse_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                  encoding="utf-8", newline="\n")
    return report


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--from", dest="source", type=Path, help="받아 둔 PDF 폴더(파일 이름으로 찾는다)")
    c.add_argument("--download", action="store_true", help="고정 커밋 원본을 직접 받는다(기본: 받아 둔 파일 사용)")
    c.add_argument("--collected-at", required=True, help="YYYY-MM-DD, 파일을 받은 날")
    c.add_argument("--out", type=Path, default=Path("data/pdf"))
    r = sub.add_parser("run")
    r.add_argument("--pdf", type=Path, default=Path("data/pdf"))
    r.add_argument("--parsed", type=Path, default=Path("data/parsed"))
    r.add_argument("--chunks", type=Path, default=Path("data/chunks"))
    r.add_argument("--reuse-docling", action="store_true")
    r.add_argument("--artifacts", type=Path, help="Docling 모델 폴더(없으면 Docling 기본 위치)")
    a = ap.parse_args()
    if a.cmd == "collect":
        if not a.download and not a.source:
            ap.error("--from 또는 --download 가 필요하다")
        m = collect(a.source, a.out, a.collected_at, a.download)
        print(f"{len(m['files'])}개 대조 통과 (고정 커밋 {m['commit'][:12]})")
        return
    rep = run(a.pdf, a.parsed, a.chunks, a.reuse_docling, a.artifacts)
    print(f"요소 {rep['elements']}개 {rep['elements_by_kind']}, 청크 {rep['chunks']}개, 빠진 요소 {rep['missing_elements']}")
    if rep["missing_elements"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
