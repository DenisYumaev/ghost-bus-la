"""The uploader: moves spool files and closed fetch-log hours to S3 (spec 2.4, steps 4 and 5).

Each round:
1. Janitor: delete local files that are safely in S3 and older than 48 hours.
2. Upload pending snapshots, oldest first, with conditional writes. 200 and 412 both mean "in
   S3", so the file gets its `.uploaded` marker. Any other error stops the round: S3 is
   probably down, and the files stay in the spool for the next round.
3. Upload fetch-log hours whose current content isn't in S3 yet.

Before uploading, each snapshot's bytes are checked against the hash in its name, so a corrupt
file (bad disk, a bug) is set aside instead of being stored under a key that lies about it.

`run()` repeats this every `interval_s`, backs off after failures, and makes a final pass at
shutdown that also uploads the still-open fetch-log hour.
"""

import gzip
import hashlib
import random
import threading
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass

from botocore.exceptions import BotoCoreError, ClientError

from ghostbus_ingest.backoff import backoff_delay
from ghostbus_ingest.fetch_log import FetchLog
from ghostbus_ingest.s3 import S3Client, conditional_put
from ghostbus_ingest.spool import Spool, parse_spool_name, spool_object_key

KEEP_LOCAL_S = 48 * 3600
UPLOAD_ERRORS = (ClientError, BotoCoreError, RuntimeError)


@dataclass
class UploadReport:
    written: int = 0
    duplicate: int = 0
    failed: int = 0
    corrupt: int = 0
    error: str | None = None


def _matches_name(path_name_sha16: str, gz_bytes: bytes) -> bool:
    try:
        data = gzip.decompress(gz_bytes)
    except (OSError, EOFError, zlib.error):
        return False
    return hashlib.sha256(data).hexdigest()[:16] == path_name_sha16


class Uploader:
    def __init__(self, spool: Spool, fetch_log: FetchLog, s3: S3Client, bucket: str) -> None:
        self.spool = spool
        self.fetch_log = fetch_log
        self.s3 = s3
        self.bucket = bucket

    def upload_once(self, now: float, final: bool = False) -> UploadReport:
        report = UploadReport()
        self.spool.clean_uploaded(now, KEEP_LOCAL_S)
        self.fetch_log.clean_uploaded(now, KEEP_LOCAL_S)

        for path in self.spool.pending():
            key = spool_object_key(path)
            body = path.read_bytes()
            _cut, sha16 = parse_spool_name(path)
            if not _matches_name(sha16, body):
                self.spool.set_aside_corrupt(path)
                self.fetch_log.record_upload(now, path.name, None, "corrupt", "hash mismatch")
                report.corrupt += 1
                continue
            try:
                outcome = conditional_put(
                    self.s3, self.bucket, key, body, content_type="application/gzip"
                )
            except UPLOAD_ERRORS as error:
                self.fetch_log.record_upload(now, path.name, key, "error", repr(error))
                report.failed += 1
                report.error = repr(error)
                return report
            self.spool.mark_uploaded(path)  # only after S3 confirmed: 200 or 412
            self.fetch_log.record_upload(now, path.name, key, outcome)
            if outcome == "written":
                report.written += 1
            else:
                report.duplicate += 1

        for log_path, data, sha in self.fetch_log.files_to_upload(now, final):
            key = FetchLog.object_key_for(log_path, sha)
            try:
                conditional_put(
                    self.s3, self.bucket, key, data, content_type="application/x-ndjson"
                )
            except UPLOAD_ERRORS as error:
                report.failed += 1
                report.error = repr(error)
                return report
            FetchLog.mark_uploaded(log_path, sha)
        return report

    def run(
        self,
        stop: threading.Event,
        interval_s: float = 10.0,
        clock: Callable[[], float] = time.time,
        wait: Callable[[float], object] | None = None,
        rand: Callable[[], float] = random.random,
    ) -> None:
        """Upload every `interval_s` until `stop` is set; back off while S3 is failing."""
        sleep = wait if wait is not None else stop.wait
        failures = 0
        while not stop.is_set():
            report = self.upload_once(clock())
            failures = failures + 1 if report.failed else 0
            sleep(backoff_delay(failures - 1, rand=rand) if failures else interval_s)
        self.upload_once(clock(), final=True)
