import importlib.util
from pathlib import Path
import tempfile
import threading
import time

spec = importlib.util.spec_from_file_location('worker', 'AI-Video.iinaplugin/worker.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
with tempfile.TemporaryDirectory() as temp:
    folder = Path(temp).resolve()
    video = folder / 'a video 中文.mp4'
    video.write_bytes(b'one')
    _, first = w.job_path(video, folder)
    video.write_bytes(b'changed')
    _, second = w.job_path(video, folder)
    assert first != second
    original_prompt = w.SUMMARY_PROMPT
    summary_before = w.summary_path(first)
    w.SUMMARY_PROMPT += '\nChanged prompt'
    assert w.summary_path(first) != summary_before
    assert w.job_path(video, folder)[1] == second
    w.SUMMARY_PROMPT = original_prompt
    segments = [{'start':i * 60,'text':'x' * 100} for i in range(8)]
    batches = w.summary_batches(segments, 250)
    assert len(batches) == 4 and '[00:07:00]' in batches[-1]
    cancel = folder / 'cancel'
    timer = threading.Timer(.3, lambda: cancel.touch())
    timer.start()
    start = time.monotonic()
    try:
        w.Runner(cancel).run(['/bin/sleep','30'], folder / 'sleep.log')
        raise AssertionError('cancellation ignored')
    except w.Cancelled:
        assert time.monotonic() - start < 3
    timer.join()
    dest = folder / 'data.json'
    w.atomic_json(dest, {'中文':'ok'})
    assert '中文' in dest.read_text()
print('PASS: cache invalidation, long transcript batches, child cancellation, atomic checkpoint')
