#!/usr/bin/env python3
import signal
import time


def ignore_term(signum, frame):
    print("ignoring SIGTERM", flush=True)


signal.signal(signal.SIGTERM, ignore_term)
print("worker alive", flush=True)
while True:
    time.sleep(0.1)

