from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from app.domain.models import Document, HtmlDoc

from .base import HtmlConverter


class HtmlPassthroughConverter(HtmlConverter):
    """이미 HTML인 입력을 변환 없이 통과시킨다.

    easyPT가 hwp5html 등으로 미리 변환한 HTML(표 구조 포함)을 받을 때 사용.
    표(<table>)·단락(<p>)만 카운트하고 out_dir로 복사.
    """

    async def convert(self, document: Document, out_dir: Path) -> HtmlDoc:
        out_dir.mkdir(parents=True, exist_ok=True)
        html = Path(document.src_path).read_text(encoding="utf-8", errors="ignore")
        out = out_dir / f"{document.id}.html"
        out.write_text(html, encoding="utf-8")
        soup = BeautifulSoup(html, "lxml")
        return HtmlDoc(
            doc_id=document.id,
            html_path=out,
            table_count=len(soup.find_all("table")),
            paragraph_count=len(soup.find_all("p")),
        )
