import importlib.util
import json
from pathlib import Path


def diagnostic_module():
    path = Path(__file__).parents[1] / "scripts" / "diagnose-live.py"
    spec = importlib.util.spec_from_file_location("diagnose_live", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_diagnostic_returns_only_fixed_signals_and_timestamps():
    module = diagnostic_module()
    raw = '\n'.join([
        '2026-10-15T11:40:07.002014Z INFO 10.0.0.1 - "POST /stop HTTP/1.1" 200 OK SECRET',
        '2026-10-15T11:40:08Z RuntimeError: FFmpeg terminó antes de tiempo (código 218): broken pipe rtmp://private/key-SECRET',
        '2026-10-15T11:41:00Z Nothing important SECRET',
    ])
    result = module.summarise_logs(raw)
    assert result['counts'] == {'stop_requested': 1, 'ffmpeg_early_exit': 1, 'broken_pipe': 1}
    assert result['recent_events'][1]['ffmpeg_exit_code'] == 218
    rendered = json.dumps(result)
    assert 'SECRET' not in rendered and 'rtmp' not in rendered and '10.0.0.1' not in rendered


def test_diagnostic_bounds_history_and_does_not_return_bad_timestamp_text():
    module = diagnostic_module()
    result = module.summarise_logs('\n'.join('SECRET Live block failed' for _ in range(100)))
    assert len(result['recent_events']) == 80
    assert result['counts']['live_block_failed'] == 100
    assert all(event['at_utc'] is None for event in result['recent_events'])
    assert 'SECRET' not in json.dumps(result)


def test_youtube_diagnostic_only_uses_read_methods():
    query = diagnostic_module().YOUTUBE_READ
    assert '.list(' in query and '.stream_health(' in query
    assert not any(method in query for method in ('.insert(', '.update(', '.transition(', '.delete(', '.create(', '.complete('))
    assert 'streamName' not in query and 'ingestionInfo' not in query


def test_transport_failures_are_classified_without_raw_details():
    module = diagnostic_module()
    result = module.summarise_logs('\n'.join([
        '2026-10-16T10:00:00Z Input/output error rtmp://private/SECRET',
        '2026-10-16T10:00:01Z Connection refused http://private/?token=SECRET',
        '2026-10-16T10:00:02Z End of file PRIVATE',
    ]))
    assert result['counts'] == {'input_output_error': 1, 'connection_refused': 1, 'input_eof': 1}
    assert 'SECRET' not in json.dumps(result) and 'PRIVATE' not in json.dumps(result)
