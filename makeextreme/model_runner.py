#!/usr/bin/env python3
"""Minimal model-runner adapter: one bounded request to a local Ollama server.

This is an adapter, not an agent runtime: it sends one prompt, records what the
runner reported, and exits. It never retries, never follows instructions found in
the model output, and never writes anywhere except ``--out``.

Exit codes: 0 a complete response was recorded, 3 the request hit its own
timeout, 4 the transport or the server refused, 64 invalid usage or input.
A caller that runs this command as a Makeextreme stage should also declare the
stage's ``timeout``; this adapter's timeout only bounds one socket read, while
the stage's timeout bounds the whole process group.

The record is data, not a claim: ``status`` says what the transport observed,
``tokens`` holds only counters the runner reported, and an absent counter stays
``null`` rather than being estimated.
"""
import argparse
import hashlib
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:11434"
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
VERSION = 1


def _loopback(url):
    host = urllib.parse.urlsplit(url).hostname
    return host in LOOPBACK


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _write_json(path, obj):
    """Write the record atomically next to its destination; a torn file is never left behind."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp = os.path.join(directory, "." + os.path.basename(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _request(base, path, payload, timeout, method="POST"):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(base.rstrip("/") + path, data=body, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def model_digest(base, model, timeout):
    """The digest the runner reports for this model name, or None when it is not listed."""
    try:
        tags = _request(base, "/api/tags", None, timeout, method="GET")
    except (OSError, ValueError):
        return None
    for row in tags.get("models", []) if isinstance(tags, dict) else []:
        if isinstance(row, dict) and row.get("name") == model:
            return row.get("digest")
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt-file", required=True, type=argparse.FileType("rb"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--num-predict", type=int, default=256)
    parser.add_argument("--num-ctx", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--think", choices=("on", "off"), default="off")
    parser.add_argument("--format", choices=("none", "json"), default="none",
                        help="ask the runner for JSON-only output (Ollama format=json)")
    parser.add_argument("--allow-non-loopback", action="store_true",
                        help="permit a non-loopback endpoint; the example never needs one")
    args = parser.parse_args(argv)

    if not (args.timeout > 0 and args.num_predict > 0 and args.num_ctx > 0):
        parser.error("timeout, num-predict and num-ctx must be positive")
    if not _loopback(args.base_url) and not args.allow_non_loopback:
        parser.error("refusing a non-loopback model endpoint without --allow-non-loopback")

    prompt = args.prompt_file.read()
    args.prompt_file.close()
    record = {
        "version": VERSION,
        "model": args.model,
        "model_digest": None,
        "base_url": args.base_url,
        "prompt_sha256": hashlib.sha256(prompt).hexdigest(),
        "prompt_bytes": len(prompt),
        "options": {"num_predict": args.num_predict, "num_ctx": args.num_ctx,
                    "temperature": args.temperature, "seed": args.seed,
                    "think": args.think == "on", "format": args.format},
        "started_at": round(time.time(), 3),
        "status": None,
        "response": None,
        "thinking": None,
        "done_reason": None,
        "tokens": {"prompt": None, "eval": None},
        "runner_total_ns": None,
        "wall_seconds": None,
        "error": None,
    }
    started = time.monotonic()
    try:
        record["model_digest"] = model_digest(args.base_url, args.model, args.timeout)
        payload = {
            "model": args.model,
            "prompt": prompt.decode("utf-8"),
            "stream": False,
            "think": args.think == "on",
            "options": {"temperature": args.temperature, "seed": args.seed,
                        "num_predict": args.num_predict, "num_ctx": args.num_ctx},
        }
        if args.format == "json":
            payload["format"] = "json"
        reply = _request(args.base_url, "/api/generate", payload, args.timeout)
        if not isinstance(reply, dict):
            raise ValueError("the runner returned a non-object response")
        record.update(status="ok", response=reply.get("response", ""),
                      thinking=reply.get("thinking"),
                      done_reason=reply.get("done_reason"),
                      tokens={"prompt": reply.get("prompt_eval_count"),
                              "eval": reply.get("eval_count")},
                      runner_total_ns=reply.get("total_duration"))
        code = 0
    except (socket.timeout, TimeoutError) as exc:
        record.update(status="timeout", error=f"{type(exc).__name__}: {exc}")
        code = 3
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        record.update(status="transport_error", error=f"{type(exc).__name__}: {exc}")
        code = 4
    except ValueError as exc:
        record.update(status="protocol_error", error=f"{type(exc).__name__}: {exc}")
        code = 4
    record["wall_seconds"] = round(time.monotonic() - started, 3)
    _write_json(args.out, record)
    print(json.dumps({"status": record["status"], "wall_seconds": record["wall_seconds"],
                      "prompt_tokens": record["tokens"]["prompt"],
                      "eval_tokens": record["tokens"]["eval"],
                      "done_reason": record["done_reason"]}, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
