from concurrent.futures import ThreadPoolExecutor

import pytest

from pdf_translator.db import (
    capture_reserved,
    get_user,
    grant_credits,
    list_ledger,
    release_reserved,
    reserve_credits,
)


def test_retry_release_cannot_mint_credits():
    grant_credits(99, 10, 'seed')
    assert reserve_credits(99, 3, 'job')
    assert reserve_credits(99, 3, 'job')
    release_reserved(99, 3, 'job')
    release_reserved(99, 3, 'job')
    assert get_user(99)['available_credits'] == 10
    assert get_user(99)['reserved_credits'] == 0
    assert len(list_ledger(99)) == 3
    with pytest.raises(ValueError, match='settled differently'):
        capture_reserved(99, 3, 'job')


def test_concurrent_reservations_cannot_overspend():
    grant_credits(99, 5, 'seed')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda job: reserve_credits(99, 4, job), ['a', 'b']))
    assert sorted(results) == [False, True]
    assert get_user(99)['available_credits'] == 1
    assert get_user(99)['reserved_credits'] == 4


def test_wrong_settlement_amount_does_not_touch_balance():
    grant_credits(99, 10, 'seed')
    reserve_credits(99, 3, 'job')
    with pytest.raises(ValueError, match='match a durable reservation'):
        release_reserved(99, 4, 'job')
    assert get_user(99)['available_credits'] == 7
    assert get_user(99)['reserved_credits'] == 3


def test_only_one_worker_can_claim_queued_job():
    from pdf_translator.db import claim_job, create_job, get_job
    create_job(job_id='claim', source_lang='tr', target_lang='en', owner_telegram_user_id=99, input_path='unused.pdf', pages_total=1, credits_reserved=0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim_job, ['claim', 'claim']))
    assert sorted(results) == [False, True]
    assert get_job('claim')['status'] == 'running'
    assert not claim_job('claim')


def test_job_settlement_rolls_back_with_status_write_failure():
    from pdf_translator.db import _conn, claim_job, create_job, finish_job, get_job
    grant_credits(99, 10, 'seed')
    reserve_credits(99, 3, 'atomic')
    create_job(job_id='atomic', source_lang='tr', target_lang='en', owner_telegram_user_id=99, input_path='unused.pdf', pages_total=3, credits_reserved=3)
    assert claim_job('atomic')
    with _conn() as conn:
        conn.execute("CREATE TRIGGER reject_completed BEFORE UPDATE OF status ON jobs WHEN NEW.status='completed' BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    with pytest.raises(Exception, match='injected failure'):
        finish_job('atomic', output_path='result.pdf')
    assert get_user(99)['reserved_credits'] == 3
    assert get_job('atomic')['status'] == 'running'
    assert not any(row['type'] == 'capture' for row in list_ledger(99))
    with _conn() as conn:
        conn.execute('DROP TRIGGER reject_completed')
    finish_job('atomic', output_path='result.pdf')
    finish_job('atomic', output_path='result.pdf')
    assert get_job('atomic')['status'] == 'completed'
    assert get_job('atomic')['credits_charged'] == 3
    assert get_user(99)['reserved_credits'] == 0
    assert sum(row['type'] == 'capture' for row in list_ledger(99)) == 1


def test_zero_credit_legacy_job_can_finalize():
    from pdf_translator.db import claim_job, create_job, finish_job, get_job
    create_job(job_id='legacy', source_lang='tr', target_lang='en', owner_telegram_user_id=99, input_path='unused.pdf', pages_total=0, credits_reserved=0)
    assert claim_job('legacy')
    finish_job('legacy', error='legacy has no input', failure_code='PDF_ERROR')
    assert get_job('legacy')['status'] == 'failed'
    assert get_job('legacy')['credits_charged'] == 0


def test_offline_recovery_refunds_once_and_preserves_queued_jobs():
    from pdf_translator.db import (
        claim_job,
        create_job,
        get_job,
        recover_interrupted_jobs,
    )
    grant_credits(99, 10, 'seed')
    for job in ['interrupted', 'queued']:
        reserve_credits(99, 3, job)
        create_job(job_id=job, source_lang='tr', target_lang='en', owner_telegram_user_id=99, input_path='unused.pdf', pages_total=3, credits_reserved=3)
    assert claim_job('interrupted')
    assert recover_interrupted_jobs() == ['interrupted']
    assert recover_interrupted_jobs() == []
    assert get_job('interrupted')['failure_reason_code'] == 'WORKER_INTERRUPTED'
    assert get_job('queued')['status'] == 'queued'
    assert get_user(99)['available_credits'] == 7
    assert get_user(99)['reserved_credits'] == 3


def test_offline_recovery_handles_crash_before_job_creation():
    from pdf_translator.db import recover_interrupted_jobs
    grant_credits(99, 10, 'seed')
    assert reserve_credits(99, 3, 'no-job-record')
    assert recover_interrupted_jobs() == ['no-job-record']
    assert recover_interrupted_jobs() == []
    assert get_user(99)['available_credits'] == 10
    assert get_user(99)['reserved_credits'] == 0
    assert sum(r['type'] == 'release' for r in list_ledger(99)) == 1
