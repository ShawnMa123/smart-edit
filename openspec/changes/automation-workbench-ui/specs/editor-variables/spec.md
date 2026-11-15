# Spec Delta

## Purpose

定义正文中的 variable reference 节点：如何从选区创建、如何显示值/占位、如何枚举 occurrence、如何与纯文本投影和 fallback 共存。它让变量成为可识别的文档结构，而不是靠全文字符串替换模拟。

## ADDED Requirements

### Requirement: variable reference 必须是可识别的正文节点

The editor SHALL represent a variable as an inline variable-reference node with a stable variable id and a display value or an explicit placeholder.

#### Scenario: Rendering a variable

- **WHEN** a paragraph contains a variable reference
- **THEN** the editor MUST render a non-editable chip showing the current value or `{{label}}` when empty
- **AND** the chip MUST identify its variable id

#### Scenario: Empty variable

- **WHEN** a variable has no value
- **THEN** the editor MUST show an explicit placeholder rather than blank text
- **AND** the placeholder MUST be distinguishable from ordinary text

### Requirement: 选区必须可以转换为 variable

The editor SHALL allow a non-empty selection in a paragraph or heading to be converted into a variable reference.

#### Scenario: Converting a selection

- **WHEN** the operator marks a non-empty selection as a variable and confirms its definition
- **THEN** the selected text MUST be replaced by one variable-reference node
- **AND** the selected text MUST become the initial display value unless the operator clears it
- **AND** the operation MUST be undoable through the editor history

#### Scenario: Unsupported selection

- **WHEN** the selection crosses blocks, a table cell boundary, or a protected structure
- **THEN** the conversion MUST be rejected
- **AND** the editor MUST explain why

### Requirement: 同一变量的所有 occurrence 必须共享值和标识

Every occurrence of a variable SHALL reference the same variable id and SHALL display the same current value.

#### Scenario: Value update

- **WHEN** the variable value changes in the variables surface
- **THEN** every occurrence MUST display the new value together
- **AND** MUST NOT modify same-named ordinary text

#### Scenario: Occurrence inventory

- **WHEN** the operator inspects a variable
- **THEN** the editor MUST provide every occurrence by stable node/occurrence identity
- **AND** MUST NOT infer occurrences by text search

### Requirement: 变量节点不能被普通文本编辑破坏

The editor SHALL prevent ordinary text editing or a text-range replacement from silently splitting or corrupting a variable-reference node.

#### Scenario: Text replacement across a variable

- **WHEN** a text replacement range crosses a variable reference
- **THEN** the replacement MUST be rejected
- **AND** the variable node MUST remain intact

#### Scenario: Deleting a variable

- **WHEN** the operator deletes a variable reference
- **THEN** the editor MUST treat it as a structural change
- **AND** a required variable MUST be reported as missing rather than silently disappearing

### Requirement: 纯文本投影必须与变量节点一致

The canonical plain-text projection SHALL include a variable's display value when present and an explicit `{{label}}` placeholder when empty.

#### Scenario: Projecting a filled variable

- **WHEN** a document containing a filled variable is projected
- **THEN** the projected text MUST contain the display value at the variable position

#### Scenario: Projecting an empty variable

- **WHEN** a document containing an empty variable is projected
- **THEN** the projected text MUST contain the explicit placeholder
- **AND** MUST NOT contain an invented value

### Requirement: fallback 编辑器必须诚实处理变量

When the rich editor cannot start, the textarea fallback SHALL show variable placeholders and SHALL disable variable creation and fill.

#### Scenario: Fallback with variables

- **WHEN** the editor falls back to a textarea and the document contains variables
- **THEN** the fallback MUST show `{{label}}` placeholders
- **AND** MUST NOT offer mark-as-variable or fill actions
- **AND** MUST explain that variable editing needs the rich editor