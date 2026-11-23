# Spec Delta

## Purpose

定义本地服务端宿主的可观察行为：草稿是权威文本、revision 单调、写入必须条件匹配、检查点不可变，以及锁与冲突发生时的诚实语义。它存在的目的是让 automation 的 apply/undo 有一个可校验的宿主，而不是把浏览器预览当成已保存。

## ADDED Requirements

### Requirement: 草稿是服务端权威且 revision 单调

The document host SHALL keep exactly one authoritative draft per document, and every accepted content change SHALL advance that draft's revision by exactly one.

#### Scenario: Reading the draft

- **WHEN** a client reads a document draft it is authorized to access
- **THEN** the response MUST include the current revision, content digest and draft content
- **AND** the response MUST carry an ETag that identifies that revision

#### Scenario: A rejected write does not advance the revision

- **WHEN** a conditional draft write fails
- **THEN** the draft revision MUST remain unchanged
- **AND** no checkpoint or receipt MUST be created

### Requirement: 草稿写入必须匹配当前 revision

The document host SHALL require every draft mutation to carry the revision it was based on, and SHALL reject a write whose base revision is not the current head.

#### Scenario: Missing precondition

- **WHEN** a draft write omits the conditional revision
- **THEN** the host MUST reject it as a precondition-required failure
- **AND** MUST NOT write content

#### Scenario: Stale precondition

- **WHEN** a draft write carries a revision that is no longer the head
- **THEN** the host MUST reject it with a version-mismatch failure
- **AND** the rejection MUST include the current head revision and content digest
- **AND** MUST NOT overwrite the stored draft

### Requirement: 相同内容不产生新 revision

The host SHALL treat a write whose canonical text and variables are identical to the current head as a no-op rather than a new revision.

#### Scenario: Autosave repeats the same content

- **WHEN** a draft write carries the current head revision but the same content
- **THEN** the host MUST confirm the write without advancing the revision
- **AND** MUST NOT create a duplicate checkpoint

### Requirement: 检查点不可变

The host SHALL preserve every accepted draft state as an immutable checkpoint and SHALL never rewrite or delete a checkpoint.

#### Scenario: A write creates a checkpoint

- **WHEN** a draft write advances the revision
- **THEN** the host MUST create a checkpoint for the new revision
- **AND** the checkpoint MUST record the same content digest as the draft head

#### Scenario: Restoring older content

- **WHEN** a client restores content from an earlier checkpoint
- **THEN** the host MUST write it as a new revision
- **AND** MUST NOT modify the earlier checkpoint or any intervening revision

### Requirement: 编辑锁带租约与 fencing

The host SHALL allow at most one active edit lock per draft, SHALL expire a lock when its lease ends, and SHALL reject writes that do not present the lock's current fencing token.

#### Scenario: Acquiring a lock

- **WHEN** an authorized editor acquires the lock for a free draft
- **THEN** the host MUST return a lock identifier, a lease expiry and a fencing token
- **AND** MUST reject a second active lock for the same draft

#### Scenario: Expired lease or stale token

- **WHEN** a write presents an expired lock, another owner's lock, or a fencing token that is not current
- **THEN** the host MUST reject the write as a lock conflict
- **AND** MUST NOT change the draft

### Requirement: 冲突必须保留本地内容

The host SHALL NOT resolve a draft conflict by discarding either side's content; a rejected write MUST leave the server head intact and MUST return enough information for the client to preserve the local content as a recovery draft.

#### Scenario: Autosave conflict

- **WHEN** a client's conditional save is rejected because the head moved
- **THEN** the response MUST identify the conflict and the current server head
- **AND** the client MUST be able to keep its local content as a recovery draft
- **AND** the server MUST NOT merge, rebase or overwrite either content automatically

#### Scenario: Applying an automation proposal after the head moved

- **WHEN** an apply request targets a draft whose head no longer matches the proposal baseline
- **THEN** the host MUST reject the apply as stale
- **AND** MUST NOT write content or consume the proposal

### Requirement: 宿主只返回当前身份可见的草稿

The host SHALL scope every draft, checkpoint, lock and receipt read to the current principal and workspace, and SHALL hide the existence of resources the principal cannot access.

#### Scenario: Cross-user access

- **WHEN** a principal requests another principal's draft or checkpoint
- **THEN** the host MUST return the same not-found response used for an unknown resource
- **AND** MUST NOT reveal its title, revision or existence

### Requirement: 生产模式必须失败关闭

The host SHALL allow its local adapters only in local or test mode, and MUST fail closed when configured for production without an approved host adapter.

#### Scenario: Production with local host

- **WHEN** the application starts in production mode while the local host adapter is configured
- **THEN** startup MUST fail with an explicit error
- **AND** MUST NOT serve draft or apply endpoints with local adapters