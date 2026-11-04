import os,json
from pathlib import Path
from urllib.parse import urlsplit
u=urlsplit(os.environ['POSTGRES_URL']);assert u.hostname=='127.0.0.1' and u.port==15458 and u.path=='/workspace_controller_p6_walk' and os.environ['WORKSPACE_RATE_DATABASE_URL']==os.environ['POSTGRES_URL'] and os.environ['WORKSPACE_OWNER']=='controller-p6' and os.environ['ANTHROPIC_API_KEY']=='local-preview-disabled'
import src
assert Path(src.__file__).resolve().is_relative_to(Path.cwd().resolve())
from src.tools.postgres_pool import get_pool,close_pool
from src.workspace.store import WorkspaceStore
s=WorkspaceStore(get_pool())
try:
 works=s.works('controller-p6');eds=s.editions('controller-p6');old=next(x for x in eds if x['id']=='eca0e2ffba5045369e85be5001fcbeea');assert len(works)==28 and old['work_ids'][0]=='arxiv:2611.99800' and len(old['work_ids'])==9
 profile=s.profile('controller-p6');new=s.edition('controller-p6',old['work_ids'],minutes=old['minutes'],revision=profile['revision'],work_versions=old['work_versions']);assert s.editions('controller-p6')[0]['id']==new['id'] and any(e==old for e in s.editions('controller-p6'));print(json.dumps({'edition':new['id'],'originalLongEditionPreserved':old['id'],'items':len(new['work_ids']),'works':len(works)}))
finally:close_pool()
