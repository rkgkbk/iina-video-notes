#!/usr/bin/env python3
"""Line-delimited JSON bridge: IINA -> local ASR -> Codex CLI."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text())
SUMMARY_PROMPT = (ROOT / "summary-prompt.txt").read_text(encoding="utf-8").strip()


def summary_path(job):
    # Prompt edits invalidate summaries while preserving expensive ASR checkpoints.
    version = hashlib.sha256(SUMMARY_PROMPT.encode()).hexdigest()[:16]
    return job / "summaries" / version


def emit(kind, **data):
    print(json.dumps({"type": kind, **data}, ensure_ascii=False), flush=True)


def atomic_json(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def job_path(video, cache):
    video = Path(video).resolve(strict=True)
    if not video.is_file():
        raise ValueError("请选择本地音视频文件。")
    stat = video.stat()
    identity = [str(video), stat.st_size, stat.st_mtime_ns, CONFIG, 1]
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    return video, Path(cache) / key


def stamp(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


class Cancelled(Exception):
    pass


class Runner:
    def __init__(self, cancel):
        self.cancel = Path(cancel)

    def check(self):
        if self.cancel.exists():
            raise Cancelled("已停止，已完成的转写会保留。")

    def run(self, args, log, *, prompt=None, timeout=7200):
        self.check()
        env = dict(os.environ, PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", HF_HUB_OFFLINE="1")
        # A pipe must not fill while the worker waits; diagnostics go to a file.
        with open(log, "wb") as out:
            process = subprocess.Popen(args, stdin=subprocess.PIPE if prompt else subprocess.DEVNULL,
                                       stdout=out, stderr=out, env=env, start_new_session=True,
                                       cwd=Path(log).parent)
            try:
                if prompt:
                    process.stdin.write(prompt.encode())
                    process.stdin.close()
                start = time.monotonic()
                while process.poll() is None:
                    self.check()
                    if time.monotonic() - start > timeout:
                        raise RuntimeError("处理超时，可再次点击继续。日志：" + str(log))
                    time.sleep(0.25)
                if process.returncode:
                    tail = Path(log).read_text(errors="replace")[-1800:]
                    raise RuntimeError(f"{Path(args[0]).name} 执行失败：\n{tail}")
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()


def summary_batches(segments, limit=18000):
    batches, current, count = [], [], 0
    for segment in segments:
        line = f"[{stamp(segment['start'])}] {segment['text']}"
        if count + len(line) > limit and current:
            batches.append("\n".join(current))
            current, count = [], 0
        current.append(line)
        count += len(line) + 1
    if current:
        batches.append("\n".join(current))
    return batches


def codex_summary(text, dest, runner, merge=False):
    if dest.exists() and dest.read_text().strip():
        return dest.read_text()
    instructions = SUMMARY_PROMPT + ("\n以下是覆盖全部视频的分段摘要。请整合、去重，按上述结构重新形成全片总结；保留不同片段的关键依据、例子和局限，不能只总结最后一段。" if merge else "\n以下是视频转写内容：")
    args = [CONFIG["codex"], "exec", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only",
            "--color", "never", "-c", 'approval_policy="never"', "-o", str(dest), "-"]
    # Keep the configured model/authentication, but avoid loading unrelated MCP servers and hooks.
    import tomllib
    settings = Path.home() / ".codex/config.toml"
    if settings.exists():
        config = tomllib.loads(settings.read_text())
        for name in config.get("mcp_servers", {}):
            if all(c.isalnum() or c in "_-" for c in name):
                args.extend(["-c", f"mcp_servers.{name}.enabled=false"])
    args.extend(["-c", "features.hooks=false"])
    try:
        runner.run(args, dest.with_suffix(".log"), prompt=instructions + "\n<video_data>\n" + text + "\n</video_data>", timeout=1800)
        result = dest.read_text().strip()
        if not result:
            raise RuntimeError("Codex 没有返回总结。")
        return result
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


def transcribe(video, job, runner):
    checkpoint = job / "transcript.json"
    saved = json.loads(checkpoint.read_text()) if checkpoint.exists() else {"segments": []}
    if saved.get("complete"):
        return saved
    if saved["segments"]:
        emit("transcript", **saved)
    audio = job / "audio.wav"
    try:
        emit("status", message="正在提取完整音轨…", progress=2)
        runner.run([CONFIG["ffmpeg"], "-nostdin", "-v", "error", "-y", "-i", str(video),
                    "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio)], job / "ffmpeg.log")
        emit("status", message="正在加载本地 Qwen-ASR…", progress=5)
        import numpy as np
        with contextlib.redirect_stdout(sys.stderr):
            from mlx_audio.stt.utils import load_model
            model = load_model(str(Path(CONFIG["asrDirectory"]) / "model"))
        with wave.open(str(audio)) as wav:
            rate = wav.getframerate()
            duration = wav.getnframes() / rate
            chunk = CONFIG["chunkSeconds"]
            total = math.ceil(duration / chunk)
            segments = saved["segments"]
            for index in range(len(segments), total):
                runner.check()
                start = index * chunk
                emit("status", message=f"正在转写 {index + 1}/{total} 段…", progress=5 + 70 * index / total)
                wav.setpos(int(start * rate))
                samples = np.frombuffer(wav.readframes(int(chunk * rate)), dtype="<i2").astype(np.float32) / 32768
                with contextlib.redirect_stdout(sys.stderr):
                    result = model.generate(samples, language=None, max_tokens=4096, verbose=False)
                segments.append({"start": start, "end": min(start + chunk, duration), "text": result.text.strip()})
                saved = {"segments": segments, "duration": duration, "complete": False}
                atomic_json(checkpoint, saved)
                emit("segment", index=index, segment=segments[-1], duration=duration)
            saved["complete"] = True
            atomic_json(checkpoint, saved)
        return saved
    finally:
        audio.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["run", "inspect", "start", "copy"])
    parser.add_argument("--video", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--cancel")
    parser.add_argument("--events")
    parser.add_argument("--mode", choices=["transcribe", "summarize"], default="transcribe")
    parser.add_argument("--content", choices=["summary", "transcript"], default="summary")
    args = parser.parse_args()
    if args.action == "start":
        if not args.events or not args.cancel:
            raise ValueError("缺少进度文件路径。")
        with open(args.events, "wb") as out, open(args.events + ".log", "wb") as err:
            process = subprocess.Popen([sys.executable, str(ROOT / "worker.py"), "run", "--video", args.video,
                                        "--cache", args.cache, "--cancel", args.cancel, "--mode", args.mode],
                                       stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                       start_new_session=True)
        emit("started", pid=process.pid)
        return
    video, job = job_path(args.video, args.cache)
    summaries_dir = summary_path(job)
    result_file = summaries_dir / "result.json"
    if args.action == "copy":
        if args.content == "transcript":
            transcript = json.loads((job / "transcript.json").read_text(encoding="utf-8"))
            text = "\n\n".join(f"[{stamp(s['start'])}] {s['text']}" for s in transcript["segments"])
        else:
            text = json.loads(result_file.read_text(encoding="utf-8"))["summary"]
        subprocess.run(["/usr/bin/pbcopy"], input=text.encode("utf-8"), check=True, timeout=10)
        emit("copied")
        return
    if args.action == "inspect":
        if result_file.exists():
            emit("result", **json.loads(result_file.read_text()))
        elif (job / "transcript.json").exists():
            saved = json.loads((job / "transcript.json").read_text())
            emit("transcription_done" if saved.get("complete") else "transcript", **saved)
            if not saved.get("complete"):
                emit("status", message="已有转写进度，点击继续转录。", progress=0)
        return
    if not args.cancel:
        raise ValueError("缺少取消标记路径。")
    if result_file.exists():
        emit("result", **json.loads(result_file.read_text()))
        return
    job.mkdir(parents=True, exist_ok=True)
    summaries_dir.mkdir(parents=True, exist_ok=True)
    with open(Path(args.cache) / "worker.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("另一个视频正在处理，请等待它完成或停止后再试。")
        runner = Runner(args.cancel)
        if args.mode == "summarize":
            checkpoint = job / "transcript.json"
            transcript = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
            if not transcript.get("complete"):
                raise RuntimeError("请先完成转录，再手动生成总结。")
        else:
            transcript = transcribe(video, job, runner)
        runner.check()
        emit("transcript", **transcript)
        if not any(s["text"] for s in transcript["segments"]):
            raise RuntimeError("未识别到语音，无法生成总结。")
        if args.mode == "transcribe":
            emit("transcription_done", **transcript)
            return
        parts = summary_batches(transcript["segments"])
        summaries = []
        for i, part in enumerate(parts):
            runner.check()
            emit("status", message=f"Codex 正在总结 {i + 1}/{len(parts)}…", progress=76 + 18 * i / len(parts))
            summaries.append(codex_summary(part, summaries_dir / f"summary-{i}.md", runner))
        if len(summaries) > 1:
            # Reduce recursively so unusually long videos cannot overflow the next request.
            level = 0
            while len(summaries) > 1:
                groups, current, size = [], [], 0
                for summary in summaries:
                    if current and size + len(summary) > 24000:
                        groups.append("\n\n".join(current))
                        current, size = [], 0
                    current.append(summary)
                    size += len(summary)
                if current:
                    groups.append("\n\n".join(current))
                if len(groups) == len(summaries):
                    raise RuntimeError("分段摘要过长，请检查 Codex 输出后重试。")
                emit("status", message="正在汇总全片要点…", progress=96)
                summaries = [codex_summary(g, summaries_dir / f"merged-{level}-{i}.md", runner, True) for i, g in enumerate(groups)]
                level += 1
        result = {**transcript, "summary": summaries[0], "name": video.name, "folder": str(summaries_dir)}
        atomic_json(result_file, result)
        (summaries_dir / "总结.md").write_text(result["summary"], encoding="utf-8")
        (summaries_dir / "转写.txt").write_text("\n\n".join(f"[{stamp(s['start'])}] {s['text']}" for s in transcript["segments"]), encoding="utf-8")
        emit("result", **result)


if __name__ == "__main__":
    try:
        main()
    except Cancelled as error:
        emit("cancelled", message=str(error))
    except Exception as error:
        emit("error", message=str(error))
        sys.exit(1)
