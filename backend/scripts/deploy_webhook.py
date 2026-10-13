"""Isolated GitHub release receiver: authenticate bytes, queue a trigger, nothing else."""

from collections import deque
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import tempfile
import time


MAX_BODY = 1024 * 1024
REPOSITORY = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}\Z")
TAG = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+-main\.[0-9]+\.[0-9a-f]{12}\Z")
DELIVERY = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")


def log(outcome, **fields):
    print(json.dumps({"service": "deploy-webhook", "outcome": outcome, **fields}), flush=True)


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class Receiver:
    def __init__(self, repository, secret, directory, limit=60, clock=time.monotonic):
        if not REPOSITORY.fullmatch(repository) or repository.split("/")[1] in {".", ".."}:
            raise ValueError("SPACEWORKS_REPOSITORY must be a GitHub owner/repository")
        self.repository = repository.casefold()
        self.secret = secret.encode("utf-8")
        self.directory = Path(directory)
        self.limit = limit
        self.clock = clock
        self.requests = deque()

    def rate_allowed(self):
        now = self.clock()
        while self.requests and self.requests[0] <= now - 60:
            self.requests.popleft()
        if len(self.requests) >= self.limit:
            return False
        self.requests.append(now)
        return True

    def receive(self, headers, body):
        if not self.secret:
            return 403, "disabled"
        signature = headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(self.secret, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature.encode("utf-8"), expected.encode("ascii")):
            return 403, "signature_refused"
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError, RecursionError):
            return 400, "invalid_json"
        if not isinstance(payload, dict):
            return 400, "invalid_json"
        if headers.get("X-GitHub-Event") == "ping":
            return 200, "ping"
        repository = payload.get("repository")
        release = payload.get("release")
        if (headers.get("X-GitHub-Event") != "release"
                or payload.get("action") != "published"
                or not isinstance(repository, dict)
                or not isinstance(repository.get("full_name"), str)
                or repository["full_name"].casefold() != self.repository
                or not isinstance(release, dict)
                or release.get("draft") is not False
                or release.get("prerelease") is not False
                or not isinstance(release.get("tag_name"), str)
                or not TAG.fullmatch(release["tag_name"])):
            return 202, "ignored"
        delivery = headers.get("X-GitHub-Delivery", "")
        if not DELIVERY.fullmatch(delivery):
            return 400, "invalid_delivery"
        delivery = delivery.lower()
        return self.enqueue(release["tag_name"], delivery)

    def enqueue(self, tag, delivery):
        receipts = self.directory / ".deliveries"
        receipt = receipts / delivery
        temporary = None
        try:
            receipts.mkdir(mode=0o770, exist_ok=True)
            if receipt.exists():
                return 202, "duplicate"
            # The single-threaded server serializes receipt/queue publication. Never use
            # any payload field as a command, path, image or deployment version input.
            descriptor, temporary = tempfile.mkstemp(prefix=".request-", dir=self.directory)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                os.fchmod(stream.fileno(), 0o660)
                json.dump({"tag": tag, "delivery": delivery}, stream)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / f"{delivery}.json")
            temporary = None
            sync_directory(self.directory)
            # Receipts survive host consumption and receiver restart. They contain no
            # payload and are outside the host path unit's *.json watch.
            with receipt.open("x", encoding="ascii") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            sync_directory(receipts)
        except OSError:
            return 503, "queue_unavailable"
        finally:
            if temporary:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    pass  # Hidden temporary files never trigger the host consumer.
        return 202, "queued"


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.0 closes after each response. Read timeout bounds slow/incomplete bodies;
    # a single-threaded listener bounds memory/concurrency as well as rate.
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        pass  # Never log request lines, signatures or arbitrary payload text.

    def respond(self, status, outcome):
        log(outcome, status=status)
        self.send_response(status)
        self.send_header("Content-Length", "0")
        if status == 429:
            self.send_header("Retry-After", "60")
        self.end_headers()

    def do_POST(self):
        receiver = self.server.receiver
        if not receiver.secret:
            return self.respond(403, "disabled")
        if not receiver.rate_allowed():
            return self.respond(429, "rate_limited")
        if self.path != "/hooks/deploy":
            return self.respond(404, "unknown_path")
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return self.respond(415, "content_type_refused")
        lengths = self.headers.get_all("Content-Length", [])
        if (self.headers.get("Transfer-Encoding") or len(lengths) != 1
                or not re.fullmatch(r"[0-9]{1,10}", lengths[0])):
            return self.respond(400, "invalid_length")
        length = int(lengths[0])
        if length > MAX_BODY:
            return self.respond(413, "body_too_large")
        try:
            body = self.rfile.read(length)
        except (TimeoutError, OSError):
            return self.respond(408, "body_timeout")
        if len(body) != length:
            return self.respond(400, "incomplete_body")
        status, outcome = receiver.receive(self.headers, body)
        self.respond(status, outcome)

    def do_GET(self):
        self.respond(403 if not self.server.receiver.secret else 405, "method_refused")

    do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_GET


def main():
    receiver = Receiver(
        os.environ.get("SPACEWORKS_REPOSITORY", "SpaceWorks-HQ/SpaceWorks"),
        os.environ.get("SPACEWORKS_DEPLOY_WEBHOOK_SECRET", ""),
        "/deploy-requests",
    )
    server = HTTPServer(("0.0.0.0", 8081), Handler)
    server.receiver = receiver
    log("listening", enabled=bool(receiver.secret))
    server.serve_forever()


if __name__ == "__main__":
    main()
