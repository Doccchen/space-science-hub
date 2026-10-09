from fastapi import APIRouter,Depends,Request
from . import admin_auth,news_limits

router = APIRouter(prefix='/api/news-agent-limits',dependencies=[Depends(admin_auth.require)])

@router.get('')
def overview(): return news_limits.overview()

@router.post('/drafts')
async def save(request:Request,user=Depends(admin_auth.require)):
    return news_limits.save(await request.json(),user['username'])

@router.post('/apply')
async def apply(request:Request,user=Depends(admin_auth.require)):
    return news_limits.apply(await request.json(),user['username'])
