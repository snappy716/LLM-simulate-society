"""Network-only jobs; generators reserve and settle usage on the world thread.

Neither a worker nor its provider receives a world, RNG, cache or transaction.
No speculative retries: one submitted job is one provider request.
"""
from copy import copy, deepcopy
from dataclasses import dataclass
from time import perf_counter

from simulation.cognition.provider import OpenAICompatibleCognitionProvider


@dataclass
class DecisionJob:
    provider: object
    request: object
    output_tokens: int
    network_request = True

    def run(self):
        provider = self.provider
        # This adapter's diagnostic dictionary is its only per-call mutation.
        # Keep parallel completions from overwriting another call's status.
        if type(provider) is OpenAICompatibleCognitionProvider:
            provider = copy(provider)
            provider.last_result = deepcopy(provider.last_result)
        started = perf_counter()
        try:
            raw = dict(provider.decide(deepcopy(self.request), max_output_tokens=self.output_tokens))
            error = None
        except Exception as exc:
            raw, error = None, exc
        return raw, error, deepcopy(getattr(provider, "last_result", None)), perf_counter() - started


@dataclass
class CachedDecisionJob:
    raw: dict
    revision: int
    network_request = False

    def run(self):
        raw = deepcopy(self.raw)
        raw["candidate_revision"] = self.revision
        return raw, None, None, 0.0


def run_inline(flow):
    """Drive the same validation path for ordinary synchronous decisions."""
    try:
        job = next(flow)
        while True:
            job = flow.send(job.run())
    except StopIteration as completed:
        return completed.value
