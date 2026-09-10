"""Ordered planning pipeline with conservative capacity dependency barriers.

Candidate builders inspect occupancy only through capacity comparisons. While
pending choices cannot change ANY such comparison, subsequent candidates and
RNG draws are identical to serial planning. At a boundary, settle earlier jobs
before building more candidates. Actual activity execution still rechecks all
resources and task/appointment ownership.
"""
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter

from simulation.systems.campus_decisions import _lineage


class DailyPlanJobs:
    def __init__(self, graph, occupancy, limit, apply):
        self.graph, self.occupancy, self.apply = graph, occupancy, apply
        self.limit = limit if type(limit) is int and 1 <= limit <= 20 else 1
        self.possible = {phase: Counter() for phase in occupancy}
        self.pending = deque()
        self.pool = None
        self.metrics = {"concurrency_limit": self.limit, "peak_pending": 0,
                        "network_calls": 0, "capacity_barriers": 0,
                        "network_seconds_sum": 0.0, "blocking_wait_seconds": 0.0}

    def __enter__(self):
        self.started = perf_counter()
        self.pool = ThreadPoolExecutor(max_workers=self.limit, thread_name_prefix="npc-plan")
        return self

    def __exit__(self, kind, value, traceback):
        try:
            if kind is None:
                while self.pending:
                    self._finish_first()
            else:
                for _, _, future, _, _ in self.pending:
                    future.cancel()
        finally:
            self.pool.shutdown(wait=True, cancel_futures=True)
            self.metrics["planning_seconds"] = perf_counter() - self.started

    def _uncertain_capacity(self):
        return any(self.occupancy[phase][node] < self.graph.locations[node].capacity
                   <= self.occupancy[phase][node] + count
                   for phase, counts in self.possible.items()
                   for node, count in counts.items() if count > 0)

    def before_actor(self):
        while self.pending:
            uncertain = self._uncertain_capacity()
            if not uncertain and len(self.pending) < self.limit:
                break
            self.metrics["capacity_barriers"] += int(uncertain)
            self._finish_first()

    def submit(self, actor, flow, options):
        try:
            job = next(flow)  # Cache lookup, budget reservation: world thread only.
        except StopIteration as completed:
            self.apply(actor, completed.value, options)
            return
        bounds = {phase: set().union(*(
            set(_lineage(self.graph, slot.get("location_id", ""))) for slot in slots))
            for phase, slots in options.items()}
        for phase, nodes in bounds.items():
            self.possible[phase].update(nodes)
        future = self.pool.submit(job.run)
        self.pending.append((actor, flow, future, options, bounds))
        self.metrics["network_calls"] += int(getattr(job, "network_request", True))
        self.metrics["peak_pending"] = max(self.metrics["peak_pending"], len(self.pending))

    def _finish_first(self):
        actor, flow, future, options, bounds = self.pending.popleft()
        started = perf_counter()
        result = future.result()
        self.metrics["blocking_wait_seconds"] += perf_counter() - started
        self.metrics["network_seconds_sum"] += result[3]
        try:
            flow.send(result)  # Validation, accounting/cache/audit: world thread.
        except StopIteration as completed:
            slots = completed.value
        else:
            raise RuntimeError("daily planning must issue at most one request per NPC")
        for phase, nodes in bounds.items():
            self.possible[phase].subtract(nodes)
        self.apply(actor, slots, options)
