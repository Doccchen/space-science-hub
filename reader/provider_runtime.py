"""Read the shared applied configuration, without exposing credentials to public APIs."""
import asyncio

from backend import literature_config as config, management_store as store
from .discovery import SearchService


class Runtime:
    def __init__(self,client,settings):
        self.client,self.settings=client,settings
        self.signature=None
        self.warning=None
        self.service=SearchService(client,wanfang_key=settings.wanfang_key)
        self.managed=None

    def sync(self):
        try:
            values=config.runtime_settings()
            if values is None:
                self.warning=None
                return
            signature=tuple((name,row['version']) for name,row in values.items())
            if signature!=self.signature:
                self.service=SearchService(self.client,managed=values)
                self.signature=signature
            self.managed=values
            self.warning=None
            config.acknowledge(values)
        except (store.ManagementError,ValueError,KeyError,TypeError,OSError):
            # Once management is authoritative, a lost DB/key never revives
            # stale environment credentials or previously enabled integrations.
            self.service=SearchService(self.client)
            self.signature=None
            self.warning='文献 API 配置暂不可用，暂仅使用基础检索来源。'
            try:config.acknowledge_failure()
            except (store.ManagementError,OSError):pass

    async def loop(self):
        while True:
            self.sync()
            await asyncio.sleep(2)
