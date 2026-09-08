"""easyPT vLLM 연동 스모크 테스트.

rfp-matcher의 OpenAIClient가 vLLM(OpenAI 호환)로 structured_output(json_object)을
성공하는지 검증한다. SSH 터널(:8001)이 올라온 뒤 실행:

    cd ~/Projects/rfp-matcher/backend && source .venv/bin/activate
    PYTHONPATH=. python scripts/vllm_smoke.py

연결 실패 → 터널 미가동. response_format/json_object 에러 → vLLM 미지원(OpenAIClient 패치 필요).
"""
import asyncio, sys
from pydantic import BaseModel
from app.core.config import get_settings
from app.core.container import build_llm
from app.llm.base import Message


class Toy(BaseModel):
    a: int
    b: int


async def main():
    s = get_settings()
    llm = build_llm(s)
    print(f"client={type(llm).__name__} base_url={s.openai_base_url} model={s.llm_model_openai}")
    msgs = [Message(role="user", content='Return a JSON object with exactly two keys named "a" and "b". Set "a" to 7 and "b" to 9. Output JSON only.')]
    try:
        out = await llm.structured_output(msgs, Toy, max_tokens=80)
        print("OK structured_output →", out.model_dump())
        print("RESULT: vLLM 왕복 + json_object 지원 확인")
    except Exception as e:
        print("FAIL:", type(e).__name__, str(e)[:300])
        em = str(e).lower()
        if "connect" in em or "refused" in em or "timeout" in em:
            print("DIAGNOSIS: 연결 실패 — SSH 터널(:8001) 미가동")
        elif "response_format" in em or "json_object" in em or "guided" in em:
            print("DIAGNOSIS: vLLM이 response_format=json_object 미지원 → OpenAIClient 패치 필요")
        else:
            print("DIAGNOSIS: 기타 — 위 메시지 확인")
        sys.exit(1)


asyncio.run(main())
