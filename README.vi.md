# BLF to MAT

[English](README.md)

Chuyển log CAN BLF thành file MAT bằng giao diện hoặc dòng lệnh.
**Chỉ cần file hoặc folder BLF.** Các đầu vào khác bổ sung theo nhu cầu dự án.

## Tính năng

- Chỉ BLF: xuất frame CAN/CAN-FD thô.
- Thêm DBC để tự giải mã signal.
- Excel, TXT, YAML là tùy chọn để map signal, chọn datatype, áp dụng công thức
  hoặc giữ input ở giá trị hằng số.
- Tự chọn sheet input/output, cột và dòng header của Excel.
- Xuất MAT không cần MATLAB; xuất Dataset cho Signal Editor khi có MATLAB.

## Cài đặt và mở tool

Dùng Python **3.11-3.14**. Đặt `.pyz` cùng `requirements.txt` đi kèm vào một folder,
mở terminal tại đó và chạy:

```powershell
python -m pip install -r requirements.txt
python .\blf_to_mat-0.1.0.pyz --gui
```

Cài thư viện và chạy tool bằng cùng một Python. Nếu báo thiếu SciPy, kiểm tra môi trường:

```powershell
python .\blf_to_mat-0.1.0.pyz --check
```

## Chuyển đổi

Trên GUI, chọn file/folder BLF, thêm các đầu vào tùy chọn, chọn định dạng output rồi
bấm **Convert**. Dùng **Select sheets...** để chọn sheet Excel; các ô để trống sẽ tự
nhận diện. Tool chạy nền và hiển thị log.

Chạy bằng dòng lệnh:

```powershell
python .\blf_to_mat-0.1.0.pyz --blf .\capture.blf
python .\blf_to_mat-0.1.0.pyz --blf .\Logs --dbc-folder .\DBC
```

Kết quả nằm trong `mat_output` cạnh file BLF hoặc bên trong BLF folder đã chọn.
Dùng `--output` để đổi folder. Chỉ BLF tạo `<tên>.mat` chứa frame; BLF + DBC tạo
`<tên>_signals.mat`. Khi dùng mapping riêng, tool tạo file input/output cho phía
đã cấu hình. Xem `--help` để biết các tùy chọn và
[ví dụ YAML](examples/signal_mapping.example.yaml) để cấu hình mapping.

## Lưu ý khi dùng kết quả

MAT thông thường chứa dữ liệu, chưa phải Dataset native cho Signal Editor.
Muốn dùng Signal Editor, chọn `dataset` trên GUI hoặc thêm `--format dataset`;
cần MATLAB/Simulink R2024b+ và license khả dụng.

Không có DBC thì không giải mã được signal CAN. Signal mapping thiếu mẫu sẽ dùng
giá trị mặc định và cảnh báo, nên cần xem log. **File output cũ sẽ bị ghi đè.**
Xuất Dataset native vẫn cần xác nhận bằng MATLAB/Signal Editor thực.
