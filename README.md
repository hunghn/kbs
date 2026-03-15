# KBS - Hệ thống Kiểm tra Tri thức Thông minh

KBS là hệ thống quản lý tri thức và kiểm tra năng lực học tập dựa trên mô hình tri thức quan hệ, ontology và IRT 3PL. Hệ thống tập trung vào hai miền tri thức chính là Toán rời rạc và Cơ sở dữ liệu SQL, đồng thời hỗ trợ CAT (Computerized Adaptive Testing) để chọn câu hỏi thích ứng theo năng lực người học.

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
- Rule engine điều phối CAT theo bộ luật R1-R12 và BLOOM
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

- Ưu tiên item có độ khó khởi tạo an toàn, cụ thể `b ∈ [-1.5, -0.5]`.
- Trong nhóm này, ưu tiên item có độ phân biệt cao `a > 1.2` để hội tụ nhanh năng lực ban đầu.
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
- Rule engine lọc tập ứng viên theo ngữ cảnh hiện tại (bao phủ topic, prerequisite, năng lực cao, đoán mò).
- Hệ thống thiết lập `b_target` theo kết quả câu trước (`+0.5` nếu đúng, `-0.7` nếu sai) để điều hướng độ khó.
- Trong vài bước đầu, engine ưu tiên shortlist các câu có `a` cao để phân loại nhanh.
- Khi không đủ item phù hợp quanh `b_target`, hệ thống kích hoạt LLM để sinh item động.
- Nếu các luật không chọn được item, hệ thống fallback sang chọn theo Fisher Information.

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

- IF `số_câu_đã_làm == 0`
- THEN ưu tiên chọn câu có `b ∈ [-1.5, -0.5]` và `a > 1.2` trong môn học hiện tại.
- Nếu có nhiều ứng viên, chọn theo Fisher Information tại $\theta = 0$.
- Nếu không có ứng viên phù hợp, fallback qua shortlist `a` cao, rồi Fisher toàn cục.

### R2. Luật tăng độ khó

- IF `User_Answer == Correct_Answer`
- THEN đặt `b_target = theta_current + 0.5`.
- Mục tiêu: tăng độ khó có kiểm soát theo năng lực vừa cập nhật.

### R3. Luật giảm độ khó

- IF `User_Answer != Correct_Answer`
- THEN đặt `b_target = theta_current - 0.7`.
- Mục tiêu: giảm độ khó đủ mạnh để tránh chuỗi thất bại liên tiếp.

### R4. Luật tối ưu giai đoạn đầu

- IF `2 <= số_câu_đã_làm <= 5`
- THEN ưu tiên sắp xếp ứng viên theo `a DESC` trước khi chọn câu kế tiếp.
- Mục tiêu: hội tụ nhanh $\theta$ ở pha thăm dò sớm, nhưng tránh kích hoạt ngay sau câu đầu tiên.

### R5. Luật chuyển topic để đảm bảo bao phủ ontology

- IF `số_câu_đúng_liên_tiếp(Topic_X) >= 3`
- THEN lọc ứng viên với `Topic != Topic_X` để chuyển sang topic ngang hàng.
- Mục tiêu: tránh overfit vào một topic và đảm bảo độ bao phủ tri thức.

### R6. Luật lọc trình độ cao

- IF `theta > 1.0` AND `số_câu_đã_làm >= 3` AND `SEM < 1.0`
- THEN loại trừ các câu `Nhận biết` khỏi tập ứng viên.
- Mục tiêu: chỉ nâng chuẩn khi vừa đủ dữ liệu và độ tin cậy ước lượng năng lực.

### R7. Luật kiểm soát đoán mò

- IF `User_Answer == Correct` AND `Thời_gian_làm < 10s` AND `c > 0.2`
- THEN coi là có khả năng đoán mò và giảm trọng số cập nhật năng lực (damp theta update).
- Mục tiêu: tránh thổi phồng năng lực do đáp án may mắn.

### R8. Luật ràng buộc lặp

- Luôn loại các câu đã trả lời trong phiên hiện tại khỏi tập ứng viên.
- IF tồn tại lịch sử câu gần nhất `cross-session` (cùng user, cùng môn)
- THEN tiếp tục loại các câu đó khỏi tập ứng viên và ghi log `R8`.
- Mục tiêu: chống trùng lặp thực sự giữa các phiên làm bài liên tiếp, tránh log nhiễu ở bước đầu tiên.

### R9. Luật kích hoạt sinh câu hỏi mới bằng LLM

- IF số item phù hợp quanh `b_target` trong DB không đủ (hoặc `min_gap` quá lớn)
- THEN kích hoạt pipeline sinh câu hỏi động theo topic ưu tiên.
- Mục tiêu: đảm bảo CAT không bị kẹt do thiếu item phù hợp.

### R10. Luật gán độ khó cho câu hỏi LLM

- IF câu hỏi mới được sinh bởi LLM
- THEN dùng cơ chế scoring/validation để gán `b_dự_kiến` theo độ phức tạp suy luận.
- Mục tiêu: giữ nhất quán IRT giữa item tĩnh và item sinh động.

### R11. Luật tiên quyết (Prerequisite Fallback)

- IF `User_Fail_Consecutive(Topic_X) >= 2` AND tồn tại `Topic_Y` là tiên quyết của `Topic_X`
- THEN chuyển tạm sang `Topic_Y` và ưu tiên câu dễ (`b ≈ -1.0`) để củng cố nền tảng.
- Mục tiêu: xử lý bế tắc tri thức theo quan hệ tiên quyết trong ontology.

### R12. Luật suy diễn Mạng tính toán (Computation Network)

- IF người học đã thể hiện mastery ở `Topic_A` và `Topic_B`
- AND trong đồ thị tri thức có quan hệ suy diễn `A, B -> C`
- THEN tăng `theta` khởi tạo cho `Topic_C` và có thể bỏ qua một phần câu `Nhận biết` của `Topic_C`.
- Mục tiêu: suy diễn năng lực gián tiếp để rút ngắn lộ trình đánh giá.

### BLOOM. Luật phân loại kết quả nổi trội

- IF $\theta > 1.5$ và độ chính xác nhóm `Vận dụng` > 80%
- THEN gắn nhãn năng lực nổi trội trong báo cáo kết quả.
- Luật này phục vụ diễn giải đầu ra, không dùng để chọn câu tiếp theo.

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
cd /path/to/kbs
docker compose up -d
docker compose exec backend python -m app.data.seed /data/MaTranKienThuc.xlsx
```

Sau khi chạy:

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs

### Chạy thủ công trong môi trường phát triển

```bash
cd /path/to/kbs

python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Terminal khác để import dữ liệu:

```bash
cd /path/to/kbs
source .venv/bin/activate
cd backend
python -m app.data.seed ../MaTranKienThuc.xlsx
```

Terminal khác để chạy frontend:

```bash
cd /path/to/kbs/frontend
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
