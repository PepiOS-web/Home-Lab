#!/usr/bin/env python3
"""Read-only operator diagnostics. Never print raw logs, config, URLs or keys."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import subprocess

NAMES = ("astrolearner-iss-live", "astrolearner-iss-live-camera-browser-1")
SIGNALS = {
    "stop_requested": (r'"POST /stop(?:\s|\?)',),
    "start_requested": (r'"POST /start(?:\s|\?)',),
    "live_block_failed": (r"Live block failed",),
    "youtube_verification_failed": (r"YouTube broadcast verification failed",),
    "youtube_rate_limit": (r"userRequestsExceedRateLimit",),
    "ffmpeg_early_exit": (r"FFmpeg terminó antes de tiempo",),
    "broken_pipe": (r"broken[ _]pipe",),
    "same_broadcast_recovery": (r"Recovering same YouTube broadcast",),
    "output_connection_interrupted": (r"Output connection interrupted",),
    "connection_reset": (r"connection reset",),
    "connection_timeout": (r"connection timed out", r"i/o timeout", r"operation timed out"),
    "connection_refused": (r"connection refused",),
    "input_output_error": (r"input/output error",),
    "input_eof": (r"end of file", r"eof while"),
    "muxer_write_failed": (r"error submitting a packet to the muxer", r"error muxing a packet", r"error writing trailer"),
    "filter_reinitialization": (r"error reinitializing filters", r"impossible to convert between the formats"),
    "thread_limit": (r"pthread_create", r"failed to create thread"),
    "out_of_memory": (r"out of memory", r"cannot allocate memory"),
    "youtube_completed": (r"YouTube marcó la emisión como complete", r"YouTube marcó la emisión como revoked"),
    "sigterm": (r"received signal 15",),
    "application_start": (r"Application startup complete",),
    "application_shutdown": (r"Application shutdown complete",),
}


def timestamp(value: str) -> str | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def summarise_logs(raw: str) -> dict:
    events, counts = [], {}
    for line in raw.splitlines():
        stamp, _, text = line.partition(" ")
        signals = [name for name, patterns in SIGNALS.items()
                   if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)]
        if not signals:
            continue
        for signal in signals:
            counts[signal] = counts.get(signal, 0) + 1
        event = {"at_utc": timestamp(stamp), "signals": signals}
        code = re.search(r"FFmpeg terminó antes de tiempo \(código (-?\d{1,6})\)", text)
        if code:
            event["ffmpeg_exit_code"] = int(code[1])
        events.append(event)
    return {"counts": counts, "recent_events": events[-80:]}


def command(args: list[str], timeout: int = 25, data: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, input=data, capture_output=True, text=True, timeout=timeout, check=False)


YOUTUBE_READ = r'''
import json
from datetime import datetime
from app.config import Settings
from app.youtube import YouTubeLive
try:
    s=Settings(); yt=YouTubeLive(s.youtube_token,s.privacy,s.source_label)
    result=yt.api.liveBroadcasts().list(part="id,snippet,status,contentDetails",broadcastStatus="all",maxResults=6,
        fields="items(id,snippet(actualStartTime,actualEndTime),status(lifeCycleStatus,privacyStatus),contentDetails(enableAutoStop,boundStreamId))").execute()
    items=result.get("items",[]); streams=[]; output=[]
    for b in items:
        snippet=b.get("snippet",{}); details=b.get("contentDetails",{}); status=b.get("status",{})
        start,end=snippet.get("actualStartTime"),snippet.get("actualEndTime")
        duration=None
        if start and end:
            duration=(datetime.fromisoformat(end.replace("Z","+00:00"))-datetime.fromisoformat(start.replace("Z","+00:00"))).total_seconds()
        output.append({"broadcast_id":b.get("id"),"start_utc":start,"end_utc":end,"duration_seconds":duration,
            "lifecycle":status.get("lifeCycleStatus"),"privacy":status.get("privacyStatus"),"auto_stop":details.get("enableAutoStop")})
        sid=details.get("boundStreamId")
        if sid and len(streams)<2: streams.append(sid)
    health=[]
    for sid in streams:
        health.append(yt.stream_health(sid))
    print(json.dumps({"publishing":False,"broadcasts":output,"recent_ingest_health":health}))
except Exception as exc:
    print(json.dumps({"publishing":False,"query_failed":True,"error_type":type(exc).__name__,"http_status":getattr(getattr(exc,"resp",None),"status",None)}))
'''


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("Ejecutar con sudo. Solo lee diagnosticos; no inicia ni detiene nada.")
    report = {"at_utc": datetime.now(timezone.utc).isoformat(),
              "publishing": False, "mutations_requested": False, "containers": []}
    for name in NAMES:
        entry = {"container": name}
        try:
            state = command(["docker", "inspect", "--format", "{{json .State}}", name])
            if state.returncode:
                entry["not_found_or_unavailable"] = True
                report["containers"].append(entry)
                continue
            value = json.loads(state.stdout)
            entry["state"] = {key: value.get(key) for key in ("Status", "Running", "Restarting", "OOMKilled", "ExitCode", "StartedAt", "FinishedAt")}
            entry["health"] = value.get("Health", {}).get("Status")
            restarts = command(["docker", "inspect", "--format", "{{.RestartCount}}", name])
            if restarts.returncode == 0 and restarts.stdout.strip().isdigit():
                entry["restart_count"] = int(restarts.stdout.strip())
            # Portal polling produces many access lines. A 6000-line tail could
            # hide last night's incident even with a 36-hour time window.
            logs = command(["docker", "logs", "--timestamps", "--since", "36h", "--tail", "60000", name])
            entry["log_summary"] = summarise_logs(logs.stdout + "\n" + logs.stderr)
        except Exception as exc:
            entry["diagnostic_error_type"] = type(exc).__name__
        report["containers"].append(entry)
    try:
        runtime = command(["docker", "exec", "astrolearner-iss-live", "python", "-c", r'''
import json
from app.config import Settings
s=Settings()
keys=("dry_run","auto_start","block_seconds","gap_seconds","max_blocks","fps","encoder","map_seconds","camera_enabled")
print(json.dumps({k:getattr(s,k) for k in keys}))
'''])
        report["runtime_settings"] = json.loads(runtime.stdout) if runtime.returncode == 0 else {"unavailable": True}
    except Exception as exc:
        report["runtime_settings"] = {"unavailable": True, "error_type": type(exc).__name__}
    try:
        response = command(["docker", "exec", "-i", "astrolearner-iss-live", "python", "-"], timeout=55, data=YOUTUBE_READ)
        report["youtube"] = json.loads(response.stdout) if response.returncode == 0 else {"query_failed": True}
    except Exception as exc:
        report["youtube"] = {"query_failed": True, "error_type": type(exc).__name__}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
