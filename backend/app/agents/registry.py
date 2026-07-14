"""Multi-Agent System registry.

Hệ thống được tổ chức thành các tác tử chuyên biệt, mỗi tác tử sở hữu một
nhóm luật suy diễn và một mô-đun cài đặt cụ thể. Registry này là nguồn
chân lý duy nhất cho kiến trúc MAS: mỗi agent trỏ tới module thật, các
luật nó điều khiển và các endpoint nó phục vụ — đồng thời hoạt động của
agent được đo trực tiếp từ bảng inference_rule_logs (mỗi lần một luật
kích hoạt là một lần agent đó ra quyết định).
"""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import InferenceRuleLog

AGENTS: list[dict] = [
    {
        "id": "planner",
        "name": "Planner Agent",
        "role": "Điều phối đề thi: áp bộ luật để dựng blueprint đề kế tiếp (band độ khó, phủ topic, dành slot, chống lặp)",
        "module": "backend/app/services/exam_generation.py",
        "rules": ["R1", "R2", "R3", "R4", "R5", "R6", "R8", "R11", "R12"],
        "endpoints": ["/api/quiz/adaptive/start", "/api/quiz/adaptive/{id}/next"],
        "kind": "symbolic",
    },
    {
        "id": "generator",
        "name": "Generator Agent",
        "role": "Sinh câu hỏi mới bằng LLM theo topic, mức Bloom và mục tiêu IRT khi ngân hàng thiếu item phù hợp",
        "module": "backend/app/engine/llm_generation.py",
        "rules": ["R9"],
        "endpoints": ["/api/quiz/generate-question"],
        "kind": "llm",
    },
    {
        "id": "validator",
        "name": "Validator Agent",
        "role": "Thẩm định câu hỏi sinh ra: tự giải lại, kiểm tra đáp án nhất quán và gán độ khó dự kiến",
        "module": "backend/app/engine/llm_client.py",
        "rules": ["R10"],
        "endpoints": [],
        "kind": "llm",
    },
    {
        "id": "assessor",
        "name": "Assessor Agent",
        "role": "Chấm đề, ước lượng năng lực θ/SEM bằng Bayesian EAP tích lũy và phát hiện đoán mò",
        "module": "backend/app/engine/irt.py + app/engine/scoring.py",
        "rules": ["R7", "BLOOM"],
        "endpoints": ["/api/quiz/adaptive/{id}/submit", "/api/quiz/{id}/submit"],
        "kind": "symbolic",
    },
    {
        "id": "tracer",
        "name": "Knowledge Tracer Agent",
        "role": "Deep Knowledge Tracing: RNN học chuỗi tương tác, dự đoán P(đúng) từng topic và cấp prior warm-start",
        "module": "backend/app/engine/dkt.py",
        "rules": ["R0"],
        "endpoints": ["/api/quiz/dkt/train", "/api/users/ability-prediction"],
        "kind": "neural",
    },
    {
        "id": "strategist",
        "name": "Strategist Agent",
        "role": "Reinforcement Learning: contextual bandit học offset độ khó tối ưu, reward là lượng thông tin thu được (ΔSEM)",
        "module": "backend/app/engine/rl_policy.py",
        "rules": ["RL"],
        "endpoints": ["/api/quiz/adaptive/rl-policy"],
        "kind": "neural",
    },
    {
        "id": "explainer",
        "name": "Explainer Agent",
        "role": "Explainable AI: phân rã Δθ từng câu, Fisher share, kỹ năng đo được, phát hiện ngộ nhận và sinh narrative",
        "module": "backend/app/api/quiz.py (get_session_explanation)",
        "rules": [],
        "endpoints": ["/api/quiz/{id}/explanation"],
        "kind": "symbolic",
    },
    {
        "id": "calibrator",
        "name": "Calibrator Agent",
        "role": "Tự tinh chỉnh cơ sở tri thức: hiệu chuẩn lại độ khó b từ log trả lời thật bằng MLE 3PL",
        "module": "backend/app/engine/calibration.py",
        "rules": [],
        "endpoints": ["/api/quiz/calibration/run"],
        "kind": "symbolic",
    },
    {
        "id": "pathfinder",
        "name": "Pathfinder Agent",
        "role": "Lộ trình học: sắp xếp topo đồ thị tiên quyết, áp đường cong quên để đề xuất thứ tự ôn tập",
        "module": "backend/app/api/users.py (get_learning_path)",
        "rules": [],
        "endpoints": ["/api/users/learning-path"],
        "kind": "symbolic",
    },
]

# Message flow: (from, to, label). "learner" and "kb" are external nodes
# (người học và cơ sở tri thức).
EDGES: list[dict] = [
    {"from": "learner", "to": "planner", "label": "yêu cầu đề thi"},
    {"from": "planner", "to": "learner", "label": "đề thi N câu"},
    {"from": "learner", "to": "assessor", "label": "bài làm"},
    {"from": "planner", "to": "generator", "label": "thiếu item quanh b_target (R9)"},
    {"from": "generator", "to": "validator", "label": "câu nháp"},
    {"from": "validator", "to": "planner", "label": "câu đạt chuẩn + b dự kiến (R10)"},
    {"from": "assessor", "to": "planner", "label": "θ, SEM, streak topic"},
    {"from": "assessor", "to": "strategist", "label": "reward ΔSEM"},
    {"from": "strategist", "to": "planner", "label": "offset độ khó (RL)"},
    {"from": "assessor", "to": "tracer", "label": "chuỗi tương tác"},
    {"from": "tracer", "to": "planner", "label": "prior θ₀ warm-start (R0)"},
    {"from": "assessor", "to": "explainer", "label": "scoring data"},
    {"from": "explainer", "to": "learner", "label": "narrative + Δθ + ngộ nhận"},
    {"from": "assessor", "to": "calibrator", "label": "log trả lời"},
    {"from": "calibrator", "to": "kb", "label": "b hiệu chuẩn"},
    {"from": "kb", "to": "planner", "label": "ngân hàng câu hỏi + ontology"},
    {"from": "assessor", "to": "pathfinder", "label": "mastery theo topic"},
    {"from": "pathfinder", "to": "learner", "label": "lộ trình học"},
]


async def get_architecture(db: AsyncSession) -> dict:
    """Trả về kiến trúc MAS kèm mức độ hoạt động thật của từng agent,
    đo bằng số lần các luật nó sở hữu đã kích hoạt (inference_rule_logs)."""
    counts_rows = await db.execute(
        select(InferenceRuleLog.rule_code, func.count(InferenceRuleLog.id))
        .group_by(InferenceRuleLog.rule_code)
    )
    rule_counts = {code: int(n) for code, n in counts_rows}

    agents = []
    for a in AGENTS:
        agents.append(
            {
                **a,
                "activity_count": sum(rule_counts.get(r, 0) for r in a["rules"]),
            }
        )

    return {
        "agents": agents,
        "edges": EDGES,
        "rule_activity": rule_counts,
        "externals": [
            {"id": "learner", "name": "Người học"},
            {"id": "kb", "name": "Cơ sở tri thức (PostgreSQL)"},
        ],
    }
