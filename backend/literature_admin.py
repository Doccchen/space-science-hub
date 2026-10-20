"""Private authenticated provider management; tests are explicit, bounded requests."""
import httpx
from fastapi import APIRouter,Depends,Request
from . import admin_auth, literature_config as config, management_store as store
from reader.wanfang import WanfangError
from reader.sciencedirect import ScienceDirectError

router=APIRouter(prefix='/api/literature-config',dependencies=[Depends(admin_auth.require)])


@router.get('')
def overview():return config.overview()


@router.post('/initialize')
def initialize(user=Depends(admin_auth.require)):
    return config.initialize(user['username'])


@router.post('/{provider}/drafts')
async def save(provider:str,request:Request,user=Depends(admin_auth.require)):
    return config.save(provider,await request.json(),user['username'])


@router.post('/{provider}/apply')
async def apply(provider:str,request:Request,user=Depends(admin_auth.require)):
    return config.apply(provider,await request.json(),user['username'])


@router.post('/{provider}/restore')
async def restore(provider:str,request:Request,user=Depends(admin_auth.require)):
    return config.apply(provider,await request.json(),user['username'],restore=True)


@router.post('/{provider}/test')
async def test(provider:str,request:Request,user=Depends(admin_auth.require)):
    config.required(provider);body=await request.json()
    if set(body)!={'version','fee_confirmed'} or body['fee_confirmed'] is not True or type(body['version']) is not int:
        raise store.ManagementError('请确认连接测试会请求供应商并可能消耗额度。',400)
    with store.connection() as db:row=config.version(db,provider,body['version'])
    values=config.public(row)['config'];secrets=config.decrypt(row)
    if not secrets['key'] or not values['authorized']:
        raise store.ManagementError('测试前请配置 Key 并确认有本站使用权限。',400)
    try:identity=config.reserve(provider,row['id'],values['daily_limit'],'test',user['username'])
    except config.ProviderLimit as error:raise store.ManagementError(str(error),429) from None
    result={'ok':False,'message':'连接测试未完成，请检查网络、权限或额度。'}
    try:
        async with httpx.AsyncClient(timeout=values['timeout'],follow_redirects=False) as client:
            if provider=='wanfang':
                from reader.wanfang import fetch
                rows=await fetch('栅格舵',client,secrets['key'],timeout=values['timeout'])
            else:
                from reader.sciencedirect import fetch
                rows=await fetch('grid fin',client,secrets['key'],secrets['insttoken'],timeout=values['timeout'])
        result={'ok':True,'count':len(rows),'message':'接口调用成功；测试不会自动应用草稿。'}
    except (WanfangError,ScienceDirectError) as error:
        result={'ok':False,'message':str(error)}
    except httpx.HTTPStatusError as error:
        result={'ok':False,'message':'来源限流或额度不足。' if error.response.status_code==429 else '来源请求失败，请核对 API 权限。'}
    except Exception:
        pass  # Never return upstream bodies, exception strings or credential-bearing headers.
    config.finish(identity,result)
    return result
