"""상품 근거 DB(자유 텍스트) → rfp-matcher CatalogEntry JSON 변환 + 카탈로그 교체.

~/Downloads/database/*.txt (KT AI 상품 카탈로그 서술)에서 LLM(vLLM)으로 매칭 단위
(솔루션/기술/기능)를 추출해 data/catalog/kt_solutions.json 으로 저장한다.
재기동(또는 lifespan 재빌드) 시 BM25 인덱스에 반영된다.

실행:
    cd ~/Projects/rfp-matcher/backend && source .venv/bin/activate
    PYTHONPATH=. python scripts/build_catalog_from_db.py
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.container import build_llm
from app.llm.base import Message

DB_DIR = Path.home() / "Downloads" / "database"
OUT = Path(__file__).resolve().parents[1].parent / "data" / "catalog" / "kt_solutions.json"

# 파일 → 대분류(상품 라인). 내용 헤더 기준.
FILE_MAJOR = {
    "model.txt": "K Model",
    "rag.txt": "K RAG",
    "agent.txt": "K Agent",
    "rai.txt": "K RAI",
    "kai_studio.txt": "KAI Studio",
    "intelligence-studio.txt": "Intelligence Studio",
    "cloud.txt": "K Cloud",
}


class _Entry(BaseModel):
    중분류: str = ""   # 솔루션·기술·제품명
    소분류: str = ""   # 구체 기능·역할
    설명: str = ""
    강점: list[str] = Field(default_factory=list)


class _Catalog(BaseModel):
    entries: list[_Entry] = Field(default_factory=list)


def _slug(*parts: str) -> str:
    s = "-".join(p for p in parts if p).lower()
    s = re.sub(r"[^0-9a-z가-힣]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def _chunks(text: str, size: int = 7000) -> list[str]:
    """문단(빈 줄) 경계로 ~size자씩 분할 — 큰 파일(kai_studio 96KB) 대응."""
    out: list[str] = []
    cur = ""
    for para in text.split("\n\n"):
        if cur and len(cur) + len(para) > size:
            out.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        out.append(cur)
    return out


_PROMPT = """다음은 KT의 '{major}' AI 상품 카탈로그 설명이다.
영업 제안에서 RFP 요구사항과 매칭할 수 있는 **개별 솔루션/기술/기능 단위**를 모두 추출하라.

반드시 아래 JSON 형태로만 출력하라. entries 배열에 항목을 여러 개 채워라(빈 배열 금지):
{{"entries": [
  {{"중분류": "DocuSee", "소분류": "문서 OCR", "설명": "문서 내 텍스트를 추출해 디지털 텍스트로 변환", "강점": ["인쇄본 인식", "고정확도"]}},
  {{"중분류": "DocuSee", "소분류": "표 구조 인식", "설명": "복잡한 표 구조를 데이터 형태로 변환", "강점": ["복잡표 인식"]}}
]}}

- 중분류: 솔루션·기술·제품명 (예: DocuSee, 믿:음 K 2.0 Mini, IntelliSearch)
- 소분류: 구체 기능·역할 (예: 문서 OCR, 경량 LLM, 하이브리드 검색)
- 설명: 1~2문장으로 무엇을 하는지
- 강점: 핵심 강점 키워드 2~5개
규칙: RFP 요건과 매칭되도록 충분히 잘게. 같은 제품의 다른 기능은 별도 항목. 본문에 있는 내용만.

본문:
{body}"""


async def main() -> None:
    settings = get_settings()
    llm = build_llm(settings)
    print(f"LLM: {type(llm).__name__} (provider={settings.llm_provider}, model={settings.llm_model_openai})")
    all_entries: list[dict] = []
    for fn, major in FILE_MAJOR.items():
        path = DB_DIR / fn
        if not path.exists():
            print(f"  [skip] {fn} 없음")
            continue
        text = path.read_text(encoding="utf-8")
        parts = _chunks(text)
        n0 = len(all_entries)
        for i, ch in enumerate(parts):
            try:
                cat = await llm.structured_output(
                    [Message(role="user", content=_PROMPT.format(major=major, body=ch))],
                    _Catalog, max_tokens=4000,
                )
            except Exception as e:  # noqa: BLE001
                print(f"  [{fn}] chunk{i+1}/{len(parts)} 실패: {str(e)[:140]}")
                continue
            for e in cat.entries:
                mid = (e.중분류 or "").strip()
                sub = (e.소분류 or "").strip()
                if not mid:
                    continue
                all_entries.append({
                    "id": _slug(major, mid, sub),
                    "대분류": major, "중분류": mid, "소분류": sub,
                    "솔루션명": f"{major} · {mid}",
                    "설명": (e.설명 or "").strip(),
                    "강점": [s.strip() for s in e.강점 if s.strip()],
                    "한계": [], "레퍼런스": [],
                })
            print(f"  [{fn}] chunk{i+1}/{len(parts)}: +{len(cat.entries)}")
        print(f"  └ {fn} → {len(all_entries)-n0}건 (누적 {len(all_entries)})")

    # id 중복 제거(뒤 항목 우선)
    by_id = {e["id"]: e for e in all_entries if e["id"]}
    final = list(by_id.values())

    # 안전 가드 — 0건이면 기존 카탈로그 덮어쓰지 않음
    if not final:
        print("\n[중단] 추출 0건 — 기존 카탈로그 유지(덮어쓰기 안 함). 프롬프트/LLM 점검 필요.")
        return
    if OUT.exists():
        OUT.with_suffix(".json.bak").write_text(OUT.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"\n기존 카탈로그 백업 → {OUT.name}.bak")
    OUT.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"총 {len(final)} entries → {OUT}")
    print("→ rfp-matcher 재기동하면 BM25 인덱스에 반영됨.")


if __name__ == "__main__":
    asyncio.run(main())
