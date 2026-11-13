# Báo cáo cá nhân — Day 6

Học viên: Phan Hoàng Phúc · MSSV 2A202603455 · L3A
Thời điểm chạy: 2026-11-13 12:02 UTC (19:02 giờ Việt Nam) · máy macOS arm64, Python 3.13.15, CPU

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:**
  - Corpus gồm hai phiên bản Luật Bảo vệ quyền lợi người tiêu dùng: bản 2010 (59/2010/QH12, 51 Điều, hiệu lực 01/7/2011) và bản 2023 (19/2023/QH15, 80 Điều, hiệu lực 01/7/2024, thay thế bản 2010 theo Điều 79 khoản 2).
  - Về quyền sử dụng: văn bản quy phạm pháp luật không thuộc đối tượng bảo hộ quyền tác giả (Điều 15 khoản 2 Luật Sở hữu trí tuệ).
  - Tôi lấy toàn văn từ caselaw.vn ngày 13/11/2026, lưu nguyên snapshot HTML ở `data/raw/`, có sha256 trong `data/manifest.json`.
  - PDF chính thức trên moit.gov.vn là bản scan (pdftotext chỉ ra watermark) và máy không có OCR tiếng Việt, nên không dùng.
  - HTML không có trang vật lý. Quy tắc đếm: **1 đơn vị = 1 Điều**, là một quy định độc lập có nghĩa. Tổng cộng 131 đơn vị, 139.258 ký tự sau chuẩn hoá. Nếu chia theo quy tắc 1.500 ký tự thì tương đương **92 đơn vị**, gấp 3 lần mức 30 tối thiểu. Danh sách đơn vị và số ký tự từng Điều nằm trong manifest.
- **Chuẩn hoá, lỗi và giới hạn:**
  - Chuẩn hoá Unicode NFC và gộp khoảng trắng.
  - Dấu xuống dòng bên trong một thẻ `<p>` là do mã nguồn HTML ngắt dòng, nên được nối lại. Mỗi `<p>` giữ là một dòng, tương ứng một khoản hoặc điểm.
  - Bỏ nhãn "Mục N. ...", bỏ phần giao diện web và chú thích của trang.
  - Có cổng kiểm tra chặn lô: số Điều phải liên tục từ 1 đến N, và ngày hiệu lực khai báo phải khớp câu "có hiệu lực thi hành từ ngày …" trong chính văn bản. Lỗi ghi vào `results/ingest_errors.json`; lần chạy cuối có 0 lỗi.
  - Hai lỗi thật đã bắt được trong lúc làm:
    - Lần đầu tôi chạy, bản 2023 chỉ ra 10 Điều vì tiêu đề Điều bị ngắt dòng giữa chừng. Cổng kiểm tra báo `article_sequence` và `effective_date_mismatch`.
    - Dòng "Mục 3. HÒA GIẢI" bị dính vào cuối Điều 60.
  - Giới hạn của nguồn:
    - caselaw.vn ghi Luật 2010 là "Đang có hiệu lực", trong khi luật 2023 nói rõ bản 2010 hết hiệu lực. Vì vậy `is_current` lấy từ chính văn bản luật, không lấy từ nhãn của website.
    - Nguồn có lỗi chính tả gốc như "thi phải" ở Điều 15 bản 2023, được giữ nguyên.
- **Embedding model, vector store, metric, lệnh chạy và chi phí:**
  - Model `intfloat/multilingual-e5-base` chạy local qua sentence-transformers 6.3.0, 768 chiều, giới hạn 512 token. Câu hỏi có tiền tố `query: `, chunk có tiền tố `passage: `, vector được chuẩn hoá L2.
  - Chunk dài nhất là 284 token, nên không chunk nào bị cắt bớt.
  - Store là chromadb 1.5.9 `PersistentClient` lưu tại `store/chroma`. Mỗi chiến lược một collection, `hnsw:space=cosine`, tìm kiếm HNSW (xấp xỉ). Lọc bằng `where` của Chroma.
  - Chi phí 0 USD vì không gọi API.
  - Lần đầu tải và nạp model mất 605 giây, chủ yếu là tải về.
  - Lệnh chạy xem `README.md`.
- **Metadata:**
  - Bắt buộc: `document_id`, `source` (URL) và `page` (số Điều, truy vết dạng `unit_id = <document_id>#dieu-N`).
  - Bổ sung: `article_title`, `chapter`, `law_number`, `effective_date`, `is_current`, `char_start`/`char_end`, `content_sha1`.
  - **Trường lọc là `version_year` (int, giá trị 2010 hoặc 2023).** Giá trị lấy từ số hiệu văn bản. Lý do chọn: corpus có hai bản cùng chủ đề, nhiều Điều gần giống nhau, và người dùng thường nói rõ "theo luật 2010" hay "theo luật hiện hành".

## Cấu hình và benchmark

- **A / B / C:**
  - A: `fixed_size` 500 ký tự, overlap 50, cắt bên trong từng Điều, không lọc. Ra 356 chunk.
  - B: `by_paragraph` gom trọn khoản/điểm, tối đa 1.000 ký tự, mỗi chunk lặp lại tiêu đề "Điều N. …"; đoạn dài quá thì tách ở dấu `.` hoặc `;`. Không lọc. Ra 213 chunk.
  - C: chunk giống hệt B (collection riêng). **Khác biệt duy nhất giữa B và C là có `where version_year = <giá trị người dùng nêu>`**, chỉ áp dụng cho 8 câu có phiên bản trong câu hỏi.
  - Cùng model, cùng corpus, cùng bộ câu hỏi, cùng top-3.
- **Bộ câu hỏi:** 22 câu (`benchmark/questions.json`), chia **16 dev / 6 test theo chủ đề** trước khi chạy.
  - Loại câu: trực tiếp, diễn đạt lại, điều kiện/ngoại lệ và lọc metadata.
  - **8 câu có filter: 6 dev, 2 test (t04 lọc 2023, t05 lọc 2010).**
  - Câu d02 và d03 có hai nguồn gold hợp lệ (bản 2010 và 2023), trúng nguồn nào cũng tính.
  - `python -m src.run check` xác nhận cả 22 đoạn bằng chứng nằm trong Điều gold sau chuẩn hoá, và Điều gold thoả filter. Benchmark sha256 `354a7331…0f04` được khoá trước lần chạy đầu và ghi lại trong `results/metrics.json`.
  - Nguy cơ rò rỉ: d08 gần chủ đề t01/t04 (thương lượng); d13 (miễn trách nhiệm bản 2010) gần t06 (bản 2023).
- **Tiêu chí chọn chiến lược, chốt trước khi xem test** (ghi trong file benchmark): Evidence Hit@3 trên dev, rồi Hit@1 trên dev, rồi số chunk ít hơn.

## Kết quả

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian ingest (embed + ghi) | Thời gian 22 truy vấn | Chi phí |
|---|---|---|---|---|---|---|---|
| A | dev | 13/16 | 16/16 | 356 | 13,5 s | 1,1 s | 0 |
| A | test | 2/6 | 3/6 | 356 | | | 0 |
| B | dev | 11/16 | 16/16 | 213 | 12,2 s | 0,8 s | 0 |
| B | test | 3/6 | 6/6 | 213 | | | 0 |
| C | dev | **14/16** | 16/16 | 213 | 20,1 s* | 0,8 s | 0 |
| C | test | **4/6** | **6/6** | 213 | | | 0 |

\*C nhúng lại đúng 213 chunk của B; chênh 8 giây là dao động máy, không phải chi phí của filter. Đây là lần đo duy nhất.

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N) | Grounding 0/1/2 (số câu), trung bình /2 |
|---|---|---|---|---|
| A | 1,40 (10) | 18/18 | N/A (không lọc); top-3 thuần đúng phiên bản 0/2 test, 0/6 dev | 2 / 3 / 1, trung bình 0,83 |
| B | 2,00 (10) | 18/18 | N/A (không lọc); top-3 thuần đúng phiên bản 0/2 test, 0/6 dev | 0 / 0 / 6, trung bình 2,00 |
| C | 2,00 (10, cùng chunk B) | 18/18 | **2/2 test, 6/6 dev** | 0 / 0 / 6, trung bình 2,00 |

Đường dẫn và cách chọn mẫu:
- Trace đầy đủ (câu hỏi, filter, top-3 kèm id, text, score, metadata, cờ hit): `results/trace_{A,B,C}.jsonl`.
- Chỉ số: `results/metrics.json`, `results/metrics_table.csv`, `results/index_stats.json` (phân bố độ dài, token).
- Kiểm nạp lại: `results/reingest_check.json`.
- Nhãn thủ công kèm lý do: `results/audit/labels.json`. Bảng để chấm: `results/audit/coherence_sheet.md` và `results/audit/test_top3_sheet.md`. Tổng hợp: `results/audit/audit_summary.json`.
- Mẫu coherence: 10 vị trí cố định chốt trước khi chấm, là Điều thứ 0, 13, 26, …, 117 theo thứ tự trong `units.jsonl`, lấy ký tự giữa Điều.
- Metadata và grounding chấm trên cả 6 câu test × top-3.

## Phân tích và kết luận

- **A so với B (chỉ đổi cách chia chunk):**
  - Trên dev, A có Hit@1 cao hơn (13 so với 11) vì chunk nhỏ khớp sát câu hỏi.
  - Trên test, A tụt còn Hit@3 3/6. Hai câu có Điều gold nằm trong top-3 nhưng bằng chứng bị cắt sang chunk khác.
  - Coherence của A là 1,4 so với 2,0 của B; grounding 0,83 so với 2,0.
  - B dùng ít hơn 40% số chunk (213 so với 356). Thời gian ingest gần như nhau.
- **B so với C (chỉ thêm filter):** C chỉ thay đổi kết quả ở 8 câu có phiên bản. Hit@1 dev tăng 11→14 (d10, d12, d13), Hit@1 test tăng 3→4 (t04). Top-3 sạch phiên bản 8/8 so với 0/8 khi không lọc. Hit@3 không đổi vì B vẫn có gold trong top-3.
- **Ví dụ sai 1 — A, t05**, gold `luat-59-2010-QH12` Điều 42 khoản 3: chunk rank 1 `luat-59-2010-QH12:42:1` bắt đầu bằng "uyết định bên có lỗi…". Cửa sổ 500 ký tự cắt mất chữ "Tòa án q", nên đúng Điều đúng trang nhưng không trả lời được câu "ai quyết định". Lỗi này được ghi là tách bằng chứng (`page_only_hit@3`).
- **Ví dụ sai 2 — B, t04**, gold `luat-19-2023-QH15` Điều 57: rank 1 là Điều 31 của **bản 2010** (cùng "07 ngày làm việc"). Một agent đọc rank 1 sẽ trích dẫn văn bản đã hết hiệu lực mà vẫn đúng con số, nên lỗi này rất khó thấy.
  - Cùng kiểu lỗi ở dev: d08 và d09 (B và C, không có filter vì câu hỏi không nêu phiên bản) có rank 1 là Điều 32 / Điều 46 bản 2010. Điều 32 bản 2010 không có quy định chữ ký/điểm chỉ, nên trả lời theo rank 1 là thiếu.
- **Tôi chọn C.** Theo tiêu chí đã chốt, Hit@3 dev hoà (A = B = C = 16/16) và Hit@1 dev của C cao nhất (14).
  - Đánh đổi: filter chỉ có tác dụng khi người dùng hoặc ngữ cảnh nói rõ phiên bản. Câu không nêu phiên bản (d08, d09, t01) vẫn có thể lấy bản cũ.
  - Hướng xử lý cho agent thật: mặc định lọc `is_current = true` khi câu hỏi nói "hiện nay/hiện hành" hoặc không nêu phiên bản, và chỉ mở bản cũ khi được hỏi rõ (giao dịch trước 01/7/2024, theo Điều 80).
  - Trong lần chạy này tôi **không** dùng mặc định đó, để giữ nguyên quy tắc "filter chỉ lấy từ câu hỏi".
- **Hạn chế:**
  - Test chỉ có 6 câu: một câu chênh là 17 điểm phần trăm, nên không đủ để kết luận tổng quát ngoài corpus này.
  - Tôi vừa là người chấm vừa là người thiết kế chunker B và bộ câu hỏi, nên có nguy cơ thiên lệch về phía B/C. Coherence 2,0 của B phần lớn do Điều ngắn nằm gọn trong một chunk.
  - Evidence Hit dùng khớp chuỗi đầy đủ, nên khắt khe với cách chia A.
  - Thời gian đo một lần trên CPU laptop, có dao động.
  - Đơn vị truy vết là Điều, không phải trang PDF công báo.
- **Nếu làm lại, tôi sẽ:**
  - Lấy bản PDF công báo kèm OCR tiếng Việt để có trang thật.
  - Thêm câu không nêu phiên bản vào test để đo luật mặc định `is_current`.
  - Thử hybrid BM25 cho câu chứa con số ("07 ngày", "05 số"), dùng nhóm câu dev riêng để chỉnh tham số.
  - Thêm một người chấm độc lập để đo mức đồng thuận.

## Công cụ hỗ trợ

Tôi dùng trợ lý code AI để hỗ trợ viết code và soạn nháp; mọi bằng chứng được kiểm bằng `src.run check`, số Điều/ngày hiệu lực kiểm ở cổng ingest, nhãn chấm tay tôi tự duyệt lại. Số liệu lấy nguyên từ file kết quả của lần chạy trên.
