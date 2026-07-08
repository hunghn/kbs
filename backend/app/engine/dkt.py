"""Deep Knowledge Tracing (DKT) — vanilla RNN implemented in pure numpy.

Follows Piech et al. (2015): the input at step t is a one-hot encoding of
(skill, correctness), the recurrent hidden state summarizes the learning
history, and the output layer predicts P(correct) for every skill at the
next step. Trained with BPTT + gradient clipping; no deep-learning
dependency needed.

Skills are mapped to the subject's topics. Models are persisted per subject
as .npz files under models_store/.
"""
import math
import os
from pathlib import Path

import numpy as np

MODEL_DIR = Path(os.environ.get("DKT_MODEL_DIR", "models_store"))
HIDDEN_SIZE = 32
MAX_SEQ_LEN = 50


class DKTModel:
    def __init__(self, n_skills: int, hidden_size: int = HIDDEN_SIZE, seed: int = 7):
        rng = np.random.default_rng(seed)
        self.n_skills = n_skills
        self.hidden = hidden_size
        n_in = 2 * n_skills
        scale_in = 1.0 / math.sqrt(n_in)
        scale_h = 1.0 / math.sqrt(hidden_size)
        self.Wxh = rng.normal(0, scale_in, (hidden_size, n_in))
        self.Whh = rng.normal(0, scale_h, (hidden_size, hidden_size))
        self.Why = rng.normal(0, scale_h, (n_skills, hidden_size))
        self.bh = np.zeros(hidden_size)
        self.by = np.zeros(n_skills)

    # ---------- forward ----------
    def forward(self, seq: list[tuple[int, int]]):
        """seq: list of (skill_idx, correct). Returns (hs, ys) where
        ys[t] = sigmoid predictions for every skill after observing step t."""
        T = len(seq)
        hs = np.zeros((T + 1, self.hidden))
        ys = np.zeros((T, self.n_skills))
        xs = np.zeros((T, 2 * self.n_skills))
        for t, (skill, correct) in enumerate(seq):
            xs[t, skill * 2 + int(correct)] = 1.0
            z = self.Wxh @ xs[t] + self.Whh @ hs[t] + self.bh
            hs[t + 1] = np.tanh(z)
            logits = self.Why @ hs[t + 1] + self.by
            ys[t] = 1.0 / (1.0 + np.exp(-np.clip(logits, -30, 30)))
        return xs, hs, ys

    def predict_next(self, seq: list[tuple[int, int]]) -> np.ndarray:
        """P(correct on each skill) after the whole observed sequence."""
        if not seq:
            # No history: prior from the bias term only
            logits = self.by
            return 1.0 / (1.0 + np.exp(-np.clip(logits, -30, 30)))
        _xs, _hs, ys = self.forward(seq[-MAX_SEQ_LEN:])
        return ys[-1]

    # ---------- training ----------
    def train_step(self, seq: list[tuple[int, int]], lr: float, clip: float = 5.0) -> float:
        """One BPTT pass over a sequence; returns summed BCE loss."""
        T = len(seq)
        if T < 2:
            return 0.0
        xs, hs, ys = self.forward(seq)

        dWxh = np.zeros_like(self.Wxh)
        dWhh = np.zeros_like(self.Whh)
        dWhy = np.zeros_like(self.Why)
        dbh = np.zeros_like(self.bh)
        dby = np.zeros_like(self.by)
        dh_next = np.zeros(self.hidden)
        loss = 0.0

        for t in reversed(range(T - 1)):
            next_skill, next_correct = seq[t + 1]
            p = float(np.clip(ys[t, next_skill], 1e-7, 1 - 1e-7))
            target = float(next_correct)
            loss += -(target * math.log(p) + (1 - target) * math.log(1 - p))

            # dL/dlogit for the observed next skill only (sigmoid + BCE)
            dy = np.zeros(self.n_skills)
            dy[next_skill] = p - target

            dWhy += np.outer(dy, hs[t + 1])
            dby += dy
            dh = self.Why.T @ dy + dh_next
            dz = (1.0 - hs[t + 1] ** 2) * dh
            dWxh += np.outer(dz, xs[t])
            dWhh += np.outer(dz, hs[t])
            dbh += dz
            dh_next = self.Whh.T @ dz

        # Average gradients over the sequence steps so the update magnitude
        # does not scale with sequence length, then clip for stability.
        n_steps = float(T - 1)
        for g in (dWxh, dWhh, dWhy, dbh, dby):
            g /= n_steps
            np.clip(g, -clip, clip, out=g)

        self.Wxh -= lr * dWxh
        self.Whh -= lr * dWhh
        self.Why -= lr * dWhy
        self.bh -= lr * dbh
        self.by -= lr * dby
        return loss

    def evaluate(self, sequences: list[list[tuple[int, int]]]) -> dict:
        """BCE / accuracy / AUC over next-step predictions."""
        probs, labels = [], []
        for seq in sequences:
            if len(seq) < 2:
                continue
            _xs, _hs, ys = self.forward(seq)
            for t in range(len(seq) - 1):
                skill, correct = seq[t + 1]
                probs.append(float(ys[t, skill]))
                labels.append(int(correct))
        if not probs:
            return {"n": 0, "bce": None, "accuracy": None, "auc": None}

        p = np.array(probs)
        y = np.array(labels)
        eps = 1e-7
        bce = float(-np.mean(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps)))
        acc = float(np.mean((p >= 0.5) == y))

        # Rank-based AUC
        pos = p[y == 1]
        neg = p[y == 0]
        if len(pos) and len(neg):
            order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
            ranks = np.empty_like(order, dtype=float)
            ranks[order] = np.arange(1, len(order) + 1)
            auc = float(
                (ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2)
                / (len(pos) * len(neg))
            )
        else:
            auc = None
        return {"n": len(probs), "bce": round(bce, 4), "accuracy": round(acc, 4), "auc": round(auc, 4) if auc is not None else None}

    # ---------- persistence ----------
    def save(self, path: Path, topic_ids: list[int], meta: dict | None = None):
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            path,
            Wxh=self.Wxh, Whh=self.Whh, Why=self.Why, bh=self.bh, by=self.by,
            topic_ids=np.array(topic_ids, dtype=np.int64),
            meta=np.array([str(meta or {})]),
        )

    @classmethod
    def load(cls, path: Path) -> tuple["DKTModel", list[int]]:
        data = np.load(path, allow_pickle=True)
        n_skills = data["Why"].shape[0]
        hidden = data["Whh"].shape[0]
        model = cls(n_skills, hidden)
        model.Wxh = data["Wxh"]
        model.Whh = data["Whh"]
        model.Why = data["Why"]
        model.bh = data["bh"]
        model.by = data["by"]
        return model, [int(t) for t in data["topic_ids"]]


def model_path(subject_id: int) -> Path:
    return MODEL_DIR / f"dkt_subject_{subject_id}.npz"


def train_dkt(
    sequences: list[list[tuple[int, int]]],
    n_skills: int,
    *,
    epochs: int = 25,
    lr: float = 0.05,
    seed: int = 7,
    holdout_ratio: float = 0.1,
) -> tuple[DKTModel, dict]:
    """Train on sequences of (skill_idx, correct); returns (model, metrics)."""
    rng = np.random.default_rng(seed)
    sequences = [s[:MAX_SEQ_LEN] for s in sequences if len(s) >= 2]
    if not sequences:
        raise ValueError("No usable sequences (need length >= 2)")

    idx = rng.permutation(len(sequences))
    n_hold = max(1, int(len(sequences) * holdout_ratio)) if len(sequences) >= 10 else 0
    hold = [sequences[i] for i in idx[:n_hold]]
    train = [sequences[i] for i in idx[n_hold:]] or sequences

    model = DKTModel(n_skills, seed=seed)
    loss_history = []
    order = np.arange(len(train))
    for epoch in range(epochs):
        rng.shuffle(order)
        total_loss, total_steps = 0.0, 0
        # Simple learning-rate decay
        cur_lr = lr / (1.0 + 0.05 * epoch)
        for i in order:
            seq = train[i]
            total_loss += model.train_step(seq, lr=cur_lr)
            total_steps += len(seq) - 1
        loss_history.append(round(total_loss / max(total_steps, 1), 4))

    metrics = {
        "n_sequences": len(sequences),
        "n_train": len(train),
        "n_holdout": len(hold),
        "epochs": epochs,
        "first_epoch_loss": loss_history[0],
        "final_epoch_loss": loss_history[-1],
        "loss_history": loss_history,
        "train_metrics": model.evaluate(train),
        "holdout_metrics": model.evaluate(hold) if hold else None,
    }
    return model, metrics
