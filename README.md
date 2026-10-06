# DDES

Last updated: 2026-10-06 (UTC+8).

DUT Differential Equations Seminar

## About

This repository contains the webpage for the DUT Differential Equations Seminar.

## Usage

Open `index.html` in a browser.

## 日程与报告管理

网站的「管理日程」打开 [管理页](https://dutdynamics.github.io/ddes/manager.html)。
可以修改尚未开始的报告、添加报告、导入日程表或保存草稿。新报告需自行选择
日期，常规日程为周四，默认时段 09:00–09:45、Room 114、标题和摘要 TBA。
历史报告不会进入编辑列表。个人经历支持职位选项和自定义文字；研究兴趣逐条
填写，PDF 中以英文逗号分隔、英文句号结束。

生成 PDF 或发布修改时，双击本项目的 `start-manager.cmd`，浏览器会打开
`http://127.0.0.1:8765/manager.html`。如果从网站下载单独的启动文件，它会
先下载 GitHub 上最新的项目到本机，再启动助手。本地助手使用本机已有的
GitHub CLI 登录（`gh auth login`）和 XeLaTeX，无需在网页里输入令牌。
需要 Python 3.11 或以上，也支持 Codex 自带的 Python。此电脑的
`D:/Software/TexLive/texlive/2026/bin/windows/xelatex.exe` 会自动识别。
网页草稿与本机草稿保存在各自浏览器地址下，可通过「导出草稿／导入」转移。

点击「生成 PDF」使用 `report-template/` 中的原始 XeLaTeX 模板、校徽和二维码，
填写报告标题、摘要、个人经历与研究兴趣。PDF 先供本机预览和下载；只有勾选
「同时发布此报告的 PDF」并确认公开，发布时才会将该 PDF 加入网站。公开的
个人经历和研究兴趣保存在 `seminar-profiles.json`，切勿填写不希望公开的信息。

发布会读取 GitHub 最新主分支，核对打开页面时的版本和报告内容，创建普通分支
及拉取请求，再按仓库允许的规则合并。远端有新修改时停止发布并保留草稿；
分支保护要求审核时提供拉取请求链接。不会强推，也不会修改本地工作树中的
未提交内容。已归档报告和未编辑报告的 HTML 保留原文。网页部署通常需要
等待 GitHub Pages 构建完成。

助手仅监听 `127.0.0.1`，写入操作验证本机来源和随机请求标识。LaTeX 编译
禁用 shell escape，并限制公式指令；个人经历和普通文字均作转义。关闭助手
可在 PowerShell 中查找启动的 `manager_server.py` 进程后停止它。

验证命令：`python -m unittest discover -s scripts -p 'test_*.py'`，以及
`node --test scripts/test_calendar.cjs scripts/test_manager_core.cjs`。

## Website

GitHub Pages publishes the main branch at https://dutdynamics.github.io/ddes/

## Calendar and maintenance

The shared calendar reads reports from the event cards in `index.html`. Its labels
are Past, Upcoming (within seven days), and Scheduled. Report times use Dalian
time (UTC+8). New reports default to Room 114; leave the title and abstract as TBA
until supplied by the organizer. Do not infer missing speakers, dates, or times.

Official holiday ranges are maintained in `holidays.js`, with the source URL,
publication date, and verification date. Only holidays falling on the regular
Thursday seminar slot are marked red and labeled **Public holiday**. Other days
within a holiday range retain their normal calendar appearance. The calendar
displays only Public holiday, without a festival name or source link. Sources
remain in the maintenance data. Reports listed on a highlighted date remain
reachable; a holiday does not silently cancel or reschedule a report.

### Check on 2026-09-10

- Source: [DUT holiday notice, published 2026-09-07](https://kfqxqzhb.dlut.edu.cn/info/1071/2002.htm).
- No public holiday overlaps September 10–24. The announced Mid-Autumn holiday
  is September 25–27 and National Day holiday is October 1–7. Only October 1 is
  a Thursday and receives the red calendar label.
- September 20 and October 10 are makeup workdays, not public holidays.
- The Tencent Time Plan link supplied by the organizer denied anonymous reading
  and export. No new speakers or times could be verified or imported.
- Follow-up cadence: check official DUT notices every two weeks; remind the
  organizer each Monday to submit the latest Time Plan export or screenshot.
  These follow-ups run in the Codex desktop task, not in GitHub Pages.

### Friday archive check (2026-09-11)

The existing Codex desktop follow-up also checks ended reports every Friday at
09:00 Beijing time. It syncs the latest repository, runs the archive program,
reviews the changes and publishes them through a pull request. The computer and
Codex app must be running for this local scheduled task. If no report has ended,
no commit is created.

Run `python scripts/archive_events.py` to preview eligible reports, then add
`--write` to move them from Upcoming Events into the matching Past Events
semester. The program preserves each card's HTML, title, abstract, speaker,
location and ID, changing only its upcoming/past class. Existing shared calendar
styles continue to apply. New archives are appended below existing reports;
multiple reports in the same batch are added in ascending date order (older
above, newer below). Missing semester sections and navigation buttons are
created automatically (fall: September–January; spring: February–August).

Reports become eligible at their end time in UTC+8. Multi-day reports wait for
the final day's end time. Missing or invalid end times wait until the next day;
unrecognized dates are left untouched and printed for review. Repeated runs do
not duplicate reports. Structural HTML errors stop the operation before writing.

For a reproducible preview, use
`python scripts/archive_events.py --now 2026-09-11T09:00:00+08:00`.
Run the checks with `python -m unittest discover -s scripts -p 'test_*.py'`.

### Recognition checks (2026-10-01)

The calendar and archiver validate complete dates (English month names or ISO
`YYYY-MM-DD`) and 12/24-hour time ranges. Multiple sessions and date-labeled
sessions are supported; a multi-day report waits for the final session on its
last day. Unknown, invalid or ambiguous times wait until the next midnight in
UTC+8. No partial date range or malformed 12-hour clock is treated as valid.

Calendar and archive regression checks share the same date/time examples. Run
`python -m unittest discover -s scripts -p 'test_*.py'` and
`node --test scripts/test_calendar.cjs`. Node needs no additional packages.

Navigation uses one initializer. Report links open the corresponding semester
and calendar month; malformed URL fragments do not interrupt the page.

MathJax remains pinned to 4.0.0. Its speech-rule mathmaps use the same-version
jsDelivr path because the original BootCDN resource URL fails to load. The
[official loader options](https://docs.mathjax.org/en/v4.0/options/startup/loader.html)
support configuring the mathmaps path separately. Formula startup and all 53
rendered formulas were checked in the browser without loading errors.
