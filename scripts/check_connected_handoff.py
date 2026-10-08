#!/usr/bin/env python3
"""Model-free native repair -> accepted child -> validated final Op integration.

Uses only committed public builder inference fixtures. No provider/model call.
Run after bootstrap --install. Temporary candidate artifacts are cleaned up.
"""
import argparse
import importlib.util,json,sys
from pathlib import Path
from unittest.mock import patch
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--workspace',type=Path,default=Path(__file__).resolve().parents[2])
workspace=parser.parse_args().workspace.resolve()
sys.path.insert(0,str(workspace/'op-cog-builder/tests'))
import test_cycles
fixture=test_cycles.BuilderCycleTests();fixture.setUp()
try:
 spec=importlib.util.spec_from_file_location('design_handoff',workspace/'cog-op-designer/scripts/design_handoff.py')
 handoff=importlib.util.module_from_spec(spec);spec.loader.exec_module(handoff)
 contract=fixture.designed['contract']
 request={'goal':contract['purpose'],'success_criteria':[contract['acceptance_criteria'][0]['description']],'constraints':[],'catalog':[],'feedback':[]}
 proposal={'abstained':False,'classification':'proposed','reason':None,'goal':request['goal'],'assumptions':[],'questions':[],
  'criteria':[{'id':'length','description':request['success_criteria'][0]}],
  'artifacts':[{'id':'input','description':'Supplied notes','schema':contract['input_schema']},{'id':'output','description':'Character count','schema':contract['output_schema']}],
  'inputs':['input'],'outputs':['output'],
  'steps':[{'id':'count','purpose':contract['purpose'],'capability':'characters','inputs':['input'],'outputs':['output'],'criteria':['length'],
    'choice':{'kind':'new','cog_id':None,'catalog_fingerprint':None,'brief_id':'counter','rationale':'Build a pure character counter.'}}],
  'cog_briefs':[{'id':'counter','step_ids':['count'],'name':'cog-code-fixture','brief':contract['purpose'],'prohibits':contract['prohibits'],'cog_kind':'code'}],
  'review_points':['Accept the child contract and candidate.']}
 prepared=handoff.prepare(request,handoff.cog_core._envelope('ask',True,payload=proposal,binding={'source':'synthetic-connected-test'}))
 missing=prepared['missing_cogs'][0]
 original=test_cycles.op_cycle.start
 def start(package,path,**kwargs):
  value=json.loads(Path(path).read_text());value['build_origin']=missing['build_origin'];Path(path).write_text(json.dumps(value));return original(package,path,**kwargs)
 with patch.object(test_cycles.op_cycle,'start',side_effect=start):code,contract_pause=fixture.start()
 assert code==3,contract_pause
 code,candidate=fixture.resume(contract_pause,fixture.decide(contract_pause));assert code==3,candidate
 assert candidate['attempts']==2,candidate
 state=json.loads(Path(candidate['cycle']).read_text())
 first_track=json.loads((Path(state['phases'][0]['run_dir'])/'track.json').read_text())
 first_review=next(s for s in first_track['steps'] if s['id']=='review')
 assert json.loads(Path(first_review['envelope']).read_text())['payload']['classification']=='revise'
 pending=fixture.pending(candidate);decision_path=fixture.decide(candidate)
 code,accepted=fixture.resume(candidate,decision_path);assert code==0,accepted
 track=json.loads((Path(candidate['run_dir'])/'track.json').read_text())
 payloads={step['id']:json.loads(Path(step['envelope']).read_text())['payload'] for step in track['steps'] if step.get('envelope')}
 child={'pending':pending,'decision':json.loads(Path(decision_path).read_text()),'materialization':payloads['materialize'],'verification':payloads['verify'],'assessment':payloads['review'],'task':'run'}
 result=handoff.finalize(prepared,{missing['missing_cog_id']:child},{},{'id':'test/op-connected','version':'0.1.0','name':'Connected test'},workspace/'op-cog-builder/runs/connected-final',fixture.suite)
 assert result['op_spec']['steps'][0]['cog']['id']=='openteams/cog-code-fixture',result
 print('Native repair, accepted child and final Op validation passed')
finally:fixture.doCleanups()
