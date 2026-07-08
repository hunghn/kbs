"""Reinforcement Learning cho chiến lược chọn đề (contextual bandit).

Thay vì R2/R3 cố định (b_target = θ ± hằng số), tác tử RL học offset độ khó
tối ưu cho đề kế tiếp theo ngữ cảnh (độ chính xác đề trước × mức SEM hiện
tại). Reward = mức giảm SEM sau đề — tức lượng thông tin thu được về năng
lực; Q-value cập nhật kiểu bandit: Q += α (r − Q), chọn hành động ε-greedy
với ε giảm dần theo số lần thăm.
"""
import random

# Difficulty offsets applied to theta when steering the next exam
ACTIONS: list[float] = [-0.7, -0.3, 0.0, 0.3, 0.5]

EPSILON_BASE = 0.25
ALPHA = 0.3


def state_key(prev_accuracy: float, sem: float) -> str:
    if prev_accuracy >= 0.6:
        acc = "high"
    elif prev_accuracy >= 0.4:
        acc = "mid"
    else:
        acc = "low"

    if sem >= 0.6:
        s = "high"
    elif sem >= 0.35:
        s = "mid"
    else:
        s = "low"
    return f"acc_{acc}|sem_{s}"


class QTable:
    """In-memory contextual-bandit Q-table; persistence is the caller's job."""

    def __init__(self, seed: int | None = None):
        self.q: dict[tuple[str, int], float] = {}
        self.visits: dict[tuple[str, int], int] = {}
        self.rng = random.Random(seed)
        self.actions = ACTIONS

    def state_key(self, prev_accuracy: float, sem: float) -> str:
        return state_key(prev_accuracy, sem)

    def _state_visits(self, state: str) -> int:
        return sum(self.visits.get((state, a), 0) for a in range(len(ACTIONS)))

    def select_action(self, state: str) -> int:
        """ε-greedy with visit-decayed exploration; returns action index."""
        epsilon = EPSILON_BASE / (1.0 + 0.1 * self._state_visits(state))
        if self.rng.random() < epsilon:
            return self.rng.randrange(len(ACTIONS))
        best_a, best_q = 0, float("-inf")
        for a in range(len(ACTIONS)):
            q = self.q.get((state, a), 0.0)
            if q > best_q:
                best_a, best_q = a, q
        return best_a

    def update(self, state: str, action: int, reward: float):
        key = (state, action)
        old = self.q.get(key, 0.0)
        self.q[key] = old + ALPHA * (reward - old)
        self.visits[key] = self.visits.get(key, 0) + 1

    def snapshot(self) -> list[dict]:
        return [
            {
                "state": state,
                "action_index": a,
                "b_offset": ACTIONS[a],
                "q_value": round(q, 4),
                "visits": self.visits.get((state, a), 0),
            }
            for (state, a), q in sorted(self.q.items())
        ]
