"""Private, explicitly confirmed AI settings and test job endpoints."""
from fastapi import APIRouter, Depends, Request
from . import admin_auth, ai, ai_config

router = APIRouter(prefix='/api/ai-config', dependencies=[Depends(admin_auth.require)])


@router.get('')
def overview():
    return ai_config.overview()


@router.post('/drafts')
async def draft(request: Request, user=Depends(admin_auth.require)):
    return ai_config.save_draft(await request.json(), user['username'])


@router.post('/apply')
async def apply(request: Request, user=Depends(admin_auth.require)):
    return ai_config.apply(await request.json(), user['username'], ai.Settings.environment())


@router.post('/restore')
async def restore(request: Request, user=Depends(admin_auth.require)):
    return ai_config.apply(await request.json(), user['username'], ai.Settings.environment(), restore=True)


@router.post('/test', status_code=202)
async def test(request: Request, user=Depends(admin_auth.require)):
    return ai_config.queue_test(await request.json(), user['username'])
