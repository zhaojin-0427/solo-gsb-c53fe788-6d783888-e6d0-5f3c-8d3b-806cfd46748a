# 多时相遥感云隙拼接 API

提交同一坐标网格的 2～16 个时相栅格切片（采集时间、分辨率、左上原点、波段矩阵、
无数据值、云掩膜），服务把每个切片按仿射位置落入输出网格，逐像元**排除云与无数据**，
按固定优先级选源，检测重叠冲突与无法覆盖的空洞，返回确定性的拼接矩阵、逐像元来源、
覆盖率/空洞统计与预览图。结果持久化在 SQLite，支持按 ID 复核与请求体幂等重试。

- Web 框架：FastAPI + Pydantic v2 + NumPy + Pillow
- 交互文档：服务启动后访问 `/docs`（Swagger UI）或 `/redoc`

## 选源优先级（逐像元）

仅在“非云、非无数据”的候选像元之间比较，字典序优先级为：

1. 切片总云量 `cloud_fraction` 升序（云更少的时相优先）；
2. 与参考时间（所有切片中最新采集时间）的时间差升序（时间更近优先）；
3. 像元到切片左上角原点的纵深距离（局部行号+列号）降序（优先切片内部、远离接缝边缘）；
4. 切片在请求中的序号升序（最终确定性裁决）。

## 一、Docker Compose 一键启动（推荐复核方式）

需要本机已安装 Docker 与 Compose 插件。在仓库根目录执行：

```bash
docker compose up --build
```

服务监听在 <http://localhost:8000>，SQLite 数据库保存在命名卷 `mosaic-data`
（容器内 `/data/mosaics.db`），容器重建后结果仍在。

验证服务：

```bash
curl http://localhost:8000/healthz
# {"status":"ok"}
```

- Swagger 交互文档：<http://localhost:8000/docs>
- 创建拼接：`POST http://localhost:8000/mosaics`
- 按 ID 复核：`GET http://localhost:8000/mosaics/{id}`

停止并清理：

```bash
docker compose down            # 停止，保留数据卷
docker compose down -v         # 停止并删除数据卷
```

可用环境变量覆写默认参数（见 `docker-compose.yml` 与 `app/config.py`）：
`MOSAIC_DB_PATH`、`MOSAIC_MAX_PIXELS`、`MOSAIC_MAX_DIM`、`MOSAIC_ALIGN_TOL`、
`MOSAIC_MAX_EVIDENCE`、`MOSAIC_MAX_HOLES`、`MOSAIC_PREVIEW_EDGE`。

## 二、本地直接运行（可选）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export MOSAIC_DB_PATH=./mosaics.db          # 可选，默认 /data/mosaics.db
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

运行测试：

```bash
pip install pytest
pytest -q
```

## 三、波段数据类型 `bands_dtype` 的语义

这是本服务处理**负数无数据哨兵**（如 `-9999`）的关键约定：

- **省略 `bands_dtype`（或传 `null`）**：JSON 数组按其实际内容解析，**不做无符号窄化**，
  负数哨兵原样保留并参与无数据筛除。含 `-9999` 的数组请使用这种方式。
- **显式 `"uint8"` / `"uint16"`**：要求每个像元都能被该无符号类型表示。
  若出现无法表示的像元（如 `-9999`，或 uint8 下的 `300`、非整数小数），
  接口返回 **422**，**不会静默回绕/截断成有效值**。
- **显式 `"float32"`**：可承载负数哨兵与小数值。
- **PNG 输入（`bands_png`）**：省略 `bands_dtype` 时按 PNG 位深推断
  （16 位灰度 `I;16` → uint16，`L/LA/RGB/RGBA` → uint8）；显式声明同样执行范围校验。
  `float32` 不能用 PNG 编码。

省略类型与显式声明会得到不同的**规范化请求哈希**，因此不会在幂等重试中错误共用结果；
当数据可被显式类型无损表示时，两种写法产出的拼接矩阵、空洞、覆盖率与逐像元来源完全一致。

## 四、实际请求与响应示例

以下示例可直接对运行中的服务执行（文件版见仓库，亦可粘贴到 `/docs`）。
两个 3×3 单波段切片位于同一网格，云区上下互补，且在 `(2,0)` **共同无数据**形成空洞；
请求**省略 `bands_dtype`**，数组中的 `-9999` 被原样保留。

### 请求

```bash
curl -s -X POST http://localhost:8000/mosaics \
  -H 'Content-Type: application/json' \
  -d '{
  "tiles": [
    {
      "id": "A",
      "acquired_at": "2026-09-01T10:00:00Z",
      "pixel_size": [10.0, -10.0],
      "origin": {"x": 0.0, "y": 30.0},
      "nodata": -9999.0,
      "bands": [
        [[100, 100, 100],
         [100, 100, 100],
         [-9999, 100, 100]]
      ],
      "cloud_mask": [
        [1, 1, 1],
        [0, 0, 0],
        [0, 0, 0]
      ]
    },
    {
      "id": "B",
      "acquired_at": "2026-09-02T10:00:00Z",
      "pixel_size": [10.0, -10.0],
      "origin": {"x": 0.0, "y": 30.0},
      "nodata": -9999.0,
      "bands": [
        [[200, 200, 200],
         [200, 200, 200],
         [200, 200, 200]]
      ],
      "cloud_mask": [
        [0, 0, 0],
        [0, 0, 0],
        [1, 1, 1]
      ]
    }
  ],
  "target": {
    "origin": {"x": 0.0, "y": 30.0},
    "width": 3,
    "height": 3,
    "pixel_size": [10.0, -10.0],
    "nodata": -9999.0
  },
  "max_time_delta_seconds": 432000,
  "request_id": "demo-job-001"
}'
```

### 响应（`201 Created`，字段与实现一致；`id`/`created_at`/`*_png`/`request_hash` 每次不同，已截断长串）

```json
{
  "id": "f20a7b70c02b4f50812cb978fa900451",
  "created_at": "2026-10-04T18:26:20.287715Z",
  "status": "done",
  "target": {
    "origin": {"x": 0.0, "y": 30.0},
    "width": 3,
    "height": 3,
    "pixel_size": [10.0, -10.0],
    "nodata": -9999.0
  },
  "max_time_delta_seconds": 432000.0,
  "reference_time": "2026-09-02T10:00:00Z",
  "bands": [
    [[200.0, 200.0, 200.0],
     [200.0, 200.0, 200.0],
     [-9999.0, 100.0, 100.0]]
  ],
  "nodata": -9999.0,
  "source_map": [
    [1, 1, 1],
    [1, 1, 1],
    [-1, 0, 0]
  ],
  "source_ids": ["A", "B"],
  "coverage": {
    "covered_fraction": 0.8888888888888888,
    "covered_pixels": 8,
    "hole_pixels": 1,
    "total_pixels": 9,
    "holes": [
      {"size": 1, "bbox": {"min_row": 2, "min_col": 0, "max_row": 2, "max_col": 0}}
    ]
  },
  "overlap": {
    "pixels_with_multiple_candidates": 3,
    "conflicting_pixels": 3,
    "evidence": [
      {"row": 1, "col": 0, "winner": "B", "runner_up": "A",
       "winner_values": [200.0], "runner_up_values": [100.0], "abs_difference": [100.0],
       "acquired_at": "2026-09-02T10:00:00Z", "runner_up_acquired_at": "2026-09-01T10:00:00Z"},
      {"row": 1, "col": 1, "winner": "B", "runner_up": "A",
       "winner_values": [200.0], "runner_up_values": [100.0], "abs_difference": [100.0],
       "acquired_at": "2026-09-02T10:00:00Z", "runner_up_acquired_at": "2026-09-01T10:00:00Z"},
      {"row": 1, "col": 2, "winner": "B", "runner_up": "A",
       "winner_values": [200.0], "runner_up_values": [100.0], "abs_difference": [100.0],
       "acquired_at": "2026-09-02T10:00:00Z", "runner_up_acquired_at": "2026-09-01T10:00:00Z"}
    ]
  },
  "tiles": [
    {"tile_id": "A", "acquired_at": "2026-09-01T10:00:00Z", "used_pixels": 2,
     "excluded": false, "exclude_reason": null, "cloud_fraction": 0.3333333333333333,
     "origin_col": 0, "origin_row": 0},
    {"tile_id": "B", "acquired_at": "2026-09-02T10:00:00Z", "used_pixels": 6,
     "excluded": false, "exclude_reason": null, "cloud_fraction": 0.3333333333333333,
     "origin_col": 0, "origin_row": 0}
  ],
  "preview_png": "data:image/png;base64,iVBORw0K…（彩色预览，无数据透明）",
  "source_map_png": "data:image/png;base64,iVBORw0K…（逐像元来源索引着色，-1 空洞透明）",
  "request_hash": "554c9de62a4b82ac0445f9d0f865f94f07f4c8c979d7e670b2ecb50816f893b9",
  "request_id": "demo-job-001"
}
```

解读：

- **顶行**：A 有云，改由 B（200）填补，`source_map` 为 `1`；
- **底行**：B 有云，改由 A（100）填补，`source_map` 为 `0`；
- `(2,0)`：A 为 `-9999`、B 有云，两时相都无有效值 → 空洞，结果保留 `nodata=-9999`、
  来源为 `-1`，覆盖率 8/9；
- 中间一行两时相都清晰且数值不同（100 vs 200），构成 3 个重叠冲突，更新的 B 胜出。

### 幂等重试与按 ID 复核

- 用**完全相同的请求体**再次 `POST /mosaics`：返回 **`200 OK`** 且 `id`/`request_hash` 不变
  （不会重新计算）。
- 相同 `request_id` 但请求体不同：返回 **`409 Conflict`**。
- 复核结果：

  ```bash
  curl http://localhost:8000/mosaics/f20a7b70c02b4f50812cb978fa900451   # 200
  curl http://localhost:8000/mosaics/does-not-exist                      # 404
  ```

### 反例：显式无符号类型遇到无法表示的像元 → 422（不回绕）

把上面含 `-9999` 的切片显式声明为 `"bands_dtype": "uint16"`，返回：

```http
HTTP/1.1 422 Unprocessable Entity
```

```json
{
  "detail": "tile A 显式声明 bands_dtype=uint16，但存在超出 [0, 65535] 范围的像元（如负数无数据哨兵）；请省略 bands_dtype 让服务按数组内容推断，或改用可表示该像元的类型"
}
```

## 五、输入编码与主要约束

- 每个切片的 `bands`（JSON 数组，形状 `[band, height, width]`）与 `bands_png`
  （base64 PNG，通道 R,G,B,A 即波段）二选一；`cloud_mask`（二维 0/1）与 `cloud_mask_png`
  （单波段 8 位 PNG，非零即云）同样二选一。
- 所有切片必须与 `target` 同分辨率（相对容差 1e-6），左上角必须落在整数像元偏移上，否则 422。
- 输出网格单边 ≤ 8192、总像元 ≤ 4,000,000（可用环境变量调整）；切片数 2～16，id 唯一。
- `max_time_delta_seconds` 之外的时相不参与选源（在响应 `tiles[].excluded` 中标注原因）。
