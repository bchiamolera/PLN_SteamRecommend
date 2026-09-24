"""Shared throttling and durable checkpoints for the Steam notebook."""

import json
import math
import logging
import os
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
import requests


class RequestGate:
    def __init__(self, interval=1.0):
        self.interval = interval
        self.next_request = 0.0
        self.lock = threading.Lock()

    def configure(self, interval):
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("Request interval must be finite and positive")
        with self.lock:
            self.interval = interval

    def acquire(self):
        while True:
            with self.lock:
                now = time.monotonic()
                delay = self.next_request - now
                if delay <= 0:
                    self.next_request = now + self.interval
                    return
            time.sleep(delay)

    def defer(self, seconds):
        with self.lock:
            self.next_request = max(self.next_request, time.monotonic() + seconds)


_gates = {}
_gates_lock = threading.Lock()


def gate_for(url):
    with _gates_lock:
        return _gates.setdefault(urlsplit(url).netloc, RequestGate())


def retry_delay(value, fallback):
    if value:
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                return max(0.0, (date - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
    return fallback


def steam_get(url, *, params=None, timeout=30, limiter=None, retries=5,
              intervalo=1.0, headers=None, cookies=None, session=None):
    if retries < 1:
        raise ValueError("retries must be at least 1")
    gate = gate_for(url)
    client = session if session is not None else requests
    for attempt in range(retries):
        gate.acquire()
        if limiter is not None:
            limiter.acquire()
        backoff = max(1.0, intervalo) * 5 * (2 ** attempt)
        try:
            response = client.get(url, params=params, timeout=timeout,
                                  headers=headers, cookies=cookies)
        except (requests.Timeout, requests.ConnectionError):
            gate.defer(backoff)
            if attempt == retries - 1:
                raise
            continue
        if response.status_code in (429, 500, 502, 503, 504):
            delay = retry_delay(response.headers.get("Retry-After"), backoff)
            logging.getLogger(__name__).warning(
                "HTTP %s from %s: shared cooldown %.1fs (attempt %s/%s)",
                response.status_code, urlsplit(url).netloc, delay, attempt + 1, retries,
            )
            gate.defer(delay)
            if attempt < retries - 1:
                response.close()
                continue
        response.raise_for_status()
        return response


def atomic_pickle(df, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    df.to_pickle(temporary, compression={'method': 'gzip', 'compresslevel': 1}, protocol=5)
    os.replace(temporary, path)


REVIEW_COLUMNS = ["appid", "game_name", "review_type", "voted_up", "review",
                  "timestamp_created", "votes_up", "votes_funny",
                  "weighted_vote_score", "playtime_forever"]


def load_review_checkpoint(path, quantity, resume):
    path = Path(path)
    if not resume or not path.exists():
        return [], set()
    try:
        df = pd.read_pickle(path)
    except pd.errors.EmptyDataError:
        df = pd.DataFrame(columns=REVIEW_COLUMNS)
    if not set(REVIEW_COLUMNS).issubset(df.columns):
        raise ValueError("Review pickle is missing required columns")
    # Legacy files have no completion ledger; infer only sufficiently full pairs.
    completed = {tuple(key) for key, count in df.groupby(["appid", "review_type"]).size().items()
                 if count >= quantity}
    ledger = path.with_suffix(path.suffix + ".state.json")
    if ledger.exists():
        state = json.loads(ledger.read_text(encoding="utf-8"))
        if state.get("quantity") == quantity:
            completed.update((int(appid), kind) for appid, kind in state["completed"])
    return df.to_dict("records"), completed


def save_review_checkpoint(rows, completed, path, quantity):
    # Write data before the ledger so completion never precedes saved results.
    atomic_pickle(pd.DataFrame(rows, columns=REVIEW_COLUMNS), path)
    ledger = Path(path).with_suffix(Path(path).suffix + ".state.json")
    temporary = ledger.with_name(ledger.name + ".tmp")
    temporary.write_text(json.dumps({"quantity": quantity,
                                    "completed": sorted(completed)}), encoding="utf-8")
    os.replace(temporary, ledger)
