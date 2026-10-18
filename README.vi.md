# BLF to MAT

[English](README.md)

Chuyển BLF CAN cùng DBC, mapping Excel và schema TXT thành Dataset MAT cho
Simulink Signal Editor. Một file `.pyz` có cả CLI và GUI Tkinter, dùng chung bộ xử lý.

## Yêu cầu và cách chạy

- Python **3.11-3.14**, Tcl/Tk cho GUI (bản Python Windows tiêu chuẩn đã có).
- Cài các thư viện trong `requirements.txt` đi kèm bản phát hành.
- **MATLAB/Simulink R2024b+**, có license khả dụng để tạo Dataset cuối cùng.
  Tool gọi MATLAB một lần cho cả batch bằng `-batch`, không cần SLDD.

`.pyz` chứa mã ứng dụng; Python, MATLAB và các thư viện native như NumPy/SciPy
được cài riêng. Tool không tự tải/cài thành phần khi chạy. Với máy offline, chuẩn bị
wheel phù hợp rồi cài bằng
`python -m pip install --no-index --find-links wheels -r requirements.txt`.

```powershell
python -m pip install -r requirements.txt
python .\blf_to_mat-0.1.0.pyz --version
python .\blf_to_mat-0.1.0.pyz --check
python .\blf_to_mat-0.1.0.pyz --gui
```

Không truyền tham số cũng mở GUI. Chọn Excel, DBC folder, BLF file/folder, một
hoặc nhiều TXT và thư mục output. YAML/MATLAB có thể để trống. Chuyển đổi chạy
nền và hiển thị log; chờ hoàn tất trước khi đóng cửa sổ.

```powershell
python .\blf_to_mat-0.1.0.pyz --cli `
  --excel .\Interface.xlsx --dbc-folder .\DBC --blf .\Logs `
  --schema .\InputSignals.txt .\OutputSignals.txt --output .\Output `
  --config .\signal_mapping.yaml `
  --matlab "C:\Program Files\MATLAB\R2024b\bin\matlab.exe"
```

Các flag CLI cũ vẫn dùng được; `--cli` có thể bỏ khi đã truyền tham số chuyển đổi.
`--debug` in traceback; `--help`/`--version` chạy được khi chưa cài thư viện.

## Dữ liệu và hành vi

- Excel `.xlsx`/`.xlsm` có sheet `SWC_INF`, `SWC_OUTF`; tự nhận diện các cột
  interface, Data Element và CAN Signal. Nên ghi rõ interface nếu trùng tên element.
- TXT: `Interface.Element : datatype`, scalar; ghép nhiều file, từ chối datatype
  mâu thuẫn. Tên interface/element phải hợp lệ trong MATLAB.
- DBC và BLF folder được tìm đệ quy. Giải mã phân biệt CAN ID chuẩn/extended.
  Nếu trùng tên CAN signal, chọn nguồn có nhiều mẫu quan sát nhất và cảnh báo.
- YAML theo [ví dụ giả lập](examples/signal_mapping.example.yaml): `input_mappings`
  ghi đè nguồn CAN, hỗ trợ `status_mapping` và `formula`; thứ tự là decode → mapping
  trạng thái → công thức → ép kiểu. `input_forces` giữ hằng số cho input không lấy
  từ CAN, bỏ qua các biến đổi trên. Không chọn YAML thì tìm `signal_mapping.yaml`
  cạnh `.pyz`; chạy source/package thì tìm ở thư mục làm việc. `--config` được ưu tiên.
- Mỗi BLF tạo `<tên>_input.mat` và `<tên>_output.mat`; tên trùng trong batch được
  thêm `_2`, `_3`. **File output đã tồn tại sẽ bị ghi đè.** Nếu lỗi có thể còn file
  output dở dang; sửa lỗi rồi chạy lại.
- MAT chứa `Scenario` kiểu `Simulink.SimulationData.Dataset`, bus struct và
  `timeseries` nội suy zero-order hold. Thiếu mẫu thì dùng zero/false và cảnh báo.
  Input có mẫu đầu sau mốc zero sẽ được thêm zero trước các biến đổi cấu hình.
  Datatype chưa hỗ trợ dùng double và cảnh báo. Cần xem log khi đánh giá stimulus.

`--check` kiểm tra Python, import thư viện và tìm MATLAB executable; trả 0 khi đạt,
1 khi thiếu. Lệnh này không khởi động MATLAB, không xác nhận version/license,
Simulink, display GUI hay Dataset thật. Lỗi chuyển đổi trả 1, tham số CLI sai trả 2,
ngắt bằng bàn phím trả 130.

## Phát triển, kiểm tra và release

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python scripts/check.py
.\.venv\Scripts\python -m blf_to_mat --gui
python scripts/build_pyz.py --release-tag v0.1.0
```

Check gồm Ruff, format, pytest và build `.pyz`. Tests tự tạo BLF/DBC/Excel giả lập,
kiểm tra luồng Python và GUI; tiến trình MATLAB được mock, **chưa chứng minh Dataset
native**. GUI test local được skip nếu thiếu display; đặt `BLF_REQUIRE_GUI=1` để bắt
buộc. CI chạy Windows/Linux (Xvfb), Python 3.11-3.14 và bắt buộc GUI test.

Trước khi dùng chính thức/chấp nhận release, chạy `.pyz` với bộ dữ liệu tham chiếu
trong môi trường MATLAB R2024b+ thực; load cả hai MAT và xác nhận
`isa(Scenario,'Simulink.SimulationData.Dataset')`, thứ tự bus, datatype, timestamp,
giá trị signal, rồi mở trong Signal Editor. CI hosted không thực hiện bước này.

Version duy nhất ở `src/blf_to_mat/__init__.py`. Sửa version và thêm mục có ngày
trong `CHANGELOG.md`. Build dùng thư viện chuẩn, chỉ đóng gói mã ứng dụng và
requirements; xuất `.pyz`, checksum SHA-256 và `requirements.txt` trong `dist/`.
Không đóng gói dữ liệu xe, YAML người dùng, test fixtures hay script gốc.
Cùng source/Python/zlib tạo archive giống nhau.

Sau khi check, xác nhận MATLAB và merge PR, chủ động tạo tag khớp version:

```powershell
git tag v0.1.0
git push origin v0.1.0
```

Workflow release chạy lại checks, đối chiếu tag/version/changelog, build, smoke
test archive không có site packages và phát hành ba asset lên GitHub. Không publish
PyPI. Push nhánh/PR chỉ chạy check và tạo preview artifact; push tag là thao tác release.
