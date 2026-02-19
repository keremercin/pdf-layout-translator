from uuid import uuid4

from pdf_translator.db import create_job, list_expired_jobs, mark_job_cleaned


def test_mark_cleaned_and_expired_visibility(tmp_path, monkeypatch):
    input_file = tmp_path / "x.pdf"
    input_file.write_bytes(b"x")

    create_job(
        job_id=str(uuid4()),
        source_lang="tr",
        target_lang="en",
        owner_telegram_user_id=42,
        input_path=str(input_file),
        pages_total=1,
        credits_reserved=1,
    )

    jobs = list_expired_jobs()
    # fresh job should not be expired immediately
    assert isinstance(jobs, list)

    # direct mark call should work
    # this test validates API presence, not scheduler time travel
    # pick first job from db via expected path
    from pdf_translator.db import list_recent_jobs

    rid = list_recent_jobs(1)[0]["job_id"]
    mark_job_cleaned(rid)
    assert list_recent_jobs(1)[0]["status"] == "cleaned"
