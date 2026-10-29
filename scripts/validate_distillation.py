"""Resumable real-model acceptance. Only the PRD's original demo book is sent."""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / '.runtime/distillation-validation.json'
OUTPUT = ROOT / 'docs/validation/distillation-live.json'
METHODS = ['book-to-skill', 'cangjie', 'sansheng', 'bolan', 'book-reader']


def main():
    state = json.loads(CHECKPOINT.read_text()) if CHECKPOINT.exists() else {'run_id': str(uuid.uuid4()), 'results': {}}
    def save():
        content = json.dumps(state, ensure_ascii=False, indent=2) + '\n'
        CHECKPOINT.parent.mkdir(exist_ok=True); CHECKPOINT.write_text(content); OUTPUT.write_text(content)
    with httpx.Client(base_url='http://127.0.0.1:8765/api/v1', timeout=60, trust_env=False) as client:
        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        sources = request('POST', '/demo/load', json={})['sources']
        source = next(s for s in sources if '小步验证' in s['title'])
        detail = request('GET', '/sources/'+source['id'])
        chapters = [c['id'] for c in detail['chapters'] if c['data'].get('selected', True) and c['data'].get('text','').strip() and len(c['data']['text']) > 60]
        state.update(source_id=source['id'], chapter_ids=chapters,
            purpose='用相同原创演示资料核对五种书内蒸馏方法，重点保留执行条件、反例和边界。')
        active = source['data'].get('active_distillation_id')
        save()
        for method in METHODS:
            item = state['results'].get(method, {})
            if item.get('status') == 'completed':
                continue
            if item.get('job_id'):
                job = request('GET', '/jobs/'+item['job_id'])
                if job['status'] in {'partial','waiting_error','interrupted','failed'}:
                    if '--resume' not in sys.argv:
                        raise RuntimeError(f"{method} needs explicit resume: {job['id']} {job['status']}")
                    job = request('POST', '/jobs/'+job['id']+'/retry', json={})
            else:
                job = request('POST', '/sources/'+source['id']+'/distill', json={
                    'method_id': method, 'chapter_ids': chapters,
                    'prompt': '提炼小步实验的判断与执行方法，保留停止条件、失败案例和适用边界。',
                    'model_profile_id': 'deepseek-default', 'request_id': f"distillation-validation:{state['run_id']}:{method}"})
                state['results'][method] = {'job_id': job['id'], 'status': job['status']}; save()
            print(method+': '+job['id'], flush=True)
            stage = None
            deadline = time.monotonic()+2400
            while time.monotonic() < deadline:
                job = request('GET', '/jobs/'+job['id'])
                if stage != job['data'].get('stage'):
                    stage = job['data'].get('stage'); print('  '+job['status']+' '+str(stage), flush=True)
                if job['status'] in {'completed','partial','waiting_error','interrupted','failed','cancelled'}:
                    break
                time.sleep(2)
            state['results'][method] = {'job_id':job['id'], 'status':job['status'], 'error':job['data'].get('error'),
                'calls':[{ 'step':key, 'status':step.get('status'), 'usage':step.get('usage'), 'profile':step.get('profile_id'),
                          'profile_version':step.get('profile_version'), 'model':step.get('result',{}).get('model')}
                         for key,step in job['data'].get('steps',{}).items()]}
            if job['status'] == 'completed':
                rid = job['data']['result']['distillation_id']
                result = request('GET', '/distillations/'+rid)
                checks=[]
                for card in result['cards']:
                    for ref in card['data'].get('references', []):
                        evidence = request('GET','/evidence',params={k:ref[k] for k in ['source_id','source_version','chapter_id','chapter_version','start','end']})
                        checks.append(evidence.get('quote') == ref['quote'])
                assert all(checks), 'Citation mismatch'
                assert result['data']['method_id'] == method
                assert result['data']['external_sources']['status'] == 'not_executed'
                assert request('GET','/sources/'+source['id'])['source']['data'].get('active_distillation_id') == active
                state['results'][method].update(distillation_id=rid, cards=len(result['cards']), verified_references=len(checks),
                    extensions=[e['stage_id'] for e in result['data']['extensions']], quality=result['data']['quality'],
                    citations_exact=all(checks), active_result_unchanged=True)
            save()
            if job['status'] != 'completed':
                raise RuntimeError(f"{method}: {job['status']}; check job; no automatic paid replay")
        state['status']='passed'; save(); print('All five real-model methods passed',flush=True)


if __name__ == '__main__':
    main()
