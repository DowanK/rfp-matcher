from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.api.deps import ContainerDep
from app.domain.models import Recommendation
from app.services.recommendation import RecommendationService

router = APIRouter(tags=["recommendations"])


class RecommendStartResponse(BaseModel):
    doc_id: str
    queued: bool


@router.post("/documents/{doc_id}/recommend", response_model=RecommendStartResponse)
async def start_recommendation(
    doc_id: str,
    background: BackgroundTasks,
    container: ContainerDep,
    force: bool = False,
) -> RecommendStartResponse:
    """AI 검토(매칭) 시작. force=True 면 이미 판정된 요건도 지우고 전량 재평가 —
    사람이 카드 삭제/병합/편집을 마친 뒤 FE의 'AI 검토 시작' 버튼이 쓰는 경로."""
    if doc_id not in container.repo.documents:
        raise HTTPException(404, f"document 없음: {doc_id}")
    reqs = await container.repo.list_requirements(doc_id)
    if not reqs:
        raise HTTPException(409, "추출된 요구사항 없음 — 먼저 업로드/추출 완료 필요")
    if force:
        await container.repo.clear_recommendations(doc_id)
    svc = RecommendationService(container)

    async def _runner() -> None:
        await svc.recommend_document(doc_id)

    background.add_task(_runner)
    return RecommendStartResponse(doc_id=doc_id, queued=True)


@router.get("/requirements/{req_id}/recommendation", response_model=Recommendation | None)
async def get_recommendation(req_id: str, container: ContainerDep) -> Recommendation | None:
    return await container.repo.get_recommendation(req_id)


# ── judge-only: 외부(easyPT)가 추출한 요구사항을 카탈로그로 판정만 (추출 스킵) ──
class JudgeReqItem(BaseModel):
    id: str
    code: str = ""
    name: str = ""
    detail: str = ""
    category: str = ""


class JudgeRequest(BaseModel):
    requirements: list[JudgeReqItem]


@router.post("/requirements/judge")
async def judge_requirements(body: JudgeRequest, container: ContainerDep) -> dict:
    """제공된 요구사항을 KT 카탈로그(BM25)+LLM으로 판정. matcher 추출 없이 판정만.

    공공 RFP처럼 easyPT가 요구사항을 뽑은 경우, 그 목록을 그대로 판정해
    ai_risk·ai_reason·matched_solutions·missing_tech·rubric을 붙인다.
    """
    from app.domain.models import Requirement
    from app.phase2.recommender.recommender import DEFAULT_BATCH_SIZE, RequirementRecommender

    if not body.requirements:
        return {"recommendations": []}
    reqs = [
        Requirement(
            id=r.id, doc_id="external", category=(r.category or "기타"),
            code=(r.code or r.id), name=(r.name or (r.detail[:60] if r.detail else r.id)),
            detail=(r.detail or r.name or ""),
        )
        for r in body.requirements
    ]
    recommender = RequirementRecommender(llm=container.llm, catalog=container.catalog_retriever)
    # batch_size 단위로 쪼개 호출 — 한 번에 전부 보내면 max_tokens가 vLLM 한계 초과(400).
    recs = []
    for i in range(0, len(reqs), DEFAULT_BATCH_SIZE):
        recs.extend(await recommender.recommend_batch(reqs[i:i + DEFAULT_BATCH_SIZE]))
    return {"recommendations": [r.model_dump(mode="json") for r in recs]}
