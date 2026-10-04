"""Explicit offline recovery. Stop API/background workers before invoking."""
import argparse

from pdf_translator.db import init_db, recover_interrupted_jobs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers-stopped', action='store_true', help='Operator confirms all workers are stopped')
    args = parser.parse_args()
    if not args.workers_stopped:
        parser.error('Stop all workers, then explicitly pass --workers-stopped')
    init_db()
    print({'recovered_job_ids': recover_interrupted_jobs()})


if __name__ == '__main__':
    main()
