# 知途 · 内部求职服务工作台

面向小型求职服务机构的 B/S 工作台。Vue 3 + TypeScript + Element Plus；FastAPI + SQLAlchemy + Alembic；PostgreSQL 16。岗位只通过 Excel 导入。AI 推荐采用本地中文 Embedding + Qdrant 向量检索 + DeepSeek 精选；基础功能不依赖外部 LLM，无需 Redis 或任务队列。

## 已实现

- 管理员与顾问登录；Argon2 密码哈希；HttpOnly、SameSite=Strict 会话 Cookie；数据库保存会话摘要，支持退出、到期和撤销；连续登录失败限制。
- 管理员创建、停用顾问和重置密码。停用或重置会撤销会话；初始管理员通过命令行创建，无默认账号密码。
- Excel 模板下载（下拉选项、字段说明）、校验预览、确认入库、错误与重复明细下载、批次历史。
- 共享岗位的分页搜索、详情、编辑、手动失效和按截止日期自动判定失效。
- 学员资料（含学校）、意向与服务状态；顾问仅访问本人学员，管理员可转交负责人。
- 私有 PDF、DOCX、JPG、PNG 简历上传、版本记录与鉴权下载。MVP 将文件内容保存在 PostgreSQL，单份上限 5MB。
- 简历档案中的每个版本可单独删除，删除前需确认。仅负责顾问和管理员可删除；原文件与识别缓存一起移除，记录删除操作日志。已填入的学员资料、其他简历版本、推荐和跟进记录保留。删除后不能从工作台恢复，既有数据库备份按备份保留策略处理。
- 上传简历后本地提取姓名、手机号、学校、专业、学历，展示原文依据与现有值，经顾问核对并勾选后填补。已有值默认不选中，支持修改识别结果；也可对历史简历点击“识别信息”。不调用外部 AI 服务。
- 手动推荐岗位并保存岗位快照；记录投递、面试等进展、沟通内容和下一次跟进日期。
- 学员档案中的每条已推荐岗位支持「取消推荐」，确认后移除该条推荐并解除已有跟进的岗位关联；跟进内容、进展和提醒日期保留，其他推荐不受影响。岗位仍有效时可重新推荐，符合匹配规则时重新参与前 5 个候选排序。仅负责顾问或管理员可操作，取消写入操作日志。
- 学员档案内查看规则匹配岗位，每次最多展示 5 个，通过城市、意向岗位、学历和专业条件后才入选，支持刷新、核对详情后逐条推荐。自动排除失效和已推荐岗位。
- 可选 DeepSeek AI 简历推荐：选择简历，明确同意发送后，基于技能、项目和经历语义匹配已有岗位；展示分析、简历/岗位原文依据和待核对项，最多 5 个候选，仍须逐条确认。未配置密钥时显示待配置状态，不自动调用外部模型。
- AI 候选卡片和核对弹窗均支持「不采用」，仅从本次结果移除，不创建推荐记录、不额外调用模型；可「撤销上一次」恢复。重新生成、刷新页面或更换简历后可能再次出现，不是永久屏蔽。
- Qdrant RAG：所有有效岗位建立本地向量索引；新增和编辑触发增量同步，失效岗位清理。按学员条件检索最多 40 个不同岗位供 DeepSeek 精读，长描述按段索引；页面展示索引规模及本次检索规模，不将向量相似度当作录用概率。
- 在共享岗位库的岗位详情中选择有权限的学员并直接推荐；学员档案中的“去共享岗位库推荐”会带上当前学员，筛选后可直接推荐给该学员。推荐对象支持搜索与分页，失效岗位不能推荐。
- 工作概览与到期跟进提醒；管理员查看关键操作日志。

## 方式一：Docker Compose

需要 Docker Desktop / Docker Engine（Compose v2）。在项目根目录运行：

```powershell
Copy-Item .env.example .env
# 编辑 .env，将 POSTGRES_PASSWORD 替换为随机密码，建议只使用字母和数字。
docker compose up -d --build
docker compose exec backend python -m app.manage create-admin --username admin --name 管理员
```

创建管理员时交互输入密码两次，至少 10 位。访问 http://127.0.0.1:8080 。后端启动时执行 `alembic upgrade head`，不通过 `create_all` 建业务表。

后端镜像已经集成本地 CPU PaddleOCR。首次构建会下载 Python 依赖和两个公开模型，时间和镜像体积比普通后端更大；运行时使用镜像内的模型，不下载模型或向外部服务发送简历。无需独立显卡、Redis 或 Celery。

Compose 同时启动内部 Qdrant 和独立的 CPU 向量检索服务。向量服务首次构建下载中文 Embedding 模型，运行时离线推理，不增加 Embedding API 密钥。Qdrant 与向量服务均不映射宿主机端口；原有 8080 和 8000 入口不变。Qdrant 的命名卷 `qdrant_data` 与 PostgreSQL 数据卷独立。

后端同时绑定本机 8000 端口，可供 Vite 的 5173 开发页面使用。当前开发环境已将后端切换为 Docker，直接运行 `npm.cmd run dev` 即可连接；不要再同时启动占用 8000 的本机 uvicorn。可通过根目录 `.env` 的 `BACKEND_PORT` 修改映射端口，并对应调整前端 `BACKEND_URL`。

默认仅绑定本机，数据库端口为 55432，避免与其他项目的 5432 冲突。已有 `.env` 时不要覆盖；本次开发环境已生成随机数据库密码。

```powershell
docker compose stop
docker compose start
docker compose logs --tail 100 backend
docker compose exec backend python -m app.manage reset-password --username admin
```

数据库使用命名卷保存。`docker compose down` 保留数据卷；不要执行 `down -v`，该选项会删除数据库数据。

## 方式二：本地开发

需要 Python 3.12、Node.js 22.12+ 和 PostgreSQL 16。以下示例使用 PowerShell，从项目根目录开始。

### 数据库和后端

```powershell
Copy-Item .env.example .env
# 设置 .env 的 POSTGRES_PASSWORD
docker compose up -d db
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt --index-url https://pypi.org/simple
Copy-Item backend\.env.example backend\.env
# 修改 backend/.env，让 DATABASE_URL 的用户名、密码、端口与根目录 .env 一致。
Set-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m app.manage create-admin --username admin --name 管理员
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 前端（另开终端）

```powershell
Set-Location frontend
npm.cmd ci
npm.cmd run dev
```

访问 http://127.0.0.1:5173 。前端 `/api` 代理到本地 8000，无需将 Cookie 或令牌写入 localStorage。

普通本机开发默认不安装 PaddleOCR，也不启用 OCR。若需要在本机执行 OCR，在虚拟环境中额外安装 `backend/requirements-ocr.txt`，设置 `OCR_MODEL_DIR` 为可写的绝对路径后执行 `python -m app.ocr_models` 下载模型，再将 `OCR_ENABLED=true`。通常直接使用 Docker 后端更省事。

API 文档：http://127.0.0.1:8000/docs 。写入接口要求 `X-Requested-With: career-web` 请求头（前端自动添加）。直接用 HTTP 客户端测试时，请携带此请求头并保留登录 Cookie；Swagger 的默认 Try it out 不会添加该请求头。

## Excel 导入约定

先登录，在「Excel 导入」下载模板。只读取一个工作表，列名和顺序必须与模板相同：

| 列名 | 规则 |
| --- | --- |
| 岗位名称、公司名称、城市 | 必填，文本 |
| 学历要求 | 不限 / 高中及以下 / 中专 / 大专 / 本科 / 硕士 / 博士；留空按不限 |
| 经验要求 | 不限 / 应届生 / 1年以下 / 1-3年 / 3-5年 / 5年以上；留空按不限 |
| 专业要求 | 可选文本，留空不推测专业条件 |
| 最低月薪（元）、最高月薪（元） | 均可留空，也可只填其中一项；填写时为人民币元/月、0～1,000,000 的整数；两项都填时下限不高于上限 |
| 岗位描述、来源 | 可选文本；来源可填招聘链接或内部来源说明 |
| 截止日期 | 可选，YYYY-MM-DD 或 Excel 日期；按北京时间判断到期 |

- 仅 `.xlsx`，上限 10MB、2,000 行；拒绝公式和异常压缩工作簿。
- 岗位名称 + 公司 + 城市去除首尾空格并忽略英文大小写后，构成重复键。同一岗位重新开放时，可编辑并重新启用原岗位。
- 上传只产生预览批次；用户确认后才入库。有效行入库，错误和重复行跳过，已有岗位不被覆盖。
- 待确认批次可在预览区或导入历史中取消，包括全部重复或全部错误的批次。取消后状态为“已取消”，保留校验记录且不能再次确认入库；需要导入时重新上传。已完成批次不能取消。
- 预览与确认之间出现的重复由数据库唯一约束拦截；确认接口有批次状态保护，重复提交返回 409。
- 错误明细中的公式文本会转义，避免下载后被 Excel 当成公式执行。
- 修正错误时，按标准模板重新上传；错误明细包含辅助列，不能直接作为模板导入。

## 权限与业务约定

- 顾问共享全部岗位；仅访问自己负责的学员、简历、推荐和跟进。访问限制在每个后端入口执行。
- 管理员可访问全部学员和导入记录。普通顾问只能查看本人导入批次。
- 学员转交后，其关联记录随学员权限一同转交；日志保留原负责人和新负责人编号。
- 推荐岗位时保存完整业务快照；岗位后续编辑不会改变推荐历史。同学员同岗位不重复推荐。
- 到期提醒以学员**最新一条跟进记录**的下一次跟进日期为准。新记录不设置日期即取消该学员的当前提醒。当前概览最多显示 20 条，只展示服务中的学员。
- 简历以附件下载，不公开静态文件地址。文字 PDF 与 DOCX 直接提取；扫描 PDF、JPG、PNG 由本地 OCR 识别。加密或解析失败会提示手动填写，上传文件仍保留。手机号当前识别中国大陆 11 位号码；学校与学历仅在明确标签或教育经历中提取，专业和姓名优先使用明确标签。识别有歧义时不擅自选择，不保证任意排版都能完整识别。
- 简历确认接口仅允许更新姓名、电话、学校、专业、学历，并再次检查学员归属及所选字段的原值。资料发生并发修改时拒绝覆盖，要求刷新重试；原文和识别结果不写入操作日志。

## Qdrant RAG 检索

- 使用 `Qdrant v1.18.0`、`FastEmbed 0.9.1`、中文模型 `BAAI/bge-small-zh-v1.5`，512 维余弦相似度。独立向量服务最多 2 CPU/1GB，Qdrant 上限 768MB，避免与后端 OCR 依赖冲突。
- 模型构建时从官方 Hugging Face 仓库 `Qdrant/bge-small-zh-v1.5` 下载固定快照，保存 revision 和文件 SHA-256 到镜像 `/opt/embedding-model/manifest.json`。运行时显式使用该目录，不下载模型；模型 revision 和分段版本均纳入岗位摘要，变更后自动重新生成对应向量。
- 全部有效岗位参加建索引，而非只索引前 40 个。岗位描述分段并保留重叠，避免只索引开头；长查询分段编码后聚合。Qdrant 按 `job_id` 分组，每个岗位只占一个候选名额。
- PostgreSQL 保持业务真源。后端启动、每 60 秒、岗位导入或编辑后进行全量核对，仅为变更岗位重新编码；已失效或到期岗位从索引清理。同步失败会保留业务数据并在后续核对重试。检索前会再次核对本次候选的向量版本，防止后台同步尚未完成导致漏掉刚导入的岗位。
- 每次检索以数据库中有效、未推荐且符合城市/学历条件的岗位编号限定范围；从该范围中向量召回最多 40 个，再让 DeepSeek 精读精选最多 5 个。当前是向量相似度召回，不代表全库岗位逐个经过 LLM 判断，也不保证完美召回。
- Qdrant 只持久化共享岗位分段与向量。简历分析形成的查询和查询向量仅在当次请求内存使用，不写入向量库。简历发送给 DeepSeek 仍遵循主动同意及原文遮盖流程。
- 页面「AI 简历推荐」展示索引岗位数、符合基本条件的岗位数、本次召回数和最终候选数。向量服务未就绪时禁止生成，明确失败，不静默回退到关键词召回。
- 管理员可调用 `POST /api/ai/reindex` 立即核对索引；也可在项目根目录执行 `docker compose exec backend python -m app.vector_index`。这会重建派生索引，不删除业务岗位。日常导入和编辑无需手动执行。
- 查看状态：`docker compose ps`、`docker compose logs --tail 50 retrieval`。Qdrant 数据丢失时，可由 PostgreSQL 全量重新生成，代价是本地重新编码时间。请勿使用 `docker compose down -v` 清理，这也会删除业务数据库卷。
- 本机后端开发需要配置 `RETRIEVAL_URL` 指向可访问的向量服务；默认 Compose 已自动配置内部地址。服务每次接收最多 20,000 个岗位，面向当前 MVP 规模；更大岗位库需改为数据库增量游标和分批召回过滤。
- 官方参考：[FastEmbed 模型](https://qdrant.tech/documentation/embeddings/fastembed/)、[Qdrant 分组查询](https://api.qdrant.tech/v-1-18-x/api-reference/search/query-points-groups)。

## DeepSeek AI 简历推荐

1. 在根目录 `.env` 填写 `DEEPSEEK_API_KEY`，可用 `DEEPSEEK_MODEL` 指定模型（默认 `deepseek-flash`）。不要将密钥填写到前端代码或聊天中。
2. 首次更新代码运行 `docker compose up -d --build backend frontend`。以后仅修改密钥时，运行 `docker compose up -d --force-recreate backend frontend` 重新加载环境变量。本机 uvicorn 开发使用 `backend/.env` 并重启后端。
3. 打开学员档案的「AI 简历推荐」，上传或选择简历，阅读发送说明并勾选同意，再点击「分析简历并推荐岗位」。初次使用请核对服务账号是否有 API 权限和余额。
4. 查看分析和两侧原文依据，点击「核对 AI 推荐」，确认学员与岗位后逐条保存。生成候选本身不创建推荐记录，不自动修改学员资料。保留现有取消推荐功能。

- PDF、DOCX、JPG/PNG 先在本地提取/OCR；发送前遮盖已知姓名、手机号、邮箱和身份证号。仅发送其余文字、意向、学历/专业和候选岗位条件，不上传简历原文件、完整学员档案或备注。遮盖不等于完整匿名化，发送前应确保有权使用这些简历内容。
- 每次生成通常两次模型调用：一次提取有证据的技能和经历，一次排序。每次 API 调用超时 40 秒，失败不自动重试，已提交请求可能仍产生费用；每进程最多同时处理 2 次分析。原文最多 24,000 字符，超限明确提示；现有 OCR 页数限制仍适用。
- 城市和学历优先使用已编辑资料；模型分析仅在学历未指定时提供补充。先排除失效、已推荐及明确不满足城市/学历的岗位，再通过 Qdrant 向量召回最多 40 个供模型语义排序。岗位描述的命中分段同时提供给 DeepSeek，便于核对长描述末尾的职责。名称不必逐字匹配，不通过严格规则匹配的专业缺失岗位仍可能被 AI 作为职责相关候选，并明确待核对信息。
- AI 结果仅接受当前候选中的真实岗位 ID，最多 5 个、不可重复；技能/经历与推荐依据必须能在发出的简历和岗位原文中核对。格式、原文引用或岗位 ID 异常时拒绝整次结果，不用规则匹配冒充 AI。原文存在并不能证明模型推理必然正确，仍需顾问核对硬性要求。
- 生成后重新检查学员权限、简历是否仍存在、资料是否变化及岗位状态，排除变化后的失效结果。分析不持久化到业务库；页面刷新、更换简历或修改意向需重新生成。原有基础信息识别缓存仍仅用于本地识别。
- `GET /api/ai/status` 返回是否已配置（不返回密钥，配置状态不代表真实调用已验证）；`POST /api/students/{id}/ai-matched-jobs` 接收 `resume_id` 与必填的 `consent: true`，返回分析、依据及候选。操作日志只记录动作和简历编号，不保存原文、提示词、模型回复或密钥。
- 官方参考：[DeepSeek 对话接口](https://api-docs.deepseek.com/api/create-chat-completion/)、[JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)。当前接入采用 JSON 输出并在后端独立校验，不把 JSON 格式正确当作匹配判断正确。

## 岗位匹配规则

- 入口位于学员档案的「匹配岗位」。仅负责顾问和管理员可访问，学员转交后按新负责人权限生效。
- 使用现有资料进行规则判断，不调用外部 AI 服务。候选排序依据依次为意向岗位名称关键词、城市、专业文本重合和学历条件；同等条件下新岗位在前。排序不表示录用概率或综合能力评分。
- 城市按名称比较，忽略末尾的「市」。意向城市和意向岗位支持用逗号、顿号、分号、斜线或竖线填写多个选项；城市可填「不限」或「全国」。不推断省市关系、通勤圈或城市别名。
- 学历按是否达到岗位要求判断，本科可匹配大专及以下要求，硕士可匹配本科及以下要求。「不限」作为学员学历时不能匹配有学历限制的岗位；高中与中专不互相认定符合。共享岗位库原有学历筛选仍按要求精确查询。
- 意向岗位按至少两个字符的关键词是否出现在岗位名称中判断，忽略英文大小写、全半角和空白；未命中的岗位不入选，暂不推断同义岗位。岗位专业要求必须明确为不限，或存在至少两个字符的专业选项包含于学员专业中；包含否定、排除条件时保守排除，具体专业原文仍需顾问核对。
- 学员未填写城市、意向岗位时不生成候选；学员缺少专业时只匹配明确写专业不限的岗位。岗位未填写专业时不入选。页面列出待完善资料，不用未匹配岗位补足数量。当前学员档案未记录工作经验和期望薪资，这两项不参与筛选，展示核对提示。
- 推荐前展示岗位描述、来源、条件、待核对项及学员编号；顾问确认后复用原有推荐接口保存最新岗位快照，并刷新候选列表。提交时再次检查权限、有效状态和重复推荐。
- `GET /api/students/{id}/matched-jobs` 在服务端固定最多返回 5 个候选，返回 `total`（通过筛选总数）、`limit` 和 `missing_fields`。无分页或批量推荐；少于 5 个按实际数量返回，推荐后补入下一候选。此上限限制每次展示的候选数，不限制学员历史推荐总数。当前面向 MVP 岗位规模，在服务端对有效且未推荐岗位计算并排序，暂无匹配结果缓存。

## 本地 OCR

- 使用 `PaddleOCR 3.3.3`、`PaddlePaddle CPU 3.2.2`，模型为 `PP-OCRv5_mobile_det` 和 `PP-OCRv5_mobile_rec`，与 FastAPI 在同一个容器中运行。
- 模型构建时从官方地址下载，记录来源和 SHA-256 到 `/opt/ocr-models/manifest.json`。推理使用显式本地路径；已通过断网容器真实识别测试。
- 图片仅支持单张 JPG/PNG，不超过 2,000 万像素；处理前按 EXIF 纠正方向，并缩小过大的图片。请上传方向正确、文字清晰的文件，暂不进行复杂弯曲校正。
- PDF 最多查看前 20 页，其中仅对文字稀少/缺少文字层的页面执行 OCR，最多 5 页；超过限制会提示，已识别内容仍可确认。混合 PDF 会合并文字页与 OCR 页的结果。
- 每个后端进程只同时识别一份扫描简历，忙碌时提示稍后重试；原文件先保存，不会因识别忙碌或超时而丢失。工作进程复用已加载模型，90 秒超时后终止并在下次请求重建。Compose 为后端配置最多 2 CPU、3GB 内存。
- 正常结果缓存在同一份简历的数据库记录内，重复点击“识别信息”直接复用；缓存仍遵循学员归属权限。超时、服务不可用等临时失败不缓存。修改识别规则或模型时更新解析版本即可使缓存失效；接口支持 `GET /api/resumes/{id}/extraction?refresh=true` 强制重试。
- 上传和识别都只给出字段建议，顾问确认后才写入资料；低置信度文字会跳过并提示核对，不把 OCR 分数描述为字段正确率。

配置项：`OCR_ENABLED`、`OCR_MODEL_DIR`、`OCR_TIMEOUT_SECONDS`。登录后 `GET /api/ocr/status` 可查看模型和依赖是否就绪。修改基础运行依赖后需 `docker compose up -d --build backend` 更新镜像。

官方参考：[OCR Python 接入](https://www.paddleocr.ai/v3.0.0/en/version3.x/pipeline_usage/OCR.html)、[检测模型](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/module_usage/text_detection.en.md)、[识别模型](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/module_usage/text_recognition.en.md)。

## 验证

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m alembic check
Set-Location ..\frontend
npm.cmd run build
npm.cmd audit --registry=https://registry.npmjs.org
```

默认后端测试使用临时 SQLite，不接触业务库。也支持在**空的、专用的测试数据库**运行：设置 `TEST_DATABASE_URL` 后运行 pytest。测试会创建和删除业务表，禁止指向正式数据库。

浏览器测试使用独立的 `career_e2e` 数据库，前端 15173、后端 18000：

1. 在 PostgreSQL 创建 `career_e2e`；将运行测试服务的 `DATABASE_URL` 指向它。
2. 后端执行 `alembic upgrade head`、`python -m app.e2e_setup`，再用 uvicorn 启动 18000 端口。
3. 前端设置 `BACKEND_URL=http://127.0.0.1:18000`，执行 `npm.cmd run dev -- --port 15173`。
4. 前端执行 `npx.cmd playwright install chromium` 和 `npm.cmd run test:e2e`。测试使用项目根目录 `.venv` 中的 Python 生成 Excel 测试文件。

E2E 初始化命令仅允许名称以 `_e2e` 结尾的数据库。其固定测试账号不能用于业务环境；每次工作流测试会在测试库新增一组唯一命名的数据。截图输出到 `artifacts/`。

真实 OCR 测试需在专用测试库上使用已启用 OCR 的后端镜像。可在项目根目录执行 `.\.venv\Scripts\python.exe backend\scripts\create_ocr_fixtures.py` 生成虚构简历图片和扫描 PDF（非 Windows 环境用 `--font` 指定中文字体）。随后在前端测试终端设置 `$env:E2E_OCR='true'` 再运行 Playwright。默认测试不加载真实 OCR 模型。

`backend/scripts/ocr_smoke.py` 可以在禁网容器中对这些虚构文件执行真实模型测试。脚本参数为包含 `resume.png`、`resume.jpg`、`scan.pdf` 的目录，不连接业务数据库。

## 目录

```text
backend/
  app/                 接口、权限、模型、校验和 Excel 处理
  migrations/          Alembic 版本化迁移
  tests/               业务与权限集成测试
frontend/
  src/                 Vue 工作台与学员档案组件
  tests/               Playwright 浏览器流程测试
retrieval/              本地中文 Embedding 与 Qdrant 检索服务
compose.yaml           PostgreSQL + Qdrant + 检索服务 + 后端 + Nginx 前端
```

## 当前边界

这是可本地运行的业务 MVP。简历基础信息识别采用本地文本提取、OCR 与规则；配置密钥后可主动使用 Qdrant RAG 与 DeepSeek 简历分析推荐。共享岗位库的普通搜索仍使用数据库条件查询，尚未实现岗位 API 采集或自动批量投递。

如需给团队通过内网使用，部署时配置内网域名与 HTTPS，并将 `COOKIE_SECURE=true`；设置适当的访问入口和数据库备份。简历属于私有数据，数据库备份也包含简历内容。当前不提供自助注册、邮箱找回、全文检索、任务调度和细粒度组织权限。
