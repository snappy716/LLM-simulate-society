"""Opt-in paid same-checkpoint audit; no game quotas or synthetic outcomes."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import getpass
import hashlib
import json
from pathlib import Path
import sys

from production.run_causal_comparison import compare, code_manifest, run_branch, write
from production.run_live_cognition_soak import AuditedProvider
from simulation.persistence.kernel_checkpoint import load_kernel_checkpoint, build_kernel_checkpoint


def validate_request_timing(branch):
    """Every automatic call belongs to a real committed overnight command."""
    requests = branch.get("requests", [])
    cursor = 0
    for row in branch["commands"]:
        start, end = row["request_span"]
        if type(start) is not int or type(end) is not int or start != cursor or not start <= end <= len(requests):
            raise ValueError("Incomplete or overlapping request spans")
        cursor = end
        dawns = {e["payload"]["day"] for e in row["result"].get("events", [])
            if e["event_type"] == "WORLD_PHASE_ADVANCED" and e["payload"]["phase"] == "morning"}
        for request in requests[start:end]:
            if not row["result"]["success"] or request.get("day") not in dawns or request.get("phase") != "morning":
                raise ValueError("Automatic API request without committed overnight transition")
    if cursor != len(requests) or branch["summary"]["api_calls"] != cursor:
        raise ValueError("Unattributed API requests")
    if not requests:
        raise ValueError("No actual requests in live audit")


class AuditBudget:
    """Shared finite acceptance budget, deliberately outside game runtime."""
    def __init__(self, output, max_requests=400, max_tokens=1_000_000):
        self.output, self.max_requests, self.max_tokens = output, max_requests, max_tokens
        self.providers = []

    def report(self):
        rows = [r for p in self.providers for r in p.records]
        tokens = {k: sum(r.get("usage", {}).get(k, 0) for r in rows)
                  for k in ("prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")}
        return {"updated_at": datetime.now(timezone.utc).isoformat(), "attempts": len(rows), "tokens": tokens,
            "missing_usage": sum("usage" not in r for r in rows),
            "max_requests": self.max_requests, "stop_after_reported_tokens": self.max_tokens,
            "limits_apply_only_to_this_audit": True,
            "note": "Reported-token threshold may be crossed by the final request; not an account bill or a currency cap",
            "ledgers": [str(p.output.name) + "/requests.json" for p in self.providers]}

    def before_request(self):
        report = self.report()
        if report["attempts"] >= self.max_requests or report["tokens"]["total_tokens"] >= self.max_tokens:
            raise SystemExit("Acceptance budget reached; game call limits unchanged")

    def flush(self):
        write(self.output / "usage-ledger.json", self.report())


class CausalProvider(AuditedProvider):
    def __init__(self, key, output, budget):
        output.mkdir()
        super().__init__(key, output, 30, True)
        self.budget = budget
        budget.providers.append(self)

    def _complete_json(self, prompt, payload, limit):
        self.budget.before_request()
        try:
            return super()._complete_json(prompt, payload, limit)
        finally:
            self.budget.flush()


def coverage(branch):
    """Observed slots only; final morning's unplayed later slots are excluded."""
    covered, planned, completed, matching = 0, 0, 0, 0
    by_day = {}
    for frame in branch["frames"][1:]:
        day, phase = frame["clock"]["day"], frame["clock"]["phase"]
        audit = frame["cognition_audit"]
        by_day[day] = deepcopy(audit["usage"])
        for who in audit["focused_ids"]:
            covered += 1
            slot = audit["daily_plans"][who].get(phase, {})
            if slot.get("planned_source") != "llm" or slot.get("day") != day:
                continue
            planned += 1
            actual = audit["actual_activities"].get(who) or {}
            if actual.get("status") == "completed" and (actual.get("day"), actual.get("phase")) == (day, phase):
                completed += 1
                matching += (actual.get("activity_id"), actual.get("location_id")) == (slot.get("activity_id"), slot.get("location_id"))
    return {"observed_focused_slots": covered, "observed_llm_planned_slots": planned,
        "completed_llm_planned_slots": completed, "matching_activity_and_location": matching,
        "daily_usage": by_day,
        "note": "Initial morning already happened under checkpoint plans; final morning only counts morning. Defeat intermediate phases without snapshots are not fabricated."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--days", type=int, choices=range(1, 8), default=7)
    parser.add_argument("--max-requests", type=int, default=400, help="Acceptance-only request threshold; no game quota")
    parser.add_argument("--max-reported-tokens", type=int, default=2_000_000, help="Acceptance-only reported-token threshold")
    args = parser.parse_args()
    if args.max_requests < 1 or args.max_reported_tokens < 1:
        parser.error("Acceptance thresholds must be positive")
    if not sys.stdin.isatty():
        parser.error("Use hidden interactive key input")
    loaded = load_kernel_checkpoint(args.checkpoint)
    checkpoint = (loaded.state, loaded.rng)
    if loaded.state.clock.phase != "morning":
        parser.error("Same-checkpoint audit requires a morning start")
    cid = next(iter(loaded.state.situations["campus_anomalies"]["cases"]))
    args.output.mkdir(parents=True, exist_ok=False)
    budget = AuditBudget(args.output, max_requests=args.max_requests, max_tokens=args.max_reported_tokens)
    key = getpass.getpass("DeepSeek API Key (not saved): ").strip()
    if not key:
        parser.error("API key required")
    manifest = code_manifest()
    for name in ("production/live_causal_audit.py", "production/run_live_cognition_soak.py"):
        manifest[name] = hashlib.sha256(Path(name).read_bytes()).hexdigest()
    write(args.output / "configuration.json", {"days": args.days, "source_files": manifest,
        "checkpoint_reused": True, "injected_conditions": [], "model": "deepseek-v4-flash",
        "thinking_mode": "disabled", "max_requests": budget.max_requests, "stop_after_reported_tokens": budget.max_tokens})
    write(args.output / "initial-checkpoint.json", build_kernel_checkpoint(*checkpoint))
    try:
        probe = CausalProvider(key, args.output / "probe", budget)
        if probe._complete_json('Reply JSON only: {"ok":true}', {"test": "causal_connectivity"}, 160).get("ok") is not True:
            raise RuntimeError("Connectivity probe failed")
        probe.secret_forget()
        results = {}
        for label, policy, paid in (("rule-unattended", "unattended", False),
                                    ("llm-unattended", "unattended", True),
                                    ("llm-participant", "participant", True)):
            directory = args.output / label
            provider = CausalProvider(key, directory, budget) if paid else None
            if not paid:
                directory.mkdir()
            result = run_branch(checkpoint, cid, args.days, policy, directory, provider=provider)
            results[label] = result
            write(directory / "coverage.json", coverage(result))
            if provider:
                validate_request_timing(result)
                provider.secret_forget()
        combined = {"provider_axis": compare(results["rule-unattended"], results["llm-unattended"], axis="provider", allow_api=True),
            "player_axis": compare(results["llm-unattended"], results["llm-participant"], allow_api=True),
            "coverage": {label: coverage(result) for label, result in results.items()}}
        write(args.output / "comparison.json", combined)
        mismatches = [p for p, h in manifest.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest() != h]
        if mismatches:
            raise RuntimeError("Source changed during audit: " + ", ".join(mismatches))
        print("LIVE_CAUSAL_COMPARISON_OK", flush=True)
    finally:
        budget.flush()
        for provider in budget.providers:
            provider.secret_forget()
        key = ""


if __name__ == "__main__":
    main()
