import json
import os
from typing import Any, Dict, Optional


class ExperienceIndex:
    """
    ExperienceIndex aggregates and tracks execution telemetry for utilities.
    Assists ContextResolver in ranking compatible bindings dynamically.
    """
    def __init__(self, index_path: Optional[str] = None):
        """index_path: file to persist to, or ":memory:" (default) for a
        per-process index that never touches disk. Callers that want the
        conventional persistent location pass ExperienceIndex.default_path()."""
        self._in_memory = not index_path or index_path == ":memory:"
        self.index_path = ":memory:" if self._in_memory else index_path
        if not self._in_memory:
            self._ensure_dir()
        self.experience: Dict[str, Dict[str, Any]] = self._load()

    @staticmethod
    def default_path() -> str:
        return os.path.join(os.environ.get("GLULESS_HOME", os.path.expanduser("~/.gluless")), "experience_index.json")

    def _ensure_dir(self):
        dir_name = os.path.dirname(self.index_path)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self._in_memory:
            return {}
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save(self):
        if self._in_memory:
            return
        self._ensure_dir()
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(self.experience, f, indent=2)

    def record_invocation(
        self,
        utility_id: str,
        success: bool,
        latency: float,
        failure: Optional[str] = None
    ):
        """
        Record empirical invocation latency and outcome statistics for a utility.
        """
        if utility_id not in self.experience:
            self.experience[utility_id] = {
                "utility_id": utility_id,
                "executions": 0,
                "successful_invocations": 0,
                "goal_contributing": 0,
                "median_latency": 0.0,
                "latencies": [],
                "common_failures": []
            }

        data = self.experience[utility_id]
        data["executions"] += 1

        if success:
            data["successful_invocations"] += 1
            data["goal_contributing"] += 1  # For simple counting in POC

        data["latencies"].append(latency)
        # Compute median latency
        sorted_lats = sorted(data["latencies"])
        n = len(sorted_lats)
        if n % 2 == 1:
            data["median_latency"] = sorted_lats[n // 2]
        else:
            data["median_latency"] = (sorted_lats[n // 2 - 1] + sorted_lats[n // 2]) / 2.0

        if failure:
            data["common_failures"].append(failure)
            # Keep unique/shortened failure list
            if len(data["common_failures"]) > 10:
                data["common_failures"].pop(0)

        self.save()

    def get_metrics(self, utility_id: str) -> Dict[str, Any]:
        """
        Retrieve performance metrics for a utility.
        """
        default_stats = {
            "utility_id": utility_id,
            "executions": 0,
            "success_rate": 1.0,
            "median_latency": 0.0
        }

        record = self.experience.get(utility_id)
        if not record:
            return default_stats

        success_rate = (
            record["successful_invocations"] / record["executions"]
            if record["executions"] > 0 else 1.0
        )

        return {
            "utility_id": utility_id,
            "executions": record["executions"],
            "success_rate": success_rate,
            "median_latency": record["median_latency"]
        }
