from unittest.mock import Mock

from pdf_translator import worker


def test_terminal_job_is_not_retranslated_or_rebilled(monkeypatch):
    for status in ['completed', 'failed']:
        monkeypatch.setattr(worker, 'get_job', lambda job_id: {'status': status})
        translate = Mock()
        capture = Mock()
        monkeypatch.setattr(worker, 'translate_pdf', translate)
        monkeypatch.setattr(worker, 'finish_job', capture)
        worker.process_job('terminal')
        translate.assert_not_called()
        capture.assert_not_called()


def test_deadline_stops_at_page_boundary_and_releases_credit(monkeypatch):
    monkeypatch.setattr(worker, 'get_job', lambda job_id: {'status': 'queued', 'input_path': 'in.pdf', 'source_lang': 'tr', 'target_lang': 'en', 'owner_telegram_user_id': 999, 'credits_reserved': 2})
    monkeypatch.setattr(worker.settings, 'job_timeout_sec', 10)
    monkeypatch.setattr(worker, 'claim_job', lambda job_id: True)
    ticks = iter([100, 111])
    monkeypatch.setattr(worker.time, 'monotonic', lambda: next(ticks))
    status = Mock()
    release = Mock()
    capture = Mock()
    monkeypatch.setattr(worker, 'update_job_status', status)
    monkeypatch.setattr(worker, 'finish_job', release)
    def translate(**kwargs):
        kwargs['on_page_done'](1, 'text')
        raise AssertionError('Deadline should abort before another page')
    monkeypatch.setattr(worker, 'translate_pdf', translate)
    worker.process_job('timed')
    capture.assert_not_called()
    release.assert_called_once()
    assert release.call_args.args == ('timed',)
    assert release.call_args.kwargs['failure_code'] == 'JOB_TIMEOUT'
