"""Export/verify D5's prospective public-context packet, without provider access.

Run from the worktree root with ``python - < scripts/workspace-d5-packet.py``.
This is not an approval writer or a paid runner. Only isolated proposal projects
are written; public source material, historical receipts and owner data are read
without mutation. Rebuilding must use a new output path after any source change.
"""
import argparse
import hashlib
import gzip
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from psycopg_pool import ConnectionPool
from src.workspace.assistance import AssistanceInput, AssistanceService, CANDIDATE_MODEL, Checks, build_wire
from anthropic import transform_schema
from dataclasses import asdict
from src.workspace.grounding import EvidenceRef, ResearchClaim, ClaimKind, claim_input_digest
from src.workspace.assistance_contract import REVISION, digest
from src.workspace.context_schemas import ProjectData, ProjectWrite
from src.workspace.context_store import WorkspaceContext
from src.workspace.store import WorkspaceStore

ROOT = Path.cwd()
FILES = ['src/workspace/assistance.py', 'src/workspace/assistance_contract.py', 'src/workspace/grounding.py', 'src/workspace/executor.py', 'src/workspace/material.py', 'src/llm.py', 'src/llm_models.py', 'scripts/workspace-d5-packet.py', 'src/workspace/assistance_routes.py', 'src/workspace/admission.py', 'src/workspace/qualification_budget.py', 'src/workspace/qualification_accounting.py', 'src/workspace/provider_adapter.py', 'src/workspace/migrations/011_assistance_wire.sql', 'src/api/app.py', 'web/components/workspace/AssistancePanel.tsx', 'web/components/workspace/ReaderContent.tsx', 'web/lib/workspace/assistanceTypes.ts', 'web/contract/openapi.json']


def bindings():
    return {name: 'sha256:' + hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FILES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--export', type=Path)
    group.add_argument('--verify', type=Path)
    args = parser.parse_args()
    assert os.environ.get('ANTHROPIC_API_KEY') == 'local-preview-disabled', 'Disabled-key sentinel required'
    assert (ROOT / 'src/workspace/assistance.py').exists(), 'Run from worktree root'
    if args.verify:
        sealed = json.loads(gzip.decompress(args.verify.read_bytes()) if args.verify.suffix == '.gz' else args.verify.read_bytes())
        expected = sealed.pop('packet_digest')
        assert digest(sealed) == expected, 'Packet changed'
        assert sealed['code_bindings'] == bindings(), 'Code binding changed: export a new revision'
        assert sealed['approved'] is False and sealed['provider_contacts'] == 0
        for case in sealed['cases']:
            assert digest(case['sealed_request']) == case['sealed_digest']
            assert digest(case['candidate_wire']) == case['wire_digest']
        print(json.dumps({'verified': expected, 'provider_contacts': 0, 'approved': False}))
        return
    assert not args.export.exists(), 'Never overwrite a frozen packet'
    url = os.environ['D5_PACKET_POSTGRES_URL']
    parsed = urlsplit(url)
    assert parsed.hostname in ('127.0.0.1', 'localhost') and parsed.port == 15488 and parsed.path == '/workspace_d5_verify', 'Only isolated D5 verification DB allowed'
    owner = 'd5-proposal'
    with ConnectionPool(url, min_size=1, max_size=2) as pool:
        store = WorkspaceStore(pool)
        service = AssistanceService(store)
        with pool.connection() as conn:
            rows = conn.execute("SELECT DISTINCT ON (v.work_id) v.work_id,v.version_id,v.data->>'title' FROM workspace_versions v JOIN workspace_works w ON w.work_id=v.work_id WHERE w.visibility_owner IS NULL ORDER BY v.work_id,v.observed_at DESC,v.version_id DESC").fetchall()
        papers = []
        for work, version, title in rows:
            units = service.catalog(owner, work, version)['units']
            abstract = [u for u in units if u['reference']['scope'] == 'abstract']
            if units:
                papers.append((work, version, title, (abstract or units)[0]))
        assert len(papers) >= 12, 'At least twelve retained public abstracts required'
        react = next(p for p in papers if p[0] == 'arxiv:2210.03629')
        rag = next(p for p in papers if p[0] == 'arxiv:2310.11511')
        def named(prefix):
            return next(p for p in papers if p[2].startswith(prefix))
        learn_sources = [named(prefix) for prefix in ('KEEPER:', 'TraceSpec:', 'Can we trust LLMs', 'Density-Guided')]
        compare_sources = [[named(a), named(b)] for a,b in [('Agentic World Modeling', 'Beyond Plausible Prediction'), ('Language Models Show Conformity', 'Better Retrievers, Worse Labels'), ('Certified Behavioral Retention', 'Frozen in Time:')]]
        specs = [
            ('d5-dev-learn', 'development', 'learn', 'Explain the method and its prerequisites; identify what this abstract cannot establish.', [react]),
            ('d5-dev-compare', 'development', 'research', 'What evidence and evaluation limitations can these two sources establish?', [react, rag]),
        ]
        for i in range(4):
            specs.append((f'd5-val-learn-{i+1}', 'fresh_validation', 'learn', ['Explain the reported mechanism and prerequisites.', 'Which assumptions qualify the main result?', 'What would an implementer need that this abstract does not provide?', 'Distinguish measured results from proposed use.'][i], [learn_sources[i]]))
        for i in range(3):
            specs.append((f'd5-val-compare-{i+1}', 'fresh_validation', 'research', ['Compare the methods using separately cited facts; identify incompatible settings.', 'Look for conflicting findings, or abstain if these sources cannot establish a disagreement.', 'Compare assumptions and limitations without inventing a common evaluation.'][i], compare_sources[i]))
        specs.append(('d5-val-insufficient', 'fresh_validation', 'research', 'Does this evidence establish that the method will fit my unspecified hardware and be safe in production?', [learn_sources[3]]))
        cases = []
        for case_id, cohort, mode, question, chosen in specs:
            pid = None
            revision = None
            if mode == 'research':
                pid = 'project-' + hashlib.sha256(case_id.encode()).hexdigest()[:32]
                project = WorkspaceContext(store).write_project(owner, ProjectWrite(id=pid, revision=0, request_id='proposal-' + case_id, data=ProjectData(title='Proposed validation · ' + case_id, question=question, scope='Explicit selected public abstracts only', constraints='No private notes/history, no source expansion, no live execution')))
                revision = project['revision']
            units = [p[3] for p in chosen]
            value = AssistanceInput(mode=mode, work_id=chosen[0][0], version_id=chosen[0][1], material_ids=tuple(dict.fromkeys(u['reference']['material_id'] for u in units)), span_ids=tuple(dict.fromkeys(u['reference']['span_id'] for u in units)), unit_ids=tuple(u['id'] for u in units), follow_up=question, project_id=pid, project_revision=revision)
            preview = service.preview(owner, value)
            wire = preview.request['candidate_initial_wire']
            cases.append({'id':case_id,'cohort':cohort,'mode':mode,'question':question,'human_review':None,'input':value.model_dump(mode='json'),'sources':[{'title':p[2],**p[3]} for p in chosen], 'sealed_request':preview.request,'sealed_digest':digest(preview.request),'candidate_wire':wire,'wire_digest':digest(wire),'schemas':preview.request['response_schemas'],'approved_handle_enum':list(preview.request['units'])})
    probes = []
    with ConnectionPool(url, min_size=1, max_size=2) as pool:
        service = AssistanceService(WorkspaceStore(pool))
        for batch in range(4):
            selected_cases = [cases[2 + ((batch * 5 + i) % 7)] for i in range(5)]
            claims, inputs, refs = [], [], []
            for i, case in enumerate(selected_cases):
                ref = EvidenceRef(**next(iter(case['sealed_request']['units'].values())))
                text = [
                    'This evidence establishes a universal guarantee of safe production use in every setting.',
                    'This method always outperforms all alternatives on identical datasets and compute.',
                    'The result requires no assumptions, external tools or evaluation limitations.',
                    'The complete paper proves all implementation details and hardware requirements are known.',
                ][batch]
                claim = ResearchClaim('c' + str(i+1), text, ClaimKind.FACTUAL, (ref,), required_scope='full_text' if batch == 3 else ref.scope)
                with pool.connection() as conn:
                    materials = service.executor._sources(conn, owner, [ref.material_id])
                claims.append(asdict(claim)); refs.append(asdict(ref))
                inputs.append({'claim_id':claim.claim_id,'input_digest':claim_input_digest(claim, materials)})
            stage = {'phase':'check','role':'checker','sealed_request':{'schema_revision':REVISION,'private_context':False},'draft':{'claims':claims},'claim_inputs':inputs,'unscored_prose':{},'output_schema':transform_schema(Checks)}
            wire = build_wire(stage)
            probes.append({'id':f'd5-probe-{batch+1}','candidate_wire':wire,'wire_digest':digest(wire),'references':refs,'proposed_decisions':['unsupported_or_abstain']*5,'human_labels':[None]*5,'annotation_basis':'Machine-proposed adversarial cases, not independent human gold'})
    payload = {'revision':'d5-prospective-validation-v1','contract':REVISION,'application_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'historical_receipt_binding':json.loads((ROOT/'planning/14-explore-and-research-modes/evidence/backend/historical-accounting-preserved.json').read_text()),'approved':False,'provider_contacts':0,'code_bindings':bindings(),'model':CANDIDATE_MODEL,'historical':{'estimated_usd':'0.109967','workflow_usd':'0.094655','checker_usd':'0.015312','unknown_usd':'0','messages':9,'counts':15,'jobs':6,'held_out_completion':'0/9','replay':False},'new_limits':{'jobs':14,'messages':44,'token_counts':48,'initial_count_only':4,'concurrency':1,'repairs_per_workflow':1,'input_tokens_raw_max':20000,'input_tokens_measured_max':16000,'draft_output_tokens':4000,'checker_output_tokens':1800,'per_workflow_usd':'0.40','per_probe_batch_usd':'0.08','conservative_reservations_usd':'4.32','uncertainty_headroom_usd':'1.00','cumulative_ceiling_usd':'10.00'},'measurement_only_ids':['d5-dev-learn','d5-dev-compare','d5-val-compare-2','d5-val-insufficient'],'cases':cases,'checker_probes':probes,'checker_probe_plan':{'batches':4,'items_per_batch':5,'kinds':['unsupported meaning','missing qualification','misleading comparison','contradictory evidence','wrong version','unselected evidence','ambiguous quote','abstract-only overreach','truncation','extraction failure'],'human_labels':None},'stage_binding':'Draft wires are exact. Checks/repair/recheck are conditional templates bound to selected units, schemas and the preceding recorded output; they require actual paired counts before any Message. No precomputed checker input is claimed.','dispatch_supported':False,'dispatch_gap':'This batch exports candidate requests and exercises MockTransport only. A D5 qualification-only live adapter plus cumulative-ledger admission must pass offline gates and be sealed before a paid execution command exists. Legacy V8 runner must not be used with this packet.'}
    payload['packet_digest'] = digest(payload)
    args.export.parent.mkdir(parents=True, exist_ok=True)
    blob = (json.dumps(payload, ensure_ascii=False, indent=2)+'\n').encode()
    args.export.write_bytes(gzip.compress(blob, mtime=0) if args.export.suffix == '.gz' else blob)
    print(json.dumps({'packet':str(args.export),'digest':payload['packet_digest'],'cases':len(cases),'provider_contacts':0,'approved':False}))

if __name__ == '__main__':
    main()
