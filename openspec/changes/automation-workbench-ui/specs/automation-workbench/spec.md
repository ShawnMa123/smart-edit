# Spec Delta

## Purpose

定义 Automation 助手在前端先行阶段的三块工作台：把当前导入或编辑的文档存为 template、把选中文本标记为 variable 并预览 fill、以及导入下游 API template 后生成匹配候选与 JSON payload 预览。Template 捕获/管理使用浏览器本地存储（非服务端）；variable fill 与 mapping 仍为 fixture/mock；不声称服务端持久化、真实模型或外部发送。

## ADDED Requirements

### Requirement: 工作台必须提供三块区域

The Automation tab SHALL present Template, Variables & Fill, and Downstream Mapping as three distinct working areas within the same automation surface.

#### Scenario: Opening the workbench

- **WHEN** the operator selects the Automation tab
- **THEN** the Template, Variables & Fill, and Downstream Mapping areas MUST be reachable
- **AND** the fixture-backed boundary MUST be visible
- **AND** the workbench MUST NOT claim a complete automation assistant

#### Scenario: Switching areas

- **WHEN** the operator moves between the three areas
- **THEN** the current document/draft context MUST remain visible
- **AND** unsaved mock state MUST NOT be silently discarded

### Requirement: 当前文档必须可以存为 template

The Template area SHALL capture the current imported or edited document as a named template, and the captured template MUST contain the document content at capture time plus the source, revision, character count and variable summary needed to inspect it later.

#### Scenario: Capturing a template

- **WHEN** the operator confirms a capture with a non-empty name
- **THEN** the workbench MUST store the current rich document, projection character count, source, draft revision and variable summary
- **AND** the new template MUST appear in the template list with its name, version and captured time
- **AND** the workbench MUST state that the template was saved in this browser, not on the server

#### Scenario: Capture is a snapshot

- **WHEN** the operator edits the working document after capturing a template
- **THEN** the stored template MUST remain the captured content
- **AND** the template detail MUST show the captured content, not the live document

#### Scenario: Blank or whitespace-only name

- **WHEN** the operator attempts to capture with a blank or whitespace-only name
- **THEN** the capture MUST be rejected with a readable message
- **AND** no template MUST be stored

#### Scenario: Empty document

- **WHEN** the current document has no content
- **THEN** the capture action MUST be unavailable
- **AND** the workbench MUST explain that a template needs document content

#### Scenario: Reloading after capture

- **WHEN** the page is reloaded in the same browser
- **THEN** the template list MUST restore previously captured templates from browser-local storage
- **AND** the UI MUST NOT claim that the template was persisted on the server
- **AND** MUST explain that template storage is browser-local and non-portable

### Requirement: 捕获前必须显示文档来源与内容摘要

The Template area SHALL show, before saving, whether the current document came from an import (with its stored provenance) or was edited in this browser, together with the revision, character count, variable summary and the version that would be assigned.

#### Scenario: Imported document

- **WHEN** the document carries import provenance
- **THEN** the preview MUST show `Imported` with the stored provenance level (deterministic/heuristic/fallback) and any provenance note
- **AND** MUST NOT claim a verified origin or file name beyond the stored provenance

#### Scenario: Document edited in this browser

- **WHEN** the document has no import provenance
- **THEN** the preview MUST describe the source as edited or created in this browser
- **AND** MUST NOT invent an origin

#### Scenario: Missing server draft

- **WHEN** the editor has content but there is no server draft
- **THEN** the capture MUST remain available for the local content
- **AND** the preview MUST say that no server revision is bound

#### Scenario: Duplicate name

- **WHEN** a template with the same name already exists
- **THEN** the preview MUST warn that saving adds a new version instead of overwriting
- **AND** the existing template MUST remain unchanged if the operator cancels

### Requirement: template 列表必须可检查与管理

The Template area SHALL present captured templates as a selectable list and SHALL let the operator inspect, rename and delete them without losing the stored content.

#### Scenario: Inspecting a template

- **WHEN** the operator selects a template
- **THEN** the detail MUST show name, version, source, captured time, bound revision, character count, variable labels and a readable content excerpt
- **AND** the selection MUST be reachable by keyboard

#### Scenario: Renaming a template

- **WHEN** the operator renames a template to a non-empty name
- **THEN** the list and detail MUST show the new name
- **AND** the template id, version and captured content MUST remain unchanged
- **AND** the new name MUST be written to browser storage

#### Scenario: Blank rename

- **WHEN** the operator submits a blank or whitespace-only rename
- **THEN** the rename MUST be rejected with a readable message
- **AND** the previous name MUST remain

#### Scenario: Deleting a template

- **WHEN** the operator chooses to delete a template
- **THEN** the workbench MUST require an explicit confirmation before removal
- **AND** after confirmation the template MUST be removed from the list and browser storage
- **AND** cancelling MUST keep the template

#### Scenario: No templates yet

- **WHEN** no template has been captured
- **THEN** the area MUST explain that no templates exist and that a capture adds one
- **AND** MUST NOT render placeholder or fabricated templates

### Requirement: template 必须支持浏览器本地持久化

Template storage SHALL be browser-local and SHALL remain honest about its scope, capacity and failures.

#### Scenario: Storage boundary

- **WHEN** the operator views the Template area
- **THEN** the UI MUST state that templates are saved in this browser, not on the server
- **AND** MUST NOT call a server endpoint to load or save templates

#### Scenario: Capacity

- **WHEN** more than 20 templates have been captured
- **THEN** storage MUST keep at most 20 templates, evicting the oldest
- **AND** the UI MUST state the capacity

#### Scenario: Unreadable or unavailable storage

- **WHEN** stored data is corrupt or browser storage is unavailable
- **THEN** the workbench MUST ignore invalid entries and show a readable message
- **AND** MUST NOT fabricate templates or claim that stored templates were loaded

#### Scenario: Browser storage write failure

- **WHEN** saving to browser storage fails (for example quota or private mode)
- **THEN** the workbench MUST report that the template was not saved to browser storage
- **AND** any template kept in this session MUST be visibly marked as session-only
- **AND** MUST NOT claim persistence

### Requirement: template 必须可以应用到当前编辑器

The Template area SHALL let the operator apply a captured template to the current editor by replacing the whole working document, and the applied content MUST remain editable as a normal document.

#### Scenario: Applying over existing content

- **WHEN** the current document has content and the operator chooses `Apply to editor`
- **THEN** the workbench MUST require an explicit confirmation before replacing the document
- **AND** after confirmation the editor MUST show the template content as the current document
- **AND** the stored template (name, version, content, captured time) MUST remain unchanged
- **AND** the operator MUST be able to continue editing normally

#### Scenario: Applying to an empty document

- **WHEN** the current document has no content
- **THEN** applying MUST proceed without a replacement confirmation
- **AND** the editor MUST show the template content

#### Scenario: Cancelling an apply

- **WHEN** the replacement confirmation is shown and the operator cancels
- **THEN** the current document MUST remain unchanged
- **AND** the template MUST remain selected

#### Scenario: Variable values are preserved

- **WHEN** the applied template contains variable references with captured display values
- **THEN** the applied document MUST keep those values
- **AND** Variables & Fill MUST list the applied occurrences
- **AND** required variables from the applied template MUST be reported as missing if the operator deletes them later

#### Scenario: Provenance follows the content

- **WHEN** the applied template was captured from an imported document
- **THEN** the applied document MUST keep that provenance and note
- **AND** a later capture preview MUST describe the source as imported
- **AND** MUST NOT invent a new origin

#### Scenario: Template is not mutated

- **WHEN** a template is applied
- **THEN** its stored snapshot, version and name MUST NOT change
- **AND** applying the same template again MUST produce the same document content

#### Scenario: Fallback editor

- **WHEN** the rich editor is unavailable (textarea fallback)
- **THEN** applying a template MUST be unavailable
- **AND** the workbench MUST explain that applying a rich template needs the rich editor

#### Scenario: Autosave and capture metadata

- **WHEN** a template is applied
- **THEN** the document MUST go through the existing draft autosave path
- **AND** the template's captured revision MUST be presented as capture metadata, not as a binding to the current draft

#### Scenario: Pending save conflict

- **WHEN** a save conflict is unresolved and a template is applied
- **THEN** the workbench MUST NOT claim the conflict is resolved
- **AND** the applied content MUST be treated as local until the operator resolves the conflict
- **AND** the existing conflict choices MUST remain the only resolution

### Requirement: 选中文本必须可以标记为 variable

The Variables & Fill area SHALL let the operator mark a non-empty text selection as a variable and SHALL keep the variable definition and its occurrences inspectable.

#### Scenario: Marking a selection

- **WHEN** the operator opens the variable action for a non-empty selection
- **THEN** the workbench MUST offer a variable definition with label, value type and required flag
- **AND** confirming MUST replace the selected text with a variable reference node
- **AND** the variable MUST appear in the variable list

#### Scenario: Empty or unavailable selection

- **WHEN** the selection is empty or the editor is in a fallback that cannot host variables
- **THEN** the mark-as-variable action MUST be unavailable
- **AND** the workbench MUST explain why

### Requirement: 变量必须展示所有 occurrence

The variable list SHALL show each variable's current value, type, required flag and every occurrence, and a fill action SHALL preview the before/after value for all occurrences.

#### Scenario: Inspecting occurrences

- **WHEN** the operator selects a variable
- **THEN** the workbench MUST list every occurrence with its location
- **AND** MUST NOT rely on plain-text search to identify occurrences

#### Scenario: Filling a value

- **WHEN** the operator enters a new value
- **THEN** the workbench MUST show a before/after preview for every occurrence
- **AND** confirming MUST update the mock value on all occurrences together
- **AND** MUST NOT alter same-named ordinary text

### Requirement: 可用变量必须可以更新已有 template

The Variables & Fill area SHALL let the operator save the current document into an existing template, producing a new version snapshot of the same template.

#### Scenario: Saving to an existing template

- **WHEN** the operator chooses `Save to template` and selects an existing template
- **THEN** the workbench MUST require an explicit confirmation that the existing snapshot will be replaced
- **AND** after confirmation the template MUST keep its id and name
- **AND** its version MUST increase
- **AND** the captured content, source, bound revision, character count and variable summary MUST be replaced by the current document
- **AND** the list and detail MUST show the new version and captured time

#### Scenario: Cancelling the update

- **WHEN** the operator cancels the replacement confirmation
- **THEN** the template MUST remain unchanged
- **AND** the template MUST remain selected

#### Scenario: No templates yet

- **WHEN** no template exists
- **THEN** `Save to template` MUST be unavailable with guidance to capture a template first
- **AND** MUST NOT fabricate a template target

#### Scenario: Update write failure

- **WHEN** browser storage rejects the template update
- **THEN** the UI MUST report that the new snapshot was not saved to browser storage
- **AND** any session-only copy MUST be visibly marked
- **AND** MUST NOT claim persistence
- **AND** a reload MAY restore the previous snapshot

#### Scenario: Using the updated template later

- **WHEN** the updated template is applied later
- **THEN** apply MUST use the new snapshot
- **AND** the previous snapshot MUST NOT be recoverable in this build

### Requirement: 下游模板必须生成字段候选与 payload 预览

The Downstream Mapping area SHALL let the operator choose a mock downstream API template, show target fields and semantic candidates with evidence, and generate a JSON payload preview from confirmed values.

#### Scenario: Matching a schema keyword

- **WHEN** the document indicates a guarantee and the target template has an `application_type` enum containing `guarantee`
- **THEN** the workbench MUST show `guarantee` as a candidate with the supporting excerpt
- **AND** the candidate MUST require explicit confirmation before it enters the payload

#### Scenario: Ambiguous or missing mapping

- **WHEN** a target field has no candidate, multiple conflicting candidates, or the document does not support the enum
- **THEN** the field MUST remain unresolved or ambiguous
- **AND** the payload MUST NOT be marked ready

#### Scenario: Payload preview

- **WHEN** required target fields are confirmed
- **THEN** the workbench MUST show a JSON payload preview
- **AND** MUST NOT send the payload to an external system
- **AND** MUST bind the preview to the mock template version and document snapshot

### Requirement: Downstream Mapping 必须提供下游系统选择与管理

The Downstream Mapping area SHALL expose a downstream-system selector and a collapsible `Manage systems` surface without adding a fourth workbench area.

#### Scenario: Selecting a system

- **WHEN** the operator opens Downstream Mapping with systems available
- **THEN** the selector MUST list their name, environment and enabled state
- **AND** selecting one MUST load its bound OpenAPI spec
- **AND** a disabled system MUST be visibly disabled for mock send

#### Scenario: Managing systems

- **WHEN** the operator opens `Manage systems`
- **THEN** the operator MUST be able to create, edit and delete systems with name, base URL, environment, enabled, auth type/hint and a bound spec
- **AND** the auth area MUST show only a non-secret hint
- **AND** saving an invalid URL or spec MUST show a readable error
- **AND** deleting MUST require confirmation and update the selector/status

#### Scenario: No system available

- **WHEN** no downstream system exists or none is selected
- **THEN** OpenAPI mapping and `Send (mock)` MUST be unavailable
- **AND** the area MUST explain that a system must be created/selected first

#### Scenario: Switching or deleting the selected system

- **WHEN** the operator switches to another system
- **THEN** the previous operation and field mappings MUST be cleared
- **AND** document variables MUST remain available for remapping
- **WHEN** the selected system is deleted
- **THEN** its operation, mappings and mock receipt MUST be cleared

### Requirement: 工作台必须保持 fixture-only 边界

The workbench SHALL label synthetic variable/mapping behavior as fixture-backed, template and downstream-system storage as browser-local, and mock send as simulated; it SHALL NOT claim server-side persistence, real HTTP delivery, real parsing, model verification or external delivery.

#### Scenario: Viewing any workbench area

- **WHEN** the operator views Template, Variables or Downstream Mapping
- **THEN** a fixture-backed/browser-local/simulated boundary MUST be visible for the active area
- **AND** the Template area MUST state that templates are stored in this browser only
- **AND** Downstream Mapping MUST state that systems are browser-local and mock send makes no network request
- **AND** unimplemented backend capabilities MUST be listed

#### Scenario: Attempting an unavailable action

- **WHEN** an action depends on an unimplemented backend capability
- **THEN** the workbench MUST present it as unavailable or simulated
- **AND** a mock receipt MUST be labelled simulated
- **AND** MUST NOT render a fabricated real server receipt

### Requirement: 工作台必须可访问

The workbench SHALL expose its areas, variable actions, selections and status changes with readable text and keyboard-operable controls.

#### Scenario: Keyboard variable action

- **WHEN** the operator cannot use a right-click context menu
- **THEN** the mark-as-variable action MUST be reachable by keyboard
- **AND** the resulting dialog MUST be operable without a mouse

#### Scenario: Status announcement

- **WHEN** template capture/rename/delete/update, variable fill, payload preview, system CRUD or mock send state changes
- **THEN** the change MUST be available as readable status text
- **AND** MUST NOT rely on colour alone

#### Scenario: Keyboard template management

- **WHEN** the operator manages templates without a mouse
- **THEN** selecting a template, renaming it and confirming a delete MUST be keyboard operable
- **AND** the rename input and delete confirmation MUST have readable labels
- **AND** the delete confirmation MUST be announced as a status change

#### Scenario: Keyboard system management

- **WHEN** the operator manages downstream systems without a mouse
- **THEN** selecting a system, opening `Manage systems`, editing fields and confirming a delete MUST be keyboard operable
- **AND** form inputs and the mock send action MUST have readable labels