# KBS - Hệ thống Kiểm tra Tri thức Thông minh

KBS là hệ thống quản lý tri thức và kiểm tra năng lực học tập dựa trên mô hình tri thức quan hệ, ontology và IRT 3PL. Hệ thống tập trung vào hai miền tri thức chính là Toán rời rạc và Cơ sở dữ liệu SQL, đồng thời hỗ trợ CAT để chọn câu hỏi thích ứng theo năng lực người học.

## Tổng quan

Mục tiêu của hệ thống:

- Quản lý ngân hàng câu hỏi theo môn học, chủ đề lớn và topic.
- Tổ chức tri thức theo cấu trúc ontology và quan hệ tiên quyết.
- Đánh giá năng lực người học bằng tham số $\theta$ trong IRT 3PL.
- Chọn câu hỏi kế tiếp theo cơ chế CAT kết hợp rule-based filtering và Fisher Information.
- Sinh bổ sung câu hỏi bằng LLM khi question bank chưa đủ item phù hợp.
- Trả kết quả chi tiết, tiến trình năng lực và gợi ý học lại kiến thức nền.

## Kiến trúc hệ thống

```text
┌─────────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Next.js Frontend  │────▶│  FastAPI Backend │────▶│   PostgreSQL    │
│   (Port 3000)       │     │  (Port 8000)     │     │   (Port 5432)   │
└─────────────────────┘     └──────────────────┘     └─────────────────┘
        │                           │
        │                    ┌──────┴──────┐
        │                    │  IRT Engine │
        │                    │  + Rule CAT │
        │                    └──────┬──────┘
        │                           │
        │                    ┌──────┴──────┐
        │                    │ LLM Runtime │
        │                    │ + Validation│
        │                    └─────────────┘
```

### Frontend

- Next.js App Router
- Giao diện làm bài CAT theo thời gian thực
- Dashboard theo dõi năng lực và tiến độ học tập
- Trang quản trị cấu hình runtime cho LLM
- Trang quản lý ngân hàng câu hỏi

### Backend

- FastAPI REST API
- SQLAlchemy Async ORM
- Engine IRT 3PL để ước lượng năng lực và tính Fisher Information
- Rule engine điều phối CAT theo các luật R1-R7
- Pipeline sinh và thẩm định câu hỏi bằng LLM

### Database

- PostgreSQL lưu ontology, question bank, session làm bài, kết quả, rule logs và runtime config

## Mô hình tri thức

Hệ thống biểu diễn tri thức theo Rela-model:

- C (Concepts): Môn học → Chủ đề lớn → Topic
- R (Relations): Quan hệ phân cấp và quan hệ tiên quyết
- Rules: Các luật suy diễn áp dụng trong chọn câu hỏi và diễn giải kết quả

## Luồng vận hành của hệ thống

### 1. Khởi tạo dữ liệu

- Dữ liệu câu hỏi được import từ file Excel vào PostgreSQL.
- Mỗi câu hỏi chứa nội dung, đáp án, topic, loại câu hỏi và các tham số IRT `a`, `b`, `c`.
- Môn học, chủ đề lớn và topic được tổ chức thành ontology để phục vụ điều hướng tri thức.

### 2. Người dùng bắt đầu làm bài

- Người dùng đăng nhập và chọn một môn học.
- Backend tạo `QuizSession` cho môn đã chọn.
- Với bài thi CAT, hệ thống chọn câu mở đầu theo tập luật khởi tạo.

### 3. Hệ thống chọn câu hỏi đầu tiên

- Ưu tiên item có độ khó gần mức trung tâm, cụ thể là `b` gần `0`.
- Trong nhóm này, ưu tiên item có độ phân biệt cao `a > 1.2`.
- Nếu không có item thỏa điều kiện, hệ thống shortlist các item có `a` cao rồi chọn item có Fisher Information lớn nhất tại $\theta = 0$.
- Nếu question bank ban đầu không có item khả dụng, backend có thể sinh một câu mới bằng LLM để mở phiên CAT.

### 4. Người dùng trả lời câu hỏi

- Frontend gửi đáp án và thời gian làm bài.
- Backend ghi nhận `QuizResponse`.
- Engine IRT cập nhật lại năng lực $\theta$ và độ bất định SEM.
- Rule engine xác định luật nào đang tác động đến bước hiện tại.
- Hệ thống chọn câu kế tiếp hoặc kết thúc phiên nếu đạt điều kiện dừng.

### 5. Hệ thống chọn câu tiếp theo

- Loại bỏ các câu đã trả lời trong phiên hiện tại.
- Ưu tiên tránh lặp lại các câu vừa xuất hiện ở các phiên gần đây của cùng người dùng và cùng môn.
- Rule engine lọc tập ứng viên theo ngữ cảnh hiện tại.
- Trên tập ứng viên đã lọc, hệ thống chọn item có Fisher Information cao nhất tại $\theta$ hiện tại.
- Trong vài bước đầu, engine ưu tiên shortlist các câu có `a` cao trước khi chốt bằng Fisher.

### 6. Hệ thống sinh câu bằng LLM khi cần

- Nếu question bank không còn item đủ phù hợp cho CAT, backend xác định topic ưu tiên.
- Tạo context từ topic hiện tại và các topic tiên quyết.
- Gọi LLM để sinh câu hỏi theo mục tiêu IRT.
- Gọi bước self-validation để kiểm tra chất lượng và tính nhất quán của câu hỏi.
- Nếu đạt điều kiện, câu hỏi được lưu vào question bank và dùng ngay cho phiên hiện tại.
- Nếu không đạt điều kiện, hệ thống fallback sang generator nội bộ.

### 7. Kết thúc phiên và sinh báo cáo

Phiên CAT dừng khi thỏa một trong các điều kiện sau:

- `SEM < 0.3`
- đạt số câu tối đa
- không còn item phù hợp

Sau khi kết thúc, hệ thống trả về:

- điểm số và độ chính xác
- giá trị $\theta$
- lịch sử thay đổi $\theta$
- các rule đã được áp dụng
- gợi ý học lại kiến thức nền
- thống kê theo topic

## IRT 3PL và CAT

### Công thức xác suất trả lời đúng

$$
P(\theta) = c + \frac{1-c}{1 + e^{-a(\theta - b)}}
$$

Trong đó:

- $\theta$: năng lực hiện tại của người học
- $a$: độ phân biệt của câu hỏi
- $b$: độ khó của câu hỏi
- $c$: xác suất đoán mò

### Nguyên tắc chọn câu hỏi trong CAT

1. Áp dụng các luật điều hướng nội dung trước.
2. Thu hẹp tập ứng viên theo trạng thái hiện tại của phiên làm bài.
3. Trên tập ứng viên còn lại, chọn item có Fisher Information cao nhất tại $\theta$.
4. Trong những câu đầu, ưu tiên item có `a` cao để ước lượng năng lực nhanh hơn.

## Các luật suy diễn của CAT

### R1. Luật khởi tạo phiên CAT

- Mục tiêu: chọn câu đầu tiên có độ khó trung tâm và khả năng phân loại tốt.
- Điều kiện ưu tiên: `|b| <= 0.4` và `a > 1.2`.
- Nếu có nhiều ứng viên, chọn theo Fisher Information tại $\theta = 0$.

### R2. Luật nâng mức trong cùng topic

- Nếu người học trả lời đúng một câu `Nhận biết`, hệ thống ưu tiên câu `Thông hiểu` trong cùng topic.
- Mục tiêu là giữ mạch kiến thức và tăng dần mức độ nhận thức.

### R3. Luật chọn item lõi của CAT

- Hệ thống tạo một dải độ khó quanh $\theta$ hiện tại.
- Trên dải ứng viên đó, chọn item có Fisher Information cao nhất.
- Trong vài câu đầu, có thêm bước shortlist các item có `a` cao trước khi chọn bằng Fisher.

### R4. Luật cân bằng nội dung SQL và non-SQL

- Nếu tỷ lệ câu SQL trong lịch sử phiên quá cao, CAT ưu tiên chuyển sang câu non-SQL.
- Mục tiêu là giữ cân bằng nội dung trong phiên đánh giá.

### R5. Luật hỗ trợ khi người học yếu ở SQL

- Nếu sau hơn 3 câu mà độ chính xác ở nhóm SQL dưới 50%, CAT ưu tiên một câu SQL dễ hơn với mục tiêu gần `theta - 0.5`.
- Mục tiêu là duy trì khả năng đo lường nhưng không đẩy người học vào chuỗi thất bại kéo dài.

### R6. Luật phát hiện khả năng đoán mò

- Nếu người học trả lời đúng quá nhanh trên một câu có `c` cao, hệ thống gắn cờ khả năng đoán mò.
- Khi đó, mức tăng của $\theta$ được làm dịu để tránh đánh giá quá cao năng lực thực.

### R7. Luật phân loại kết quả nổi trội

- Nếu $\theta > 1.5$ và độ chính xác ở nhóm `Vận dụng` vượt 80%, hệ thống gắn phân loại kết quả ở mức rất tốt.
- Luật này phục vụ diễn giải đầu ra và báo cáo học tập.

## Hybrid CAT với LLM

### Thời điểm kích hoạt

- Khi question bank không đủ item để mở phiên CAT.
- Khi đang giữa phiên nhưng question bank không còn item phù hợp quanh $\theta$.

### Quy trình sinh câu hỏi

1. Xác định topic ưu tiên.
2. Tạo context từ topic hiện tại và các topic tiên quyết.
3. Gọi LLM để sinh câu hỏi với mục tiêu `a`, `b`, `c`.
4. Tự thẩm định câu hỏi bằng LLM.
5. Persist câu hỏi vào PostgreSQL nếu đạt yêu cầu.
6. Dùng câu hỏi đó làm item mở đầu hoặc item kế tiếp của phiên CAT.

### Cơ chế an toàn

- Nếu LLM lỗi hoặc câu hỏi không đạt chuẩn, backend fallback sang generator nội bộ.
- Mục tiêu là không làm gián đoạn phiên làm bài.

## Dashboard và kết quả học tập

Sau mỗi phiên, hệ thống có thể cung cấp:

- điểm số và độ chính xác
- giá trị $\theta$
- lịch sử thay đổi $\theta$
- danh sách rule được áp dụng
- gợi ý học lại topic tiên quyết
- thống kê theo topic

## API chính

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| POST | `/api/auth/register` | Đăng ký tài khoản |
| POST | `/api/auth/login` | Đăng nhập |
| GET | `/api/auth/me` | Lấy thông tin người dùng |
| GET | `/api/knowledge/subjects` | Lấy danh sách môn học |
| GET | `/api/knowledge/subjects/:id/tree` | Lấy cây ontology của môn học |
| GET | `/api/knowledge/topics` | Lấy danh sách topic |
| POST | `/api/quiz/start` | Tạo bài thi tĩnh theo phân bổ loại câu hỏi |
| POST | `/api/quiz/start-cat` | Bắt đầu phiên CAT |
| POST | `/api/quiz/:id/answer` | Gửi đáp án một câu CAT và lấy câu tiếp theo |
| POST | `/api/quiz/generate-question` | Sinh bản nháp câu hỏi theo topic bằng LLM |
| GET | `/api/quiz/evaluation/difficulty-calibration` | Báo cáo calibration theo độ khó |
| GET | `/api/quiz/:id/questions` | Lấy danh sách câu hỏi của phiên tĩnh |
| POST | `/api/quiz/:id/submit` | Nộp bài thi tĩnh |
| GET | `/api/quiz/:id/results` | Lấy kết quả chi tiết |
| GET | `/api/quiz/:id/rule-logs` | Lấy log các rule đã áp dụng trong CAT |
| GET | `/api/users/dashboard` | Lấy dữ liệu dashboard của người dùng |

## Dữ liệu

- 300 câu hỏi ban đầu
- 150 câu SQL
- 150 câu Toán rời rạc
- 8 chủ đề lớn
- 25 chủ đề con
- Mỗi câu hỏi có tham số IRT `a`, `b`, `c` và thời gian làm bài

## Khởi chạy nhanh

### Chạy bằng Docker Compose

```bash
cd /path/to/BDTT
docker compose up -d
docker compose exec backend python -m app.data.seed /data/MaTranKienThuc.xlsx
```

Sau khi chạy:

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs

### Chạy thủ công trong môi trường phát triển

```bash
cd /path/to/BDTT

python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Terminal khác để import dữ liệu:

```bash
cd /path/to/BDTT
source .venv/bin/activate
cd backend
python -m app.data.seed ../MaTranKienThuc.xlsx
```

Terminal khác để chạy frontend:

```bash
cd /path/to/BDTT/frontend
npm install
npm run dev
```

## Cấu hình LLM

Runtime config của LLM được lưu trong database và quản lý từ UI admin tại `/admin/settings`.

Các cấu hình runtime được chỉnh trên UI gồm:

- `LLM_ENABLED`
- `CAT_ENABLE_HYBRID_LLM_ON_ANSWER`
- `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_TEMPERATURE`
- `LLM_TIMEOUT_SECONDS`
- `LLM_API_KEY`
- `LLM_SYSTEM_PROMPT`

Khi database chưa có bản ghi runtime config đầu tiên, backend sẽ khởi tạo giá trị mặc định và bootstrap các thành phần cần thiết từ cấu hình môi trường hoặc file prompt.

Biến môi trường còn phục vụ cho bootstrap và cấu hình hạ tầng:

```env
LLM_API_KEY=YOUR_API_KEY
LLM_SYSTEM_PROMPT_PATH=prompts/question_generator.system.md
```

Giải thích:

- `LLM_API_KEY` là secret dùng để gọi LLM.
- API admin không trả lại giá trị thô của API key về client.
- `LLM_SYSTEM_PROMPT_PATH` là nguồn bootstrap nội dung prompt mặc định trước khi prompt được lưu vào DB.

### API admin cho runtime config

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/api/admin/settings/llm` | Lấy runtime config hiện tại |
| PUT | `/api/admin/settings/llm` | Cập nhật runtime config |

## Cấu trúc thư mục chính

```text
backend/
  app/
    api/            # REST API
    engine/         # IRT, CAT selector, scoring, LLM generation
    models/         # SQLAlchemy models
    schemas/        # Pydantic schemas
    services/       # Runtime settings và service logic
  prompts/          # Prompt bootstrap cho LLM

frontend/
  app/              # Next.js routes
  components/       # UI components
  lib/              # API client và helper
```

## Ghi chú vận hành

- CAT là phiên làm bài theo một môn học cụ thể, không đổi môn giữa phiên.
- Rule logs được lưu để giải thích vì sao hệ thống chọn một câu hỏi tiếp theo.
- Các câu hỏi sinh bởi LLM có thể được lưu lại để tái sử dụng ở các phiên sau.
- Frontend cho phép người dùng gửi lại đáp án nếu lần submit trước gặp lỗi mạng hoặc lỗi API.
