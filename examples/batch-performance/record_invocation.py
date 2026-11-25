#!/usr/bin/env python3
"""Record crash-test analyzer starts and then replace this process with the original CLI."""
import json
import os
import sys


if sys.argv[1:] == ["-m", "analyzer.library", "investigate_batch_note"]:
    name = json.load(sys.stdin)["filename"]
    # The Java bridge redirects stdin from a regular file. Let the real CLI reread its original bytes.
    os.lseek(sys.stdin.fileno(), 0, os.SEEK_SET)
    fd = os.open(os.environ["BATCH_AUDIT_LOG"], os.O_APPEND | os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        os.write(fd, (name + "\n").encode())
    finally:
        os.close(fd)
python = os.environ["BATCH_PYTHON"]
os.execv(python, [python, *sys.argv[1:]])
