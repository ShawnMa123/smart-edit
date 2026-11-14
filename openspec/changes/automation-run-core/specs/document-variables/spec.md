# Spec Delta

## Purpose

定义草稿变量值的版本化存储与并发语义，使正文保存与变量更新互不破坏。它存在的目的是让后续 fill / set_variable 能依赖稳定变量状态，而不是被一次 autosave 清空或让 `variables_version` 失去意义。

## ADDED Requirements

### Requirement: 正文保存不得改变变量

A save that changes only document content SHALL preserve the stored variables and their version.

#### Scenario: Autosave after typing

- **WHEN** a client saves only changed document text against the current draft revision
- **THEN** the stored variables MUST remain byte-for-byte equivalent
- **AND** `variables_version` MUST remain unchanged

#### Scenario: Omitted variables are not empty variables

- **WHEN** a content save omits the variables field
- **THEN** the host MUST preserve the existing variables
- **AND** MUST NOT treat omission as an instruction to clear them

### Requirement: 变量更新独立且必须版本匹配

A variable update SHALL be a separate conditional write that advances only the variables version.

#### Scenario: Updating variables

- **WHEN** a client updates variables with the current `If-Match: "variables-<version>"`
- **THEN** the host MUST store the new values and increment `variables_version` by exactly one
- **AND** the content revision MUST remain unchanged

#### Scenario: Stale variables version

- **WHEN** a variable update carries a variables version that is no longer current
- **THEN** the host MUST reject it as a version conflict
- **AND** MUST NOT change any variable value

### Requirement: 变量更新需要编辑权限与当前锁

A variable update SHALL require the `edit` capability and the current draft lock with a valid lease and fencing token.

#### Scenario: Missing edit capability or lock

- **WHEN** a principal without `edit`, or without the current lock, attempts a variable update
- **THEN** the host MUST reject the update
- **AND** MUST NOT change variables

### Requirement: 变量必须随检查点保存

Every accepted variable update SHALL create a checkpoint that records the variables and their version alongside the content revision.

#### Scenario: Reading a checkpoint

- **WHEN** a user reads the checkpoint created for a variable update
- **THEN** it MUST carry the variables and version that were current at that point
- **AND** restoring it MUST produce a new revision rather than rewriting history

### Requirement: 变量读取遵循文档权限

Variables SHALL be readable only to principals that can read the owning document, and unauthorized access MUST be indistinguishable from an unknown resource.

#### Scenario: Cross-user variable read

- **WHEN** a principal requests variables of another principal's document
- **THEN** the host MUST return the same not-found response used for an unknown document
- **AND** MUST NOT reveal variable names, values or counts

### Requirement: 变量版本是 automation 上下文的依赖

The variables version SHALL be part of any automation context that reads or proposes variable-dependent changes, and a change to it SHALL invalidate that context.

#### Scenario: Proposal after variable change

- **WHEN** variables change after an automation proposal is generated
- **THEN** the proposal MUST become stale
- **AND** MUST NOT be applied against the new variable state