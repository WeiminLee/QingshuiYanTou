from __future__ import annotations
import httpx

class RemoteEvidenceService:
    def __init__(self, base_url: str, api_key: str, timeout: float = 120):
        self.base=base_url.rstrip('/'); self.headers={'X-API-Key':api_key}; self.timeout=timeout
    async def _post(self,path,payload):
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r=await c.post(self.base+path,json=payload,headers=self.headers); r.raise_for_status(); return r.json()
    async def claim_next_job(self, job_type='combined', worker_id=''):
        d=await self._post('/api/v1/knowledge/evidence/jobs/claim',{'worker_id':worker_id,'limit':1,'job_types':[job_type]}); return (d.get('jobs') or [None])[0]
    async def get_evidence(self,evidence_id):
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r=await c.get(self.base+'/api/v1/knowledge/evidence/'+evidence_id,headers=self.headers); return r.json() if r.is_success else None
    async def mark_job_done(self,job_id,result): return await self._post('/api/v1/knowledge/evidence/jobs/%s/success'%job_id,{'worker_id':'remote','result_summary':result})
    async def mark_job_failed(self,job_id,error): return await self._post('/api/v1/knowledge/evidence/jobs/%s/failure'%job_id,{'worker_id':'remote','error':error})
    async def mark_job_skipped(self,job_id,reason): return await self.mark_job_failed(job_id,'skipped: '+reason)
    async def heartbeat_job(self,job_id,worker_id): return True
