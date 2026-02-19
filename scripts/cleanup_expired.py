from pathlib import Path

from pdf_translator.db import list_expired_jobs, mark_job_cleaned


def main() -> None:
    jobs = list_expired_jobs()
    cleaned = 0
    for job in jobs:
        for p in [job.get("input_path"), job.get("output_path")]:
            if p and Path(p).exists():
                try:
                    Path(p).unlink()
                except OSError:
                    pass
        mark_job_cleaned(job["job_id"])
        cleaned += 1

    print(f"Expired jobs cleaned: {cleaned}")


if __name__ == "__main__":
    main()
