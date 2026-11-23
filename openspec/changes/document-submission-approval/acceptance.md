# 验收记录：document-submission-approval

- 日期：2026-11-19
- 环境：PG 模式（`SMART_EDIT_AUTH_MODE=pg`）、`runs/host.db` SQLite v4、seed 账号
- 服务：`./scripts/dev.sh --pg --detach`（backend `:8000`、frontend `:5173`、`team04-pg` 隧道）
- 数据：`scripts/seed_identity_users.py --reset` 写入 Atlas Trade Bank / Applicant / BankOps / Compliance
- 可复现命令：

```bash
.venv/bin/python scripts/demo_submission_approval.py
```

## 实测输出

```text
1. submitted sub_98d7e276462c status=pending_first
2. applicant lock while pending -> 409 submission_pending
3. bank operations approve -> pending_second
4. compliance approve -> approved
5. approved document is read-only (lock -> 409)
6. bank operations return -> returned
7. returned -> edit -> resubmit sub_eb9eb722fac6
8. activity: approval.first.approved, approval.returned, approval.second.approved,
   document created, document locked, signed in, submission.created
OK: two-stage approval, read-only, return and resubmission all verified
```

## 验证点

| # | 验收项 | 结果 |
| --- | --- | --- |
| 1 | 提交冻结 revision/正文/摘要并返回 `pending_first` | ✅ |
| 2 | 审批中 `acquire_lock` / `save_draft` 返回 `409 submission_pending` | ✅ |
| 3 | BankOps 一审通过 → `pending_second` | ✅ |
| 4 | Compliance 二审通过 → `approved` | ✅ |
| 5 | 已批准文档仍只读（lock 409） | ✅ |
| 6 | Return 必须带意见，状态 `returned` 且 Applicant 可重新编辑 | ✅ |
| 7 | 重新提交生成新 submission，旧提交保留 | ✅ |
| 8 | Activity 写入 submission/approval 事件且不含正文 | ✅ |
| 9 | 越权/自审/无意见分别返回 403/403/422（API 测试） | ✅ |

## API 测试

```bash
.venv/bin/python -m pytest tests/test_approval_api.py tests/test_document_host_store.py -q
```

覆盖：提交成功、stale revision、fencing token 过期、缺失锁、两级审批、阶段错误 409、退回重提、自审 403、退回无意见 422、Activity 载荷。

## 前端验证

```bash
npm --prefix web run typecheck
npm --prefix web run test
```

覆盖：提交对话框（成功/409/403）、审批收件箱、Approve/Return、必填意见、只读状态与退回提示。

## 说明

- 本轮不发送邮件；审批人通过 Approval 待办与 Activity 感知变化。
- AI audit gate（`start_approval`）尚未接入提交/审批。
- 同一用户不能审批自己的提交；First/Second 由不同角色权限控制，未强制不同自然人。