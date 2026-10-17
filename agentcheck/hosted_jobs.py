"""Durable workflow stages reuse the same candidate, judge and refinement logic."""
import asyncio
import logging

from vercel import workflow


logger = logging.getLogger(__name__)
wf = workflow.Workflows(sandbox_policy=workflow.SandboxPolicy(share_sandboxes=True))


def execute_stage(owner, session_id, job_id, stage, *, store=None, client=None):
    # Keep filesystem/network imports outside the deterministic workflow sandbox.
    from .hosted_store import HostedStudio
    from .studio import DemoClient

    studio = HostedStudio(owner, store=store, client=client)
    session = studio.get(session_id)
    job = session.get('host_job', {})
    if job.get('id') != job_id:
        raise ValueError('A newer operation replaced this workflow.')
    if stage in job.get('completed_stages', []):
        return session['state'] != 'error'
    client = DemoClient() if session['is_mock'] else studio.client
    logger.info('AgentCheck workflow stage %s session=%s', stage, session_id)
    try:
        if stage == 'refine':
            studio._refine(session, job['feedback'], client)
        elif stage == 'prepare':
            if not session['cases']:
                studio._plan(session, client)
            studio._initialize_scan(session, client)
        elif stage.startswith('case:'):
            index = int(stage.split(':')[1])
            recorded = {row['test_id'] for row in session['versions'][-1]['scan']['results']}
            if index < len(session['cases']) and session['cases'][index]['id'] not in recorded:
                studio._test_one(session, session['cases'][index], client)
        elif stage == 'complete':
            studio._complete_scan(session)
        else:
            raise ValueError('Unknown workflow stage.')
        job['completed_stages'].append(stage)
        studio._save(session)
        if stage == 'complete':
            studio.store.release(owner, session_id)
        return True
    except (ValueError, OSError, KeyError, TypeError) as error:
        session['state'] = 'error'
        session['workflow_error'] = str(error)
        if session['versions'][-1]['scan']['status'] == 'running':
            session['versions'][-1]['scan']['status'] = 'interrupted'
        studio._save(session)
        studio.store.release(owner, session_id)
        return False


@wf.step(max_retries=0)
async def run_stage(owner: str, session_id: str, job_id: str, stage: str) -> bool:
    # One candidate+judge per step: at most two 90-second provider calls.
    # Do not automatically retry model calls to obtain a preferred test outcome.
    return await asyncio.to_thread(execute_stage, owner, session_id, job_id, stage)


@wf.workflow
async def scan_workflow(owner: str, session_id: str, job_id: str, operation: str):
    if operation == 'refine':
        if not await run_stage(owner, session_id, job_id, 'refine'):
            return
    if not await run_stage(owner, session_id, job_id, 'prepare'):
        return
    for index in range(6):
        if not await run_stage(owner, session_id, job_id, f'case:{index}'):
            return
    await run_stage(owner, session_id, job_id, 'complete')
