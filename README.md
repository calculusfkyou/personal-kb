# personal-kb

一個跑在自己電腦上的個人知識庫：用一句話請本地 LLM 幫你記筆記，看過差異、確認後才寫入；問問題時用 BM25＋向量搜尋＋筆記之間的 `[[連結]]` 找出相關筆記，再讓 LLM 根據筆記回答並附上出處。

**所有內容都留在本機**：模型由 [LM Studio](https://lmstudio.ai) 在本機執行，筆記是一般的 Markdown 檔，可以直接用 [Obsidian](https://obsidian.md) 閱讀和編輯。

```
你：kb note "最近都 11 點睡"

--- a/notes/private/睡眠.md
+++ b/notes/private/睡眠.md
 ## 作息
-- 平日大約凌晨 12 點半睡，早上 8 點起床
+- 2026-11 起改為 11 點睡，之前是 12 點半；早上 8 點起床（來源：[[inbox/2026-11-08-021946]]）
存檔？ [y/N]: y
```

## 架構

```
             kb note "一句話"                         kb ask "問題"
                   │                                       │
   相關筆記＋style.md ─┤                                       ▼
                   ▼                            BM25（jieba 斷詞）＋ Chroma 向量
          本地 LLM 輸出修改清單（JSON）                   │ reciprocal rank fusion
                   │                                       ▼
     edit.py：驗證路徑與規則 → 在記憶體中套用          順著 [[連結]] 多帶一層相關筆記
                   │                                       │
             顯示差異，等你確認                              ▼
                   │                               本地 LLM 依筆記回答，附上出處
   寫入筆記、原話存進 inbox/、更新 index.md 與 log.md
```

```
vault/
├── notes/
│   ├── private/      ← 私人筆記：AI 只能修改這裡
│   └── shared/       ← 可分享的筆記：只有你能手動編輯
├── inbox/            ← 每次對 AI 說的原話（AI 寫的每一行都會連回這裡）
├── imported/         ← PDF、Word、PPT 等轉成的 Markdown
├── style.md          ← 寫作偏好：AI 寫筆記前都會讀
├── index.md          ← 程式產生的目錄
├── log.md            ← 程式產生的變動紀錄
└── .trash/           ← AI 刪除的筆記，不會永久刪除
```

## 需求

- macOS 或 Linux、Python 3.12、[uv](https://docs.astral.sh/uv/)
- [LM Studio](https://lmstudio.ai)，開啟本機 Server（預設 `http://localhost:1234`），並下載：
  - 對話模型：`google/gemma-4-e4b`（預設，24GB 記憶體可以順跑）
  - Embedding 模型：`text-embedding-bge-m3`（多語言，中文效果好）

模型名稱和參數都在 `src/kb/config.py`。

## 使用方式

```bash
uv sync
mkdir -p vault/notes/private vault/notes/shared
uv run kb note "最近都 11 點睡"
uv run kb index
uv run kb ask "我平常幾點睡？"
```

預設讀取專案根目錄的 `vault/`，用 Obsidian 的「開啟資料夾作為 vault」打開它。`KB_VAULT` 可以指定其他 vault 資料夾，每個 vault 有各自的搜尋索引。

## 指令

| 指令 | 作用 |
|---|---|
| `kb note "<說明>"` | 請 AI 新增、修改或刪除筆記；先顯示差異，確認後才寫入 |
| `kb note --file <檔案> "<說明>"` | 附上 PDF、Word 等檔案，請 AI 依照說明整理成筆記 |
| `kb import <檔案>` | 只把檔案轉成 Markdown 放進 `imported/` |
| `kb index` | 同步搜尋索引，並重新產生 `index.md` |
| `kb search "<問題>"` | 只搜尋，列出段落（不呼叫 LLM） |
| `kb ask "<問題>"` | 根據筆記回答，附上出處；筆記裡沒有就說找不到 |
| `kb lint` | 健檢：孤兒筆記、失效連結、沒有摘要、互相矛盾；只產生報告 |
| `kb eval --questions <題目.yaml>` | 用一組固定的題目計算 hit@3、hit@5、MRR；`--answers` 會再檢查回答（找不到時要說找不到、有答案時要附出處） |

`note`、`ask`、`lint`、`eval` 都可以用 `--model` 換成其他 LM Studio 的模型。

## 安全與隱私的設計

- **確認前不寫入任何檔案**；取消、模型出錯、或預覽期間你在 Obsidian 改過筆記，都不會寫入
- AI 只能透過四種結構化動作修改筆記（新建、在段落後追加、替換一行、刪除整篇），**只能動 `notes/private/` 和 `style.md`**，任何一項不合格就整批拒絕
- 來源連結由程式加上，不讓模型自己寫；`index.md`、`log.md` 由程式產生
- 刪除的筆記移到 `.trash/`
- 所有送出筆記內容的地方都會檢查模型位址：不是 localhost 時排除私人內容（`note` 拒絕執行，`lint` 只做不需要模型的檢查）；不使用系統的 HTTP proxy 設定
- 筆記和附件裡的文字在 prompt 裡被標示為資料、不是指令；含有終端機控制字元或零寬字元等看不見字元的修改會被拒絕，避免內容在預覽中被藏起來；確認前會再列一次「新增／修改／刪除」的總覽

## 開發

```bash
uv run pytest
```

測試不需要 LM Studio：LLM 的呼叫都以假的回應取代。

## 已知限制

- 預設的 4B 模型偶爾會提出不合格或不夠精準的修改（例如改錯 `style.md` 的那一行），會被規則擋下或在預覽時由你取消；可以換個說法重試，或用 `--model` 換模型
- `kb lint` 的矛盾檢查由 LLM 判斷，同一個問題可能用不同說法列出兩次
- 附加檔案只會整理前 8000 字；掃描的 PDF 和圖片讀不到文字（沒有 OCR）
- 用檔名當筆記名：不同資料夾有同名筆記時，連結會混在一起
