# KBS - Hệ thống Kiểm tra Tri thức Thông minh

KBS là hệ thống quản lý tri thức và kiểm tra năng lực học tập dựa trên mô hình tri thức quan hệ, ontology và IRT 3PL. Hệ thống tập trung vào hai miền tri thức chính là Toán rời rạc và Cơ sở dữ liệu SQL, đồng thời hỗ trợ kiểm tra thích ứng **theo đề** (multi-stage adaptive testing): người học làm trọn từng đề thi, hệ thống đánh giá cả đề rồi dùng bộ luật suy diễn để sinh đề kế tiếp phù hợp với năng lực.

## Tổng quan

Mục tiêu của hệ thống:

- Quản lý ngân hàng câu hỏi theo môn học, chủ đề lớn và topic.
- Tổ chức tri thức theo cấu trúc ontology và quan hệ tiên quyết.
- Đánh giá năng lực người học bằng tham số $\theta$ trong IRT 3PL.
- Sinh đề thi kế tiếp theo cơ chế multi-stage testing: rule-based filtering (R1-R12) kết hợp Fisher Information, hoặc chiến lược Reinforcement Learning.
- Ước lượng năng lực và độ bất định bằng Bayesian EAP tích lũy trên toàn chuỗi đề (độ bất định expose qua trường `sem`, bản chất là posterior SD).
- Dự đoán năng lực theo thời gian thực bằng Deep Knowledge Tracing.
- Giải thích kết quả đánh giá bằng mô-đun Explainable AI.
- Sinh bổ sung câu hỏi bằng LLM khi question bank chưa đủ item phù hợp.
- Trả kết quả chi tiết, tiến trình năng lực, đồ thị tri thức năng lực cá nhân và gợi ý học lại kiến thức nền.

> Lưu ý: các mô tả "chọn từng câu kế tiếp" trong phần luồng vận hành bên dưới là thiết kế
> gốc; từ bản nâng cấp 2026, các luật R1-R12 được áp dụng **ở cấp độ đề** — xem mục
> "Các mô-đun nâng cấp (Project 2 – 2026)".

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
- Engine IRT 3PL: dùng Fisher Information cho chọn câu hỏi và Bayesian EAP cho ước lượng năng lực/độ bất định
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
- Engine IRT cập nhật lại năng lực $\theta$ và độ bất định theo Bayesian EAP (posterior SD, hiện trả qua trường `sem`).
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

- `sem < 0.3` (giá trị `sem` hiện là posterior SD từ Bayesian EAP)
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
P(\theta) = c + \frac{1-c}{1 + e^{-D\,a(\theta - b)}},\quad D = 1.702
$$

Trong đó:

- $\theta$: năng lực hiện tại của người học
- $a$: độ phân biệt của câu hỏi
- $b$: độ khó của câu hỏi
- $c$: xác suất đoán mò

### Ước lượng năng lực và độ bất định

- Hệ thống dùng Bayesian EAP để ước lượng $\theta$.
- Độ bất định được lấy từ posterior SD và trả về qua trường API `sem` để tương thích ngược.
- Fisher Information vẫn được dùng chủ yếu cho bài toán chọn item trong CAT, không phải nguồn chính để xuất độ bất định cuối cùng ở báo cáo.

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

- IF `theta > 1.0` AND `số_câu_đã_làm >= 3` AND `sem < 1.0` (trong đó `sem` là posterior SD)
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
| POST | `/api/quiz/adaptive/start` | Tạo chuỗi đề thích ứng và sinh đề #1 (luật R1) |
| POST | `/api/quiz/adaptive/:chainId/submit` | Nộp trọn một đề, chấm và cập nhật θ/SEM tích lũy |
| POST | `/api/quiz/adaptive/:chainId/next` | Sinh đề kế tiếp theo luật R1-R12 (hoặc RL) |
| POST | `/api/quiz/adaptive/:chainId/finish` | Người dùng kết thúc chuỗi đề |
| GET | `/api/quiz/adaptive/:chainId` | Trạng thái chuỗi đề (resume đề đang dở) |
| GET | `/api/quiz/adaptive/:chainId/summary` | Báo cáo tổng kết toàn chuỗi đề |
| GET | `/api/quiz/adaptive/rl-policy` | Q-table của bandit điều hướng độ khó |
| POST | `/api/quiz/dkt/train` | Huấn luyện mô hình Deep Knowledge Tracing cho môn học |
| GET | `/api/users/ability-prediction` | Dự đoán DKT: P(đúng câu tiếp theo) theo từng topic |
| GET | `/api/quiz/:id/explanation` | Explainable AI: phân rã Δθ, Fisher Information, narrative |
| GET | `/api/quiz/evaluation/convergence` | Mô phỏng đánh giá độ hội tụ năng lực giữa các chiến lược |
| POST | `/api/quiz/generate-question` | Sinh bản nháp câu hỏi theo topic bằng LLM |
| GET | `/api/quiz/evaluation/difficulty-calibration` | Báo cáo calibration theo độ khó |
| GET | `/api/quiz/:id/questions` | Lấy danh sách câu hỏi của phiên tĩnh |
| POST | `/api/quiz/:id/submit` | Nộp bài thi tĩnh |
| GET | `/api/quiz/:id/results` | Lấy kết quả chi tiết |
| GET | `/api/quiz/:id/rule-logs` | Lấy log các rule đã áp dụng khi sinh đề/chấm đề |
| GET | `/api/knowledge/subjects/:id/ability-graph` | Đồ thị tri thức năng lực cá nhân (kèm tầng Kỹ năng) |
| GET | `/api/users/learning-path` | Lộ trình học đề xuất theo đồ thị tiên quyết |
| GET | `/api/users/dashboard` | Lấy dữ liệu dashboard của người dùng |

## Các mô-đun nâng cấp (Project 2 – 2026)

### So sánh với phiên bản trước (điểm khác biệt, mở rộng)

| Khía cạnh | Phiên bản trước (nhánh 1.0) | Phiên bản Project 2 (nhánh 2.0) |
|---|---|---|
| Cơ chế thích ứng | CAT chọn **từng câu** sau mỗi lần trả lời | **Multi-stage testing theo đề**: chấm cả đề rồi sinh đề kế tiếp |
| Phạm vi áp dụng luật R1-R12 | Cấp độ câu hỏi | Cấp độ đề thi (blueprint, dành slot, lọc pool) |
| Ước lượng năng lực | Bayesian EAP trong một phiên | EAP **tích lũy trên toàn chuỗi đề** + damping R7 |
| Dự đoán năng lực theo thời gian | Không có | **Deep Knowledge Tracing** (RNN, numpy thuần) |
| Chiến lược điều hướng độ khó | Luật R2/R3 cố định | R2/R3 **hoặc Reinforcement Learning** (contextual bandit, reward = ΔSEM) |
| Giải thích kết quả | Chỉ rule logs khi chọn câu | **Explainable AI**: Δθ từng câu, Fisher share, narrative tiếng Việt |
| Ontology | Môn học → Chủ đề lớn → Topic + Bloom + độ khó | Bổ sung **tầng Kỹ năng** (2 kỹ năng/topic, đo qua nhóm Bloom) |
| Trực quan hóa năng lực | Radar chart theo topic | **Đồ thị tri thức năng lực cá nhân** (node mastery + cạnh tiên quyết/suy diễn) |
| Lộ trình học | Gợi ý topic tiên quyết rời rạc | **Learning path** sắp xếp topo trên đồ thị tiên quyết |
| Đánh giá hệ thống | Calibration độ khó | + **Mô phỏng hội tụ** so sánh 4 chiến lược (bias/RMSE/corr/SEM) |

### 1. Kiểm tra thích ứng theo đề (Multi-Stage Testing)

Hệ thống đã chuyển từ CAT chọn từng câu sang thích ứng theo **chuỗi đề** (`exam_chains`):
người học làm trọn một đề (số câu tự chọn), hệ thống chấm cả đề, cập nhật θ/SEM tích lũy
bằng Bayesian EAP trên toàn chuỗi, rồi áp bộ luật R1-R12 để **sinh đề kế tiếp**.
Giữa các đề có màn đánh giá trung gian; chuỗi dừng khi `SEM < 0.3`, đạt số đề tối đa,
hết câu phù hợp, hoặc người dùng chủ động kết thúc.

- Engine sinh đề: `backend/app/services/exam_generation.py`
- Router: `backend/app/api/adaptive.py`
- Diễn giải luật ở cấp độ đề: R1 blueprint đề #1; R2/R3 đặt `b_target` theo độ chính xác
  đề trước; R5 xoay topic mastered; R6 lọc Nhận biết khi θ cao; R8 chống lặp trong chuỗi
  và cross-session; R11 chèn câu tiên quyết dễ khi sai liên tiếp; R12 dành slot cho topic
  suy diễn; R9/R10 gọi LLM lấp chỗ trống quanh `b_target`; R7 phát hiện đoán mò khi chấm.

### 2. Deep Knowledge Tracing (DKT)

Mạng RNN (cài đặt thuần numpy theo Piech et al. 2015, `backend/app/engine/dkt.py`) học từ
chuỗi tương tác (topic, đúng/sai) để dự đoán xác suất trả lời đúng câu tiếp theo trên từng
topic — mô hình hóa năng lực **biến đổi theo thời gian**, bổ trợ cho ước lượng EAP tĩnh.
Huấn luyện trên log `quiz_responses` thật, tăng cường bằng sinh viên giả lập qua IRT 3PL
trên chính ngân hàng câu hỏi. Model lưu per-subject tại `backend/models_store/`.
Dashboard hiển thị card "Dự đoán năng lực (DKT)".

### 3. Reinforcement Learning cho chiến lược chọn đề

Contextual bandit (`backend/app/engine/rl_policy.py`) học offset độ khó tối ưu thay cho
R2/R3 cố định: state = (độ chính xác đề trước × mức SEM), action = offset
{−0.7, −0.3, 0, +0.3, +0.5}, reward = mức giảm SEM sau đề (lượng thông tin thu được),
chọn ε-greedy với ε giảm dần, Q-value lưu trong bảng `rl_policy`. Người dùng chọn chiến
lược "Luật R2/R3" hoặc "Reinforcement Learning" ở màn thiết lập; mọi quyết định và reward
của bandit được ghi vào rule logs (mã `RL`) để audit.

### 4. Explainable AI cho đánh giá

`GET /api/quiz/:id/explanation` phân rã kết quả đánh giá: Δθ do từng câu đóng góp
(theo timeline EAP), tỷ trọng Fisher Information của từng câu tại θ cuối, thống kê theo
thang Bloom và theo mức độ khó, kèm **narrative tiếng Việt** sinh bằng luật giải thích
vì sao θ đạt giá trị đó, câu nào ảnh hưởng mạnh nhất và kỹ năng nào đo được.
Hiển thị trong trang kết quả từng đề.

### 5. Đồ thị tri thức năng lực cá nhân

`GET /api/knowledge/subjects/:id/ability-graph` trả về ontology topic của môn kèm mastery
riêng của người dùng; trang Bản đồ tri thức có chế độ "Đồ thị năng lực": node tô màu theo
5 mức mastery, cạnh liền là quan hệ tiên quyết, cạnh đứt là quan hệ suy diễn (R12).

### 6. Tầng Kỹ năng trong ontology và Lộ trình học

Ontology đầy đủ 4 thành phần theo đề bài: **Môn học, Kỹ năng, Bloom Taxonomy, Độ khó**.
Mỗi topic có 2 kỹ năng đo được (bảng `skills`, seed tự động lúc khởi động):
"Hiểu và trình bày …" đo qua câu Nhận biết/Thông hiểu, "Vận dụng … giải quyết bài toán"
đo qua câu Vận dụng. Kỹ năng hiển thị trong đồ thị năng lực và phần XAI
"kỹ năng đo được" của trang kết quả.

`GET /api/users/learning-path?subject_id=` sinh **lộ trình học đề xuất**: sắp xếp topo
trên đồ thị tiên quyết (TopicPrerequisite + KnowledgeGraph), ưu tiên kiến thức nền của
các topic yếu, loại topic đã thành thạo; hiển thị dạng timeline trong trang tổng kết
chuỗi đề.

### 7. Vòng tự tinh chỉnh tri thức (nâng cấp thông minh)

Bốn cơ chế làm hệ thống tự cải thiện tri thức và mô hình người học của chính nó:

- **Hiệu chuẩn IRT từ dữ liệu thật** (`app/engine/calibration.py`,
  `POST /api/quiz/calibration/run`): khi một câu đủ lượt trả lời, độ khó `b` được
  ước lượng lại bằng MLE 3PL trên log trả lời (dùng θ của từng người làm) và trộn
  thận trọng theo lượng bằng chứng — chạy từ trang Đánh giá hệ thống.
- **Đường cong quên Ebbinghaus** (`FORGETTING_LAMBDA`): θ hiệu dụng của mỗi topic
  suy giảm theo số ngày không ôn (`θ_eff = θ − λ·ln(1+ngày)`); đồ thị năng lực tô màu
  theo mastery đã suy giảm, lộ trình học tự đẩy topic lâu chưa ôn lên trước.
- **Phát hiện ngộ nhận (distractor analysis)**: nếu phương án sai người dùng chọn
  trùng với phương án sai phổ biến nhất của câu đó (≥50% lượt sai), XAI đánh dấu
  đây là ngộ nhận điển hình thay vì lỗi ngẫu nhiên.
- **Warm-start prior (R0)**: người học cũ không bắt đầu từ θ=0 — prior của Bayesian
  EAP được khởi tạo từ trung bình UserAbility và dự đoán DKT (`exam_chains.prior_theta`),
  đề #1 sinh quanh θ₀ đó và toàn chuỗi dùng prior chặt hơn (sd 0.8); ghi log luật `R0`.

### 8. Đánh giá toán học độ hội tụ năng lực

Mô-đun mô phỏng `backend/app/evaluation/convergence.py` (CLI:
`python -m app.evaluation.convergence --subject 2`) giả lập sinh viên có θ thật trải đều
[-2.5, 2.5] làm bài qua engine thật, so sánh 4 chiến lược sinh đề (luật R1-R12, Fisher tối
ưu, ngẫu nhiên, RL) theo bias / RMSE / MAE / tương quan Pearson / tỷ lệ hội tụ SEM < 0.3 /
quỹ đạo SEM theo số đề. Trang `/evaluation` chạy mô phỏng và trực quan hóa kết quả.
Kết quả tham chiếu (15 SV, 6 câu/đề, 5 đề, môn Toán rời rạc): chiến lược luật đạt
RMSE ≈ 0.30 và tương quan ≈ 0.99 với θ thật, vượt trội chọn ngẫu nhiên (RMSE ≈ 0.56).

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
