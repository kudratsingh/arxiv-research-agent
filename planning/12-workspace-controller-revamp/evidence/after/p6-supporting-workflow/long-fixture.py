import os,json,importlib.util
from pathlib import Path
from datetime import UTC,datetime
from urllib.parse import urlsplit
u=urlsplit(os.environ.get('POSTGRES_URL','')); owner=os.environ.get('WORKSPACE_OWNER'); db=u.path.lstrip('/')
allowed={'workspace_controller_p6_preview':('controller-p6-preview',38,9),'workspace_controller_p6_walk':('controller-p6',3,3)}
assert db in allowed and owner==allowed[db][0] and u.hostname=='127.0.0.1' and u.port==15458 and u.username=='workspace' and not u.query and not u.fragment
assert os.environ['WORKSPACE_RATE_DATABASE_URL']==os.environ['POSTGRES_URL'] and os.environ['ANTHROPIC_API_KEY']=='local-preview-disabled' and os.environ['USE_MOCK_DATA']=='true' and os.environ['WORKSPACE_SCHEDULE_APPROVED']=='false'
import src
assert Path(src.__file__).resolve().is_relative_to(Path.cwd().resolve())
from src.tools.postgres_pool import get_pool,close_pool
from src.workspace.store import WorkspaceStore
from src.workspace.schemas import ReadingWrite,ReadingData
from src.workspace.intake import HttpResponse,fetch_source
s=WorkspaceStore(get_pool())
try:
 old=s.works(owner); editions=s.editions(owner); assert len(old)==allowed[db][1] and len(editions[0]['work_ids'])==allowed[db][2]; prior=editions[0]; assert all(w['work_id']!='arxiv:2611.99800' for w in old)
 n=24 if db=='workspace_controller_p6_walk' else 0; rows=[('CI synthetic long abstract agent navigation study','Synthetic fixture author',('This synthetic fixture examines navigation and reading continuity in a local preview. It is generated solely for interface verification and makes no scientific claim. Each passage is intentionally long enough to test scrolling, paper transitions, and the exact return to a retained source. ' * 14))]+[(f'CI synthetic navigation filler agent {i}','Synthetic fixture author','Synthetic offline fixture for navigation; no scientific finding.') for i in range(n)]
 spec=importlib.util.spec_from_file_location('rich','planning/12-workspace-controller-revamp/tools/rich_seed.py');rich=importlib.util.module_from_spec(spec);spec.loader.exec_module(rich);now=datetime.fromisoformat(s.cutoff()).astimezone(UTC);body=rich.arxiv_rss('cs.LG',rows,now,800)
 def transport(url,headers):return HttpResponse(200,{'content-type':'application/rss+xml'},body,url)
 result=fetch_source('arxiv-cs-lg',{},now=now,transport=transport);assert len(result.items)==len(rows)
 with s.pool.connection() as conn:
  for item in result.items:s._put_item(conn,item)
 long=result.items[0];s.write_reading(owner,ReadingWrite(work_id=long['work_id'],revision=0,request_id='p6-long-synthetic-save',data=ReadingData(status='saved',version_id=long['version_id'],anchor='abstract:0')))
 chosen=(prior['work_ids']+[x['work_id'] for x in result.items[1:]])[:8];assert len(chosen)==8 and len(set(chosen))==8
 edition=s.edition(owner,[long['work_id']]+chosen,minutes=prior['minutes'],revision=prior['profile_revision']); after=s.works(owner); all_editions=s.editions(owner)
 assert len(after)==len(old)+len(rows) and len(edition['work_ids'])==9 and all_editions[0]['id']==edition['id'] and any(e==prior for e in all_editions)
 print(json.dumps({'database':db,'principal':owner,'works':len(after),'newWorkId':long['work_id'],'newVersionId':long['version_id'],'abstractLength':len(long['abstract']),'newEdition':edition['id'],'oldEditionPreserved':prior['id'],'editionItems':len(edition['work_ids']),'saved':True,'fillerCount':n,'sourceRequests':0,'providerCalls':0,'srcFile':str(Path(src.__file__).resolve())}))
finally:close_pool()
