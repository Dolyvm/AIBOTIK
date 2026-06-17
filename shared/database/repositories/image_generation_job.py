"""Repository for chat image generation jobs."""
from datetime import datetime

from sqlalchemy import select, update

from shared.models import ImageGenerationJob
from .base import BaseRepository


ACTIVE_IMAGE_JOB_STATUSES = ("queued", "running")
TERMINAL_IMAGE_JOB_STATUSES = ("succeeded", "failed", "canceled")


class ImageGenerationJobRepository(BaseRepository[ImageGenerationJob]):
    model = ImageGenerationJob

    async def get_active_for_chat(self, chat_id: int) -> ImageGenerationJob | None:
        result = await self.session.execute(
            select(ImageGenerationJob)
            .where(ImageGenerationJob.chat_id == chat_id)
            .where(ImageGenerationJob.status.in_(ACTIVE_IMAGE_JOB_STATUSES))
            .order_by(ImageGenerationJob.created_at.desc(), ImageGenerationJob.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_chat_and_id(self, chat_id: int, job_id: int) -> ImageGenerationJob | None:
        result = await self.session.execute(
            select(ImageGenerationJob).where(
                ImageGenerationJob.id == job_id,
                ImageGenerationJob.chat_id == chat_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_job(
        self,
        user_id: int,
        chat_id: int,
        request_payload: dict,
    ) -> ImageGenerationJob:
        job = ImageGenerationJob(
            user_id=user_id,
            chat_id=chat_id,
            status="queued",
            request_payload=request_payload,
        )
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def set_arq_job_id(self, job_id: int, arq_job_id: str | None) -> ImageGenerationJob | None:
        job = await self.get_by_id(job_id)
        if not job:
            return None
        job.arq_job_id = arq_job_id
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def mark_running(self, job_id: int) -> ImageGenerationJob | None:
        job = await self.get_by_id(job_id)
        if not job or job.status != "queued":
            return job
        job.status = "running"
        job.started_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def mark_succeeded(self, job_id: int, image_id: int) -> ImageGenerationJob | None:
        job = await self.get_by_id(job_id)
        if not job:
            return None
        job.status = "succeeded"
        job.image_id = image_id
        job.error_code = None
        job.error_message = None
        now = datetime.utcnow()
        job.completed_at = now
        job.updated_at = now
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def mark_failed(
        self,
        job_id: int,
        error_code: str,
        error_message: str,
    ) -> ImageGenerationJob | None:
        job = await self.get_by_id(job_id)
        if not job:
            return None
        job.status = "failed"
        job.error_code = error_code[:100]
        job.error_message = error_message[:500]
        now = datetime.utcnow()
        job.completed_at = now
        job.updated_at = now
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def mark_canceled(
        self,
        job_id: int,
        error_message: str = "Генерация отменена",
    ) -> ImageGenerationJob | None:
        job = await self.get_by_id(job_id)
        if not job:
            return None
        job.status = "canceled"
        job.error_code = "canceled"
        job.error_message = error_message[:500]
        now = datetime.utcnow()
        job.completed_at = now
        job.updated_at = now
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def record_runpod_job(
        self,
        job_id: int,
        *,
        provider: str,
        runpod_job_id: str,
        endpoint_id: str | None = None,
        status_payload: dict | None = None,
    ) -> ImageGenerationJob | None:
        job = await self.get_by_id(job_id)
        if not job:
            return None
        payload = dict(job.request_payload or {})
        runpod_jobs = list(payload.get("runpod_jobs") or [])
        existing = next(
            (
                item
                for item in runpod_jobs
                if isinstance(item, dict)
                and item.get("provider") == provider
                and item.get("job_id") == runpod_job_id
            ),
            None,
        )
        item = existing if existing is not None else {}
        item.update(
            {
                "provider": provider,
                "job_id": runpod_job_id,
                "endpoint_id": endpoint_id,
                "created_at": datetime.utcnow().isoformat(),
            }
        )
        if status_payload:
            item["status"] = status_payload.get("status")
            item["delayTime"] = status_payload.get("delayTime")
            item["executionTime"] = status_payload.get("executionTime")
        if existing is None:
            runpod_jobs.append(item)
        payload["runpod_jobs"] = runpod_jobs
        job.request_payload = payload
        job.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def get_active_started_before(
        self,
        cutoff: datetime,
        *,
        limit: int = 50,
    ) -> list[ImageGenerationJob]:
        result = await self.session.execute(
            select(ImageGenerationJob)
            .where(ImageGenerationJob.status.in_(ACTIVE_IMAGE_JOB_STATUSES))
            .where(ImageGenerationJob.started_at.is_not(None))
            .where(ImageGenerationJob.started_at < cutoff)
            .order_by(ImageGenerationJob.started_at.asc(), ImageGenerationJob.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def cancel_active_for_chat(self, chat_id: int) -> int:
        result = await self.session.execute(
            update(ImageGenerationJob)
            .where(ImageGenerationJob.chat_id == chat_id)
            .where(ImageGenerationJob.status.in_(ACTIVE_IMAGE_JOB_STATUSES))
            .values(
                status="canceled",
                error_code="canceled",
                error_message="Генерация отменена",
                completed_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.commit()
        return result.rowcount or 0
