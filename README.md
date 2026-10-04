# 多时相遥感云隙拼接 API（Cloud-Gap Mosaic API）

提交 **同一坐标网格** 的 2～16 个时相栅格切片（采集时间、分辨率、左上原点、波段矩阵、
无数据值、云掩膜），服务把各切片按仿射位置落入统一输出网格，逐像元 **排除云与无数据**，
按固定优先级选源，检测重叠冲突与无法覆盖的空洞，返回确定性拼接结果。

- Web 框架：FastAPI + Pydantic v2
- 数值/图像：NumPy、Pillow（波段矩阵与云掩膜均支持 JSON 数组或 base64 PNG）
- 持久化：SQLite（任务、请求摘要、幂等键）

---

## 1. Docker Compose 一键启动

前置：已安装 Docker 与 Docker Compose（`docker compose version` 可用）。

```bash
# 在仓库根目录（含 docker-compose.yml）执行
docker compose up --build
```

启动后：

| 入口 | 地址 | 说明 |
| --- | --- | --- |
| 健康检查 | http://localhost:8000/healthz | 返回 `{"status":"ok"}` |
| 创建拼接任务 | `POST http://localhost:8000/mosaics` | 201 新建 / 200 幂等命中 |
| 按 ID 取结果 | `GET http://localhost:8000/mosaics/{id}` | 持久化，可复核 |
| Swagger UI | http://localhost:8000/docs | 可交互发请求 |
| ReDoc | http://localhost:8000/redoc | 只读接口文档 |

SQLite 数据文件保存在命名卷 `mosaic_data`（容器内 `/data/mosaics.db`），
`docker compose down` 后仍保留；如需清空：`docker compose down -v`。

用仓库自带的示例复核（见 [`examples/request.json`](examples/request.json)）：

```bash
curl -s -X POST http://localhost:8000/mosaics \
  -H 'Content-Type: application/json' \
  --data @examples/request.json | python3 -m json.tool
```

> 不使用 Docker 时也可本地运行：
> `pip install -r requirements.txt`，
> `MOSAIC_DB_PATH=./mosaics.db uvicorn app.main:app --host 0.0.0.0 --port 8000`。

运行测试：`pip install -r requirements.txt pytest httpx && python3 -m pytest -q`。

---

## 2. `bands_dtype`：负数无数据哨兵的关键行为

每个切片的波段类型由字段 `bands_dtype` 决定，**三种取值语义不同，且是不同的请求**
（请求哈希、幂等结果互不共用）：

| `bands_dtype` | 语义 | 负数哨兵（如 `-9999`） | 越界像元 |
| --- | --- | --- | --- |
| **省略 / `null`**（推荐） | 按 JSON 数组内容 **自动判定**：整数保留 `int64`，小数按 `float64` | **原样保留**，正常参与云隙选源 | 不存在“越界”，仅要求是数值型规则三维数组 |
| `"uint8"` / `"uint16"` | 显式声明为无符号整数 | **返回 422**，绝不回绕成 `55537` 等大正数 | 负数、超上限、非整数、NaN/Inf 一律 **422** |
| `"float32"` | 显式 32 位浮点（仅 JSON 数组，不支持 PNG） | 原样保留 | —— |

> **历史故障说明**：旧版本 `bands_dtype` 默认 `"uint16"`，当 JSON 像元含 `-9999` 且
> `nodata=-9999` 时，解码阶段会因无符号类型装不下负数而抛出 `OverflowError`，
> 导致接口在“筛除云/无数据 + 选源”之前就失败。修复后：**省略类型的数组保留负数哨兵
> 并参与原有选源**；只有在 **显式** 声明 `uint8`/`uint16` 且确有不可表示像元时才拒绝（422）。
>
> PNG 输入（`bands_png`）省略 `bands_dtype` 时按 PNG 位深解码（L/LA/RGB/RGBA→`uint8`，
> `I;16`→`uint16`）；显式类型也必须在该无符号取值范围内，否则 422。

**云与无数据的区别**（逐像元）：

- **云**（`cloud_mask=1`）只表示“该时相此像元不可用”，该候选被剔除，**缺口由其他时相填补**；
- **无数据**（波段值 == 该切片 `nodata`）表示“该时相无观测”：更晚覆盖该像元的切片若为
  非云 nodata，会把更早时相的填充也抹掉（输出回退为目标 `nodata`）；而更晚的清晰像元
  同样可以覆盖更早的 nodata。云不参与这一“有无观测”的裁决。

---

## 3. 实际请求示例（与实现一致）

下面的最小示例使用仓库中的 [`examples/request.json`](examples/request.json)：
2 个 1 波段、2×2 的同网格切片。A 无云但右下角无数据（`-9999`）；B 较新但右下角有云。

```json
{
  "tiles": [
    {
      "id": "2026-08-01-A",
      "acquired_at": "2026-08-01T10:00:00Z",
      "pixel_size": [10.0, -10.0],
      "origin": { "x": 0.0, "y": 20.0 },
      "nodata": -9999.0,
      "bands": [
        [
          [10, 20],
          [30, -9999]
        ]
      ],
      "cloud_mask": [
        [0, 0],
        [0, 0]
      ]
    },
    {
      "id": "2026-08-02-B",
      "acquired_at": "2026-08-02T10:00:00Z",
      "pixel_size": [10.0, -10.0],
      "origin": { "x": 0.0, "y": 20.0 },
      "nodata": -9999.0,
      "bands": [
        [
          [40, 50],
          [60, 70]
        ]
      ],
      "cloud_mask": [
        [0, 0],
        [0, 1]
      ]
    }
  ],
  "target": {
    "origin": { "x": 0.0, "y": 20.0 },
    "width": 2,
    "height": 2,
    "pixel_size": [10.0, -10.0],
    "nodata": -9999.0
  },
  "max_time_delta_seconds": 86400,
  "conflict_value_tolerance": 0
}
```

> 注意：两个切片都 **没有** `bands_dtype` 字段，因此 `-9999` 哨兵被自动保留，不会触发
> `OverflowError`。

### 响应（HTTP 201，节选）

```json
{
  "id": "946a59361fa947fab9df750c8e1162c9",
  "status": "done",
  "target": {
    "origin": { "x": 0.0, "y": 20.0 },
    "width": 2, "height": 2,
    "pixel_size": [10.0, -10.0],
    "nodata": -9999.0
  },
  "max_time_delta_seconds": 86400.0,
  "reference_time": "2026-08-02T10:00:00Z",
  "bands": [
    [
      [10.0, 20.0],
      [30.0, -9999.0]
    ]
  ],
  "nodata": -9999.0,
  "source_map": [
    [0, 0],
    [0, -1]
  ],
  "source_ids": ["2026-08-01-A", "2026-08-02-B"],
  "coverage": {
    "covered_fraction": 0.75,
    "covered_pixels": 3,
    "hole_pixels": 1,
    "total_pixels": 4,
    "holes": [
      { "size": 1, "bbox": {"min_row": 1, "min_col": 1, "max_row": 1, "max_col": 1} }
    ]
  },
  "overlap": {
    "pixels_with_multiple_candidates": 3,
    "conflicting_pixels": 3,
    "evidence": [
      {
        "row": 0, "col": 0,
        "winner": "2026-08-01-A", "runner_up": "2026-08-02-B",
        "winner_values": [10.0], "runner_up_values": [40.0],
        "abs_difference": [30.0],
        "acquired_at": "2026-08-01T10:00:00Z",
        "runner_up_acquired_at": "2026-08-02T10:00:00Z"
      }
    ]
  },
  "tiles": [
    {
      "tile_id": "2026-08-01-A", "acquired_at": "2026-08-01T10:00:00Z",
      "used_pixels": 3, "excluded": false, "exclude_reason": null,
      "cloud_fraction": 0.0, "origin_col": 0, "origin_row": 0
    },
    {
      "tile_id": "2026-08-02-B", "acquired_at": "2026-08-02T10:00:00Z",
      "used_pixels": 0, "excluded": false, "exclude_reason": null,
      "cloud_fraction": 0.25, "origin_col": 0, "origin_row": 0
    }
  ],
  "preview_png": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAGElEQVR42gXBAQEAAAjDIEz+6BMObaMKHjnYBnq92Z2rAAAAAElFTkSuQmCC",
  "source_map_png": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFUlEQVR42mN8IiXzn4GBgYGJAQIYASCRAh5fd8rCAAAAAElFTkSuQmCC",
  "request_hash": "9d842ee7d1730fbaee31850ed76be43eff4a77ec26635a9c10dcee3413fdcc21",
  "request_id": null
}
```

结果解读（逐像元来源一致）：

- **三个重叠清晰像元**：虽然 B 更新，但 B 云量 25% > A 云量 0%，按“**云量优先**”选 A
  （值 10/20/30，`source_map` 为 `0`），并记录为 3 个数值冲突（容差 0，差值 30）。
- **右下角 (1,1)**：A 是 nodata、B 是云，没有任何有效观测 → 空洞（`-9999`，`source_map=-1`），
  覆盖率 75%，一个 1 像元的 4 连通空洞。
- `id`/`created_at` 每次部署会变，但同一请求体重试得到 **相同 `request_hash` 与相同 `id`**
  （幂等，第二次返回 HTTP 200）。

随后可用返回的 `id` 复核：

```bash
curl -s http://localhost:8000/mosaics/946a59361fa947fab9df750c8e1162c9 | python3 -m json.tool
```

---

## 4. 显式无符号类型遇到负数 → 422（不回绕）

把上面请求里两个切片都加上 `"bands_dtype": "uint16"`（A 仍含 `-9999`），服务 **拒绝**：

`POST /mosaics` → **HTTP 422**

```json
{
  "detail": "tile u1 显式声明 bands_dtype=uint16，但存在 1 个无法由该无符号类型表示的像元（首个 -9999.0）；无符号像元必须是 [0, 65535] 内的整数。请移除越界像元、改用非负 nodata，或省略 bands_dtype / 改用 float32 以保留负数哨兵。"
}
```

- `uint8` 的取值范围是 `[0, 255]`；`uint16` 是 `[0, 65535]`。非整数（如 `1.5`）、超上限
  （如 `uint8` 的 `300`、`uint16` 的 `65536`）同样 422。
- 该请求 **不会** 落库、不产生拼接结果；省略 `bands_dtype` 或改用 `"float32"` 即可保留负数。

---

## 5. 幂等、请求摘要与 `request_id`

- 服务对规范化请求体（含 **是否省略 `bands_dtype` 及具体取值**）计算 SHA-256 `request_hash`。
  因此“省略类型（自动保留负数）”与“显式 `uint16`”是 **不同请求**，不会在请求摘要或
  幂等重试中错误共用结果（`id`、`request_hash` 都不同）。
- **相同请求体重试**：直接返回首次结果，HTTP **200**（不重新计算）。
- **相同 `request_id`、不同请求体**：返回 HTTP **409**。
- `GET /mosaics/{id}` 持久可取；输入摘要（不含大矩阵）随任务存入 SQLite，便于审计。

---

## 6. 选源优先级（固定、确定性）

在时相合格（距参考时间不超过 `max_time_delta_seconds`）范围内，逐像元按以下键字典序选最小：

1. 切片总云量 `cloud_fraction` 升序（云少优先）；
2. 与参考时间（所有切片的最新采集时间）的时间差升序；
3. 到切片左上角（原点）的轴对齐入深距离 `max(row, col)` 降序（优先远离切入边缘的像元）；
4. 切片在请求中的序号升序（最终确定性裁决）。

几何约束：切片必须与目标网格同分辨率（1e-6 相对容差），左上原点必须落在整数像元偏移上，
否则 422。

---

## 7. 字段速览

- 切片 `bands`：`[band, height, width]` 的 JSON 嵌套数组；或用 `bands_png`（base64，
  L/LA/RGB/RGBA 或单波段 16 位 `I;16`）。
- `cloud_mask`：`[height, width]`，`1=云`；或 `cloud_mask_png`（单波段 8 位 PNG，非零为云）。
- 输出 `bands` 为 `[band, H, W]` 浮点矩阵；`source_map` 为每像元来源序号（`-1` 空洞），
  颜色见 `source_map_png`；真彩预览（无数据透明）见 `preview_png`。
- 规模上限等可通过环境变量调整：`MOSAIC_MAX_PIXELS`、`MOSAIC_MAX_DIM`、
  `MOSAIC_ALIGN_TOL`、`MOSAIC_PREVIEW_EDGE` 等（见 `app/config.py`）。
