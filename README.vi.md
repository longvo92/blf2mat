# BLF to MAT

[English](README.md)

Tool chuyển CAN BLF dùng chung cho nhiều dự án, có CLI và GUI Tkinter trong một
`.pyz`. **Chỉ BLF bắt buộc.** DBC, Excel, TXT, YAML, thư mục output và MATLAB đều
là tùy chọn, tùy mục đích sử dụng.

## Chạy tool

Hỗ trợ Python **3.11–3.14**. Cài `requirements.txt` đi kèm archive vào cùng môi
trường Python. GUI cần Tcl/Tk; chỉ xuất Dataset native mới cần MATLAB/Simulink
R2024b+ có license.

```powershell
python -m pip install -r requirements.txt
python .\blf_to_mat-0.1.0.pyz --blf .\capture.blf
python .\blf_to_mat-0.1.0.pyz --gui
python .\blf_to_mat-0.1.0.pyz --check
```

Không truyền tham số thì mở GUI. BLF có thể là file hoặc folder tìm đệ quy.
Output mặc định là `mat_output` cạnh file BLF hoặc bên trong BLF folder; có thể
đổi bằng `--output`. `--cli` không bắt buộc khi đã truyền tham số chuyển đổi.
`--help`/`--version` chạy được khi chưa cài thư viện ngoài.

| Setup | Kết quả |
| --- | --- |
| Chỉ BLF | `<tên>.mat`, chứa CAN/CAN-FD `Frames` |
| BLF + DBC | `<tên>_signals.mat`, signal được nhóm theo message DBC |
| BLF + DBC + TXT | Dùng interface/datatype từ schema, map element trùng tên CAN |
| BLF + Excel, DBC/TXT tùy chọn | Dùng mapping input/output; tự suy ra target nếu thiếu TXT |
| BLF + YAML, DBC/TXT tùy chọn | Dùng mapping/biến đổi CAN hoặc force hằng số |
| Có định nghĩa signal + `--format dataset` | Dataset native cho Signal Editor, tạo bằng MATLAB |

Không có DBC thì không giải mã được signal CAN: vẫn xuất frame thô; các định nghĩa
signal được cấp sẽ dùng default/force và có cảnh báo. YAML khai báo nguồn CAN cần
DBC chứa nguồn đó. Setup chỉ có frame thô không tạo được Dataset native; cần thêm
định nghĩa signal hoặc chọn MAT thông thường.

## Excel linh hoạt

Không bắt buộc tên sheet, vị trí cột hay thứ tự bus riêng của dự án. Tool tìm header
và tên schema/DBC trong 20 dòng đầu. Nhận diện các tên như `Data Element`/`Element`/
`Target`, `CAN Signal`/`DBC Signal`/`Source`, `Interface`/`Bus`/`Group`, `Datatype`/`Type`.

```powershell
python .\blf_to_mat-0.1.0.pyz --blf .\Logs --dbc-folder .\DBC `
  --excel .\Mapping.xlsx --input-sheet "Inputs" --output-sheet "Outputs" `
  --header-row 4 --element-column "Model name" --can-column "Network name" `
  --interface-column "Bus name" --dtype-column "Storage type"
```

- Lặp `--input-sheet`/`--output-sheet` để chọn nhiều sheet. Có thể chỉ xuất một
  phía. Nếu không chọn, các sheet nhận diện được làm input; sheet không nhận diện
  được bị bỏ qua kèm cảnh báo. Workbook có cả `SWC_INF`/`SWC_OUTF` vẫn được hiểu
  theo input/output cũ để tương thích, không bắt buộc dùng các tên này.
- Cột có thể chọn bằng tên header chính xác, không phân biệt hoa/thường, hoặc
  số thứ tự **từ 1**. `--header-row` cũng tính từ 1. Chọn sai rõ ràng sẽ báo lỗi.
- Không có TXT: dùng target `Bus.Element` hoặc cột interface; nếu thiếu thì bus là
  `Signals`. Datatype mặc định double. Nếu chỉ có cột CAN thì dùng tên CAN làm tên
  element. Mapping trùng và mâu thuẫn sẽ báo lỗi.
- Có TXT: đối chiếu với schema; element trùng ở nhiều bus phải chỉ rõ interface.
  Thứ tự bus theo mapping/schema, không còn danh sách kiến trúc cố định.
- GUI có **Select sheets...** để chọn nhiều sheet input/output, cùng các ô chọn
  tên/số cột và dòng header. Để trống thì tự nhận diện.

## Định nghĩa signal và định dạng MAT

TXT khai báo scalar `Interface.Element : datatype`, có thể ghép nhiều file. Từ chối
datatype mâu thuẫn và tên MATLAB không hợp lệ. Khi chỉ có DBC, tool tự tạo tên
message/element hợp lệ và duy nhất, giữ riêng signal trùng tên ở các message khác
nhau, giữ thời điểm mẫu quan sát được và lưu giá trị vật lý dạng double.

[Ví dụ YAML](examples/signal_mapping.example.yaml): `input_mappings` có `can_signal`,
`status_mapping` (CAN → model), `formula` như `x/10+5`; thứ tự là decode → mapping
trạng thái → công thức → ép kiểu. `input_forces` giữ hằng số cho input không từ CAN
trong toàn log. Nếu thiếu Excel/TXT, target YAML được suy ra với kiểu double.
Không truyền `--config` thì tìm `signal_mapping.yaml` cạnh `.pyz`; chạy source/package
thì tìm ở thư mục làm việc.

MAT thông thường là mặc định, không cần MATLAB. File signal chứa struct `Scenario`,
bus/element có `Time` và `Data`; **không phải Dataset native**. Chỉ xuất file input/
output cho phía đã cấu hình. `Frames` gồm thời gian tương đối `Time`, `Timestamp`
như BLF reader đọc được, ID, channel, DLC, chiều dài payload, ma trận uint8 N×64 và
các cờ Extended/FD/Remote/Error/BRS/ESI/Rx. `Length` phân biệt payload với zero padding.
Không xuất các object BLF ngoài CAN; mốc timestamp phụ thuộc BLF reader.

Cho Signal Editor, chọn `--format dataset [--matlab PATH]`. Không truyền đường dẫn
thì tìm MATLAB tự động. Để tương thích CLI cũ, `--matlab` tường minh ngầm chọn Dataset
trừ khi có `--format` ghi đè. MATLAB chạy một lần cho cả batch, tạo `Scenario` native
với bus struct/timeseries ZOH; không cần SLDD.

Signal mapping thiếu mẫu dùng zero/false và cảnh báo. Setup input có Excel/TXT vẫn
thêm mẫu zero ban đầu trước các biến đổi cấu hình; DBC-only không thêm mẫu giả.
Ép integer có làm tròn/bão hòa; kiểu chưa hỗ trợ dùng double và cảnh báo. Cần kiểm
tra log trước khi dùng làm stimulus. Mapping Excel/TXT/YAML có nguồn CAN trùng tên
vẫn chọn DBC theo số mẫu và cảnh báo mơ hồ; các tùy chọn này chưa cấu hình DBC theo
CAN channel riêng.

**File output cũ sẽ bị ghi đè.** Tên BLF trùng trong batch thêm `_2`, `_3`.
Lỗi có thể để lại output dở dang. GUI chạy nền; chờ xong trước khi đóng.
Dùng `--debug` để xem traceback.

`--check` kiểm tra import thư viện và báo GUI/MATLAB tùy chọn. Thiếu MATLAB không
làm fail check MAT; `--check --format dataset` thì yêu cầu MATLAB. Tìm executable
không xác nhận version/license/serialization; import Tcl/Tk không xác nhận display.
Exit code: 0 thành công, 1 lỗi chuyển đổi/check, 2 tham số sai, 130 ngắt bàn phím.

## Phát triển, build và release

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python scripts/check.py
.\.venv\Scripts\python -m blf_to_mat --gui
python scripts/build_pyz.py --release-tag v0.1.0
```

Check gồm Ruff, format, pytest và build archive. Tests dùng dữ liệu giả lập, kiểm
tra serialization MAT thật, các setup optional, chọn Excel và GUI. MATLAB được mock:
Dataset native vẫn cần xác nhận bằng MATLAB R2024b+ và Signal Editor thực. GUI test
local có thể skip nếu thiếu display; `BLF_REQUIRE_GUI=1` bắt buộc chạy. CI bắt buộc
GUI trên Windows/Linux (Xvfb), Python 3.11–3.14; mỗi module GUI test dùng một Tcl/Tk
interpreter để tránh lỗi vòng đời cửa sổ.

Version ở `src/blf_to_mat/__init__.py`; mỗi version cần mục có ngày trong changelog.
Build chỉ dùng thư viện chuẩn, xuất `.pyz`, SHA-256 và requirements lấy từ
`pyproject.toml` vào `dist/`. Chỉ đóng gói mã ứng dụng, chuẩn hóa newline, không kèm
dữ liệu người dùng, YAML, fixtures, script gốc hay thư viện native. Cùng source và
Python/zlib tạo bytes giống nhau. Tool không tải gì khi chạy. Với máy offline,
chuẩn bị wheel phù hợp rồi cài bằng
`python -m pip install --no-index --find-links wheels -r requirements.txt`.

Sau khi merge thay đổi đã review và xác nhận runtime phù hợp, chủ động push tag khớp
version (`git tag v0.1.0`, rồi `git push origin v0.1.0`). Workflow release chạy lại
checks, đối chiếu tag/version/changelog, smoke test archive không có site packages,
rồi phát hành ba asset lên GitHub. Check nhánh/PR chỉ tạo preview; không publish PyPI.
