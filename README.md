# KBS - Hệ thống Kiểm tra Tri thức Thông minh

Hệ thống quản lý, kiểm tra tri thức và hỗ trợ giải bài tập thông minh dựa trên **Mô hình tri thức quan hệ (Rela-model)**, **Ontology** và **IRT (Item Response Theory)**.

## Kiến trúc

```
┌─────────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Next.js Frontend  │────▶│  FastAPI Backend  │────▶│   PostgreSQL    │
│   (Port 3000)       │     │  (Port 8000)      │     │   (Port 5432)   │
└─────────────────────┘     └──────────────────┘     └─────────────────┘
        │                           │
        │                    ┌──────┴──────┐
        │                    │ IRT Engine  │
        │                    │ (3PL Model) │
        │                    └─────────────┘
        │
  ┌─────┴──────────────────────────────┐
  │  Pages:                            │
  │  • Dashboard (Radar chart)         │
  │  • Bản đồ Tri thức (Ontology)     │
  │  • Làm bài thi (Timer + Adaptive) │
  │  • Kết quả (Chi tiết + Scores)    │
  └────────────────────────────────────┘
```

## Cấu trúc Tri thức (Rela-model)

- **C (Concepts):** Môn học → Chủ đề lớn → Topic
- **R (Relations):** Phân cấp + Tiên quyết (Prerequisite)
- **Rules:** IRT 3PL với tham số a (phân biệt), b (độ khó), c (đoán mò)

## Khởi chạy nhanh

### Với Docker Compose (khuyến nghị)

```bash
# 0. Đứng tại thư mục gốc project (BDTT)
cd /path/to/BDTT

# 1. Khởi động tất cả services
docker compose up -d
# Nếu máy không có subcommand `docker compose`, dùng: docker-compose up -d

# 2. Import dữ liệu từ Excel
docker compose exec backend python -m app.data.seed /data/MaTranKienThuc.xlsx

# 3. Truy cập
# Frontend: http://localhost:3000
# API docs: http://localhost:8000/docs
```

### Chạy thủ công (development)

```bash
# 0. Đứng tại thư mục gốc project (BDTT)
cd /path/to/BDTT

# 1. Database
# Cài PostgreSQL và tạo DB/user theo backend/.env
# Ví dụ mặc định:
#   database: kbs_db
#   user: kbs_user
#   password: kbs_pass

# 2. Backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 3. Import data (mở terminal khác)
# terminal 2:
cd /path/to/BDTT
source .venv/bin/activate
cd backend
python -m app.data.seed ../MaTranKienThuc.xlsx

# 4. Frontend
# terminal 3:
cd /path/to/BDTT
cd frontend
npm install
npm run dev
```

## API Endpoints

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| POST | `/api/auth/register` | Đăng ký |
| POST | `/api/auth/login` | Đăng nhập |
| GET | `/api/auth/me` | Thông tin user |
| GET | `/api/knowledge/subjects` | Danh sách môn học |
| GET | `/api/knowledge/subjects/:id/tree` | Cây Ontology |
| GET | `/api/knowledge/topics` | Danh sách topic |
| POST | `/api/quiz/start` | Tạo bài thi |
| POST | `/api/quiz/start-cat` | Bắt đầu phiên CAT; ưu tiên câu mở đầu có `b≈0`, `a` cao, và có thể bootstrap bằng LLM nếu ngân hàng ban đầu thiếu item |
| POST | `/api/quiz/:id/answer` | Trả lời 1 câu và lấy câu tiếp theo theo rule-based filtering + Fisher; có thể trigger Hybrid CAT + LLM khi thiếu câu phù hợp |
| POST | `/api/quiz/generate-question` | Sinh câu hỏi bằng LLM + pre-label a,b,c |
| GET | `/api/quiz/evaluation/difficulty-calibration` | Báo cáo calibration theo độ khó |
| GET | `/api/quiz/:id/questions` | Lấy câu hỏi |
| POST | `/api/quiz/:id/submit` | Nộp bài |
| GET | `/api/quiz/:id/results` | Kết quả chi tiết |
| GET | `/api/users/dashboard` | Dashboard user |

## IRT Engine

Sử dụng **3PL Model** (Three-Parameter Logistic):

$$P(\theta) = c + \frac{1-c}{1 + e^{-a(\theta - b)}}$$

- **θ (theta):** Năng lực người dùng
- **a:** Độ phân biệt câu hỏi
- **b:** Độ khó câu hỏi  
- **c:** Xác suất đoán mò

### Thuật toán chọn câu hỏi
1. **Static:** Phân bổ theo tỷ lệ Nhận biết/Thông hiểu/Vận dụng
2. **Adaptive CAT:** Kết hợp rule-based filtering với Maximum Fisher Information tại θ hiện tại
3. **Early CAT Heuristic:** Trong vài câu đầu, shortlist các câu có độ phân biệt `a` cao trước khi chốt bằng Fisher
4. **Hybrid Triggered by CAT:** Khi ngân hàng không còn item phù hợp hoặc không đủ item để mở phiên, hệ thống có thể tự sinh câu mới bằng LLM

### Luồng Hybrid Triggered by CAT (mới)

Mục tiêu: giải quyết niche case khi CAT cần item phù hợp nhưng question bank hiện tại chưa đáp ứng đủ, cả ở thời điểm mở phiên lẫn giữa phiên.

#### 0) Câu mở đầu CAT
- Engine ưu tiên câu mở đầu có `b` gần 0 và `a > 1.2`.
- Nếu không có item thỏa điều kiện này, hệ thống shortlist các câu có `a` cao rồi chọn theo Fisher Information tại `θ = 0`.
- Nếu subject/topic ban đầu chưa có item khả dụng, backend có thể bootstrap một câu mới bằng LLM để khởi động phiên CAT.

#### 1) CAT cập nhật năng lực
- Sau mỗi câu trả lời, engine tính lại năng lực hiện tại $\theta$ và độ bất định (SEM).

#### 2) Tìm câu phù hợp trong PostgreSQL
- Hệ thống loại các câu đã trả lời và ưu tiên tránh lặp lại các câu vừa làm ở các phiên gần đây.
- Rule engine lọc trước các ứng viên phù hợp theo ngữ cảnh hiện tại.
- Ở bước lõi R3, hệ thống tạo một dải độ khó quanh $\theta$, rồi chọn câu có Fisher Information cao nhất trong tập ứng viên đã lọc.
- Nếu đang ở vài câu đầu, tập ứng viên này tiếp tục được shortlist theo `a` cao trước khi chốt bằng Fisher.

#### 3) Trigger LLM khi thiếu câu phù hợp
- Nếu không còn item đủ phù hợp quanh $\theta$ hoặc ngân hàng ban đầu quá nghèo, hệ thống kích hoạt nhánh Hybrid.
- Chọn topic ưu tiên theo tỷ lệ sai cao hoặc topic vừa làm gần nhất.
- Tạo context tri thức từ Ontology:
  - Topic hiện tại
  - Các topic tiên quyết (prerequisite)

Ví dụ prompt mục tiêu:
"Dựa trên chủ đề Mệnh đề kéo theo, hãy sinh 1 câu hỏi có độ khó $b=1.2$ (Vận dụng), với tham số dự kiến $a=1.5, c=0.2$."

#### 4) Zero-shot LLM validation
- Sau khi sinh câu hỏi, hệ thống gọi bước self-validation bằng LLM:
  - Tự giải lại câu hỏi
  - Kiểm tra đáp án giải được có khớp đáp án đã sinh không
  - Ước lượng lại độ khó $\hat{b}$ từ số bước suy luận và độ chắc chắn
- Chỉ chấp nhận câu hỏi nếu:
  - Câu hợp lệ về cấu trúc/nội dung
  - Đáp án self-solve khớp đáp án chuẩn
  - $|\hat{b}-b_{target}|$ nằm trong ngưỡng chấp nhận

#### 5) Persist và tái sử dụng
- Câu hỏi đạt chuẩn được lưu vào PostgreSQL question bank.
- Câu này được dùng ngay làm item mở đầu hoặc "next item" cho phiên CAT hiện tại.
- Đồng thời trở thành dữ liệu dùng lại cho các phiên sau.

#### 6) Fallback an toàn
- Nếu LLM lỗi hoặc validation không đạt sau số lần thử cho phép, hệ thống fallback sang generator nội bộ để không gián đoạn phiên làm bài.

### Ước lượng năng lực
- **EAP (Expected A Posteriori):** Ổn định với ít câu trả lời
- **MLE (Maximum Likelihood):** Newton-Raphson iteration

## Dữ liệu

- **300 câu hỏi** (150 SQL + 150 Toán rời rạc)
- **8 chủ đề lớn**, **25 chủ đề con**
- Mỗi câu có tham số IRT (a, b, c) và thời gian giới hạn

## Cấu hình LLM

Hệ thống hỗ trợ kết nối API dạng OpenAI-compatible để sinh câu hỏi.

Runtime config cho LLM được quản lý trong database và chỉnh qua UI admin tại `/admin/settings`.

Các trường runtime sau không còn lấy từ `backend/.env` khi ứng dụng chạy:

- `LLM_ENABLED`
- `CAT_ENABLE_HYBRID_LLM_ON_ANSWER`
- `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_TEMPERATURE`
- `LLM_TIMEOUT_SECONDS`

Khi database chưa có bản ghi cấu hình đầu tiên, backend sẽ tự khởi tạo một row mặc định trong bảng `llm_runtime_config`, sau đó mọi thay đổi runtime đều đi qua DB.

System prompt mặc định được bootstrap từ [backend/prompts/question_generator.system.md](/home/hunghn/code_uit_mcs/BDTT/backend/prompts/question_generator.system.md) vào DB. Sau lần khởi tạo đầu tiên, admin có thể chỉnh trực tiếp system prompt trên UI tại `/admin/settings`.

Biến môi trường còn dùng cho phần LLM chỉ gồm:

```env
LLM_API_KEY=YOUR_API_KEY
LLM_SYSTEM_PROMPT_PATH=prompts/question_generator.system.md
```

- `LLM_API_KEY` là secret bắt buộc cho kết nối LLM.
- Hệ thống hỗ trợ nhập `LLM_API_KEY` trên UI admin. API sẽ không trả secret này về client; chỉ trả trạng thái đã có key hay chưa.
- Nếu DB chưa có `llm_api_key`, backend sẽ bootstrap từ `LLM_API_KEY` trong env để tương thích với cấu hình cũ.
- `LLM_SYSTEM_PROMPT_PATH` là nguồn bootstrap cho system prompt mặc định trước khi prompt được lưu trong DB.
- Nếu LLM lỗi/kết nối thất bại, hệ thống tự động fallback sang generator nội bộ để không gián đoạn API.

### API admin cho runtime config

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/api/admin/settings/llm` | Lấy runtime config hiện tại từ DB |
| PUT | `/api/admin/settings/llm` | Cập nhật runtime config trong DB |

Runtime config trong admin hiện bao gồm:

- Bật/tắt LLM tổng thể
- Bật/tắt Hybrid CAT sinh câu hỏi trong luồng trả lời
- API key và system prompt cho LLM
- Base URL, model, temperature, timeout
