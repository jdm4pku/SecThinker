"""Export or generate RQ1 candidates; never starts a model service or evaluator."""
import argparse
import ast
import concurrent.futures
import contextlib
import fcntl
import socket
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from prompt_baselines.core import ROOT, tasks, digest, save, now, extract
from .prompts import METHODS, PROMPT_DIR, build_prompt
from secthinker_experiments.artifacts import create_output, write_result

REQ = "[Completed Requirements]"
CODE = "[Code]"
ANALYSIS = "[Analysis]"

def response_sections(content):
    """Separate scored requirements from code so either artifact survives failure of the other."""
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty_output")
    # Only whole-line section markers count; do not split on prose mentions.
    markers = list(re.finditer(r"(?m)^\[(?:Analysis|Completed Requirements|Code)\]\s*$", content))
    sections = {}
    for i, marker in enumerate(markers):
        name = marker.group().strip()
        if name in sections:
            raise ValueError("duplicate_section:" + name)
        end = markers[i+1].start() if i+1 < len(markers) else len(content)
        sections[name] = content[marker.end():end].strip("\r\n")
    return sections

def parse_response(content, task):
    sections = response_sections(content)
    requirements = sections.get(REQ, "").strip()
    analysis = sections.get(ANALYSIS, "").strip()
    code_section = sections.get(CODE)
    # Preserve a usable single code block even if section formatting is missing.
    source = code_section if code_section is not None else content
    blocks = list(re.finditer(r"```[^\n]*\n(.*?)```", source, re.S))
    if len(blocks) != 1:
        raise ValueError("expected_one_code_block")
    code = blocks[0].group(1).strip("\r\n") + "\n"
    return {"requirements": requirements, "analysis": analysis, "code": code,
            "requirements_status": "present" if requirements else "missing",
            "format_warnings": ([] if code_section is not None else ["missing_code_heading"]) +
                               ([] if requirements else ["missing_completed_requirements"])}

def payload_for(args, prompt):
    payload = {"model": args.model, "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.0, "top_p": 1.0, "max_tokens": args.max_tokens,
               "n": 1, "seed": args.seed, "stream": False}
    if args.disable_native_thinking:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    return payload

def request(args, prompt, dest):
    payload = payload_for(args, prompt)
    headers = {"Content-Type": "application/json"}
    if args.api_key_env:
        token = os.environ.get(args.api_key_env)
        if not token:
            raise RuntimeError("API key environment variable is not set")
        headers["Authorization"] = "Bearer " + token
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    # A durable successful API response is the checkpoint, even if parsing was interrupted.
    saved = sorted(dest.glob("code.response.*.json"), key=lambda p: int(p.name.split(".")[2]))
    for path in saved:
        record = json.loads(path.read_text())
        body = record["response"]
        choice = body["choices"][0]
        return choice["message"].get("content") or "", choice["finish_reason"], body.get("usage", {})
    previous = [int(p.name.split(".")[2]) for p in dest.glob("code.request.*.json")]
    first_attempt = max(previous, default=-1) + 1
    for retry in range(3):
        attempt = first_attempt + retry
        save(dest / f"code.request.{attempt}.json", payload)
        start = time.monotonic()
        try:
            req = urllib.request.Request(args.endpoint.rstrip("/") + "/chat/completions",
                data=json.dumps(payload).encode(), headers=headers)
            with opener.open(req, timeout=600) as response:
                body = json.load(response)
            # Validate protocol before treating it as a received model completion.
            choice = body["choices"][0]
            finish = choice["finish_reason"]
            content = choice["message"].get("content") or ""
            save(dest / f"code.response.{attempt}.json",
                 {"elapsed_s": time.monotonic()-start, "received_at": now(), "response": body})
            return content, finish, body.get("usage", {})
        except (urllib.error.URLError, TimeoutError) as exc:
            save(dest / f"code.error.{attempt}.json", {"error": repr(exc), "time": now()})
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in (408, 429, 500, 502, 503, 504):
                raise
            if retry == 2:
                raise
            time.sleep(2 ** retry)

def generate_one(task, args):
    dest = args.output / "tasks" / f'{task["index"]:04d}'
    dest.mkdir(parents=True, exist_ok=True)
    resultfile = dest / "generation.json"
    if resultfile.exists():
        old = json.loads(resultfile.read_text())
        if old["status"] != "generation_error":
            return old["status"]
        history = dest / "infrastructure_history"
        history.mkdir(exist_ok=True)
        version = len(list(history.glob("generation.*.json")))
        resultfile.replace(history / f"generation.{version}.json")
    prompt = build_prompt(task, args.method)
    save(dest / "task.json", task)
    (dest / "prompt.txt").write_text(prompt)
    result = {"key": task["key"], "index": task["index"], "started_at": now(),
              "candidate": None, "prompt_sha256": digest(prompt)}
    try:
        content, finish, usage = request(args, prompt, dest)
    except Exception as exc:
        result.update(status="generation_error", error=repr(exc))
    else:
        (dest / "raw_content.txt").write_text(content)
        result.update(code_finish_reason=finish, code_usage=usage)
        try:
            sections = response_sections(content)
            requirements = sections.get(REQ, "").strip()
            (dest / "completed_requirements.txt").write_text(requirements + "\n")
            (dest / "analysis.txt").write_text(sections.get(ANALYSIS, "").strip() + "\n")
            result.update(requirements_status="present" if requirements else "missing",
                          requirements_sha256=digest(requirements))
            parsed = parse_response(content, task)
            code = parsed["code"]
            candidate = dest / ("candidate." + task["language"])
            candidate.write_text(code)
            result.update(status="generated", candidate=candidate.name, candidate_sha256=digest(code),
                          requirements_status=parsed["requirements_status"],
                          requirements_sha256=digest(parsed["requirements"]),
                          format_warnings=parsed["format_warnings"])
            if finish == "length":
                result.update(status="invalid_output", error="truncated_generation")
            elif finish != "stop":
                result.update(status="invalid_output", error="unexpected_finish_reason:" + str(finish))
            elif task["language"] == "py":
                try:
                    ast.parse(code)
                except SyntaxError as exc:
                    result.update(status="invalid_output", error="syntax_error:" + str(exc))
        except ValueError as exc:
            result.update(status="invalid_output", error=str(exc))
    result["finished_at"] = now()
    save(resultfile, result)
    return result["status"]

@contextlib.contextmanager
def output_lock(output):
    # Keep the inode: flock is automatically released after exit, SIGKILL, or reboot.
    path = output / ".generation.lock"
    with path.open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another generator holds the output lock: " + str(output))
        stream.seek(0); stream.truncate()
        json.dump({"pid": os.getpid(), "hostname": socket.gethostname(), "started_at": now()}, stream)
        stream.flush()
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)

def generate(args, selected):
    sources = [Path(__file__), Path(__file__).with_name("prompts.py"),
               ROOT / "src/prompt_baselines/core.py", ROOT / "src/secthinker_experiments/artifacts.py", *sorted(PROMPT_DIR.glob("*.txt"))]
    cfg = {k: v for k, v in vars(args).items() if k not in ("output", "command")}
    cfg.update(temperature=0.0, top_p=1.0, n=1,
               input_sha256=digest(json.dumps(selected, sort_keys=True)),
               source_sha256={str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sources})
    args.output.mkdir(parents=True, exist_ok=True)
    with output_lock(args.output):
        manifest = args.output / "manifest.json"
        if manifest.exists():
            if json.loads(manifest.read_text())["config"] != cfg:
                raise RuntimeError("Refusing to resume with changed inputs, prompts, model, settings or source")
        else:
            if (args.output / "tasks").exists():
                raise RuntimeError("Tasks exist without a manifest; use a fresh output directory")
            save(manifest, {"config": cfg, "created_at": now(), "task_count": len(selected),
                            "implementation": "SecThinker RQ1 prompting protocol v2; requirements and complete code"})
        write_result(args.output)
        counts = {}
        # Submit only bounded work. Stop taking new tasks if the service goes away.
        stopped = False
        iterator = iter(selected)
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            pending = {}
            def submit_next():
                task = next(iterator, None)
                if task is not None:
                    pending[pool.submit(generate_one, task, args)] = task
            for _ in range(args.concurrency):
                submit_next()
            completed = 0
            while pending:
                ready, _ = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in ready:
                    pending.pop(future)
                    status = future.result()
                    counts[status] = counts.get(status, 0) + 1
                    completed += 1
                    if status == "generation_error":
                        stopped = True
                    save(args.output / "status.json", {"phase": "generation", "completed": completed,
                         "total": len(selected), "counts": counts, "updated_at": now()})
                    write_result(args.output)
                    print(f"{now()} {completed}/{len(selected)} {counts}", flush=True)
                if not stopped:
                    for _ in ready:
                        submit_next()
        phase = "paused_infrastructure" if stopped else "generated_waiting_evaluation"
        save(args.output / "status.json", {"phase": phase,
             "completed": completed, "total": len(selected), "counts": counts, "updated_at": now()})
        write_result(args.output)
        if stopped:
            raise RuntimeError("Service/infrastructure error: checkpoints retained; run the same command to resume")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("export", "generate"))
    parser.add_argument("--dataset", required=True, choices=("codesec_eval", "codeguard_plus"))
    parser.add_argument("--method", required=True, choices=METHODS)
    parser.add_argument("--output", type=Path, help="Existing experiment directory to resume; omitted creates output/{dataset}/{model}_{prompt}_n{N}_{timestamp}")
    parser.add_argument("--endpoint", help="OpenAI-compatible API base URL ending in /v1")
    parser.add_argument("--model", help="Exact served model ID; recorded in manifest")
    parser.add_argument("--api-key-env", help="Name of environment variable; value is never recorded")
    parser.add_argument("--disable-native-thinking", action="store_true",
                        help="Send enable_thinking=false; use consistently for all three strategies")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if args.limit < 0 or args.concurrency < 1 or args.max_tokens < 1:
        parser.error("limit must be nonnegative; concurrency and max-tokens must be positive")
    selected = tasks(args.dataset)
    if args.limit:
        selected = selected[:args.limit]
    if args.output is None:
        if not args.model:parser.error("--model is required to name a new experiment")
        args.output = create_output(args.dataset,args.model,args.method,len(selected))
        print("Experiment output: " + str(args.output),flush=True)
    args.output = args.output.resolve()
    if not args.output.is_relative_to(ROOT):parser.error("output must remain inside " + str(ROOT))
    if args.command == "export":
        args.output.mkdir(parents=True, exist_ok=True)
        with (args.output / "prompts.jsonl").open("w") as stream:
            for task in selected:
                prompt = build_prompt(task, args.method)
                stream.write(json.dumps({"key": task["key"], "index": task["index"],
                    "public_input_sha256": task["public_input_sha256"], "prompt": prompt,
                    "prompt_sha256": digest(prompt)}, ensure_ascii=False) + "\n")
        print(json.dumps({"exported": len(selected), "output": str(args.output), "api_calls": 0}))
    else:
        if not args.endpoint or not args.model:
            parser.error("generate requires --endpoint and --model")
        generate(args, selected)

if __name__ == "__main__":
    main()
