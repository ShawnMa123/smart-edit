# Spec Delta

## Purpose

定义 Automation 工作台里“从下游系统 OpenAPI 生成请求 JSON”的前端能力：维护下游系统（名称、地址、环境、auth 类型提示、绑定的 OpenAPI 3.x JSON，浏览器本地持久化），选择系统后解析其 contract，把正文变量映射到 schema 字段，预览/下载 JSON，并可执行**不触网的 mock send**（200/500）查看模拟 receipt。不联网、不调用真实下游 API；不存真实凭据。

## ADDED Requirements

### Requirement: 下游系统必须可配置并持久化

The workbench SHALL let the operator create, edit and delete downstream systems with a name, base URL, environment, enabled flag, auth type/hint and a bound OpenAPI spec, and SHALL persist them in browser-local storage.

#### Scenario: Seeded presets

- **WHEN** the workbench has no stored downstream systems
- **THEN** it MUST seed the mock presets from `fixtures/automation/downstream_systems.json`
- **AND** must state that systems are saved in this browser, not on the server
- **AND** deleting every system MUST NOT re-seed on the next load

#### Scenario: Creating and editing a system

- **WHEN** the operator saves a system with a non-empty name and an `http(s)` base URL
- **THEN** the system MUST appear in the selector with its environment and enabled state
- **AND** edits MUST survive a reload
- **AND** a blank name or invalid URL MUST be rejected with a readable message

#### Scenario: Deleting a system

- **WHEN** the operator deletes a system
- **THEN** the workbench MUST require explicit confirmation
- **AND** after confirmation the system MUST be removed from storage and the selector
- **AND** if it was selected, the operation/mapping MUST be cleared

#### Scenario: Capacity and corrupt storage

- **WHEN** more than 10 systems or a spec larger than 512 KB is written
- **THEN** the write MUST be rejected with a readable message
- **AND** corrupt or invalid stored systems MUST be ignored rather than fabricated
- **AND** a storage write failure MUST be reported and MUST NOT claim persistence

#### Scenario: Credentials

- **WHEN** the operator sets an auth type
- **THEN** the workbench MAY store the type and a non-secret hint
- **AND** MUST NOT store, display or send a real token or secret in this build

### Requirement: 下游系统必须绑定 OpenAPI contract

The workbench SHALL load the OpenAPI spec bound to the selected system and SHALL require a selected system before mapping or mock sending.

#### Scenario: Selecting a system

- **WHEN** the operator selects a system
- **THEN** the workbench MUST parse that system's saved OpenAPI spec
- **AND** MUST reset the previous operation and field mappings
- **AND** MUST keep the document variables available for remapping

#### Scenario: Editing the bound spec

- **WHEN** the operator uploads or pastes OpenAPI JSON in `Manage systems`
- **THEN** saving the system MUST persist the spec with that system
- **AND** an invalid spec MUST be rejected with a readable error
- **AND** the mapping area MUST NOT use an unsaved, unbound spec

#### Scenario: No system selected

- **WHEN** no downstream system exists or none is selected
- **THEN** OpenAPI mapping and mock send MUST be unavailable
- **AND** the workbench MUST explain that a system must be created/selected first

### Requirement: OpenAPI JSON 必须可以导入并解析

The workbench SHALL accept an OpenAPI 3.x JSON document via file upload or paste and SHALL parse it locally without a network request.

#### Scenario: Importing a spec

- **WHEN** the operator uploads a `.json` file or pastes OpenAPI JSON
- **THEN** the workbench MUST parse it in the browser
- **AND** MUST show the document title/version when present
- **AND** MUST NOT upload the spec to a server

#### Scenario: Rejecting unsupported input

- **WHEN** the input is YAML, Swagger 2.0, malformed JSON, or not an OpenAPI 3.x document
- **THEN** the workbench MUST show a readable error naming the unsupported format
- **AND** MUST NOT fabricate operations or fields

#### Scenario: Spec lifetime

- **WHEN** the page is reloaded
- **THEN** the uploaded spec MAY be gone
- **AND** the UI MUST NOT claim that the spec was saved

### Requirement: 必须可以选择 operation 与 JSON request schema

The workbench SHALL list operations from the parsed document and SHALL let the operator choose one that carries an `application/json` request body before mapping fields.

#### Scenario: Listing operations

- **WHEN** a valid OpenAPI document is parsed
- **THEN** the workbench MUST list operations with their method, path and `operationId` when present
- **AND** an operation without a JSON request body MUST be shown as unavailable
- **AND** selecting one MUST show its request schema

#### Scenario: Local schema references

- **WHEN** the request schema uses `$ref` to `components/schemas`
- **THEN** the workbench MUST resolve local references
- **AND** MUST detect and report reference cycles instead of hanging
- **AND** external references MUST be reported as unsupported

#### Scenario: Unsupported schema constructs

- **WHEN** the schema uses `oneOf`, `anyOf`, external `$ref` or unsupported types
- **THEN** the affected fields MUST be reported as unsupported
- **AND** the workbench MUST NOT silently invent a shape

### Requirement: 可用变量必须可以映射到 schema 字段

The workbench SHALL map available document variables to schema fields and SHALL show required, type and enum constraints before generating JSON.

#### Scenario: Suggested mapping

- **WHEN** an operation schema exposes object properties
- **THEN** the workbench MUST suggest a mapping when a variable label matches a property name after normalisation
- **AND** the operator MUST be able to override the mapping manually
- **AND** nested object properties MUST be addressable by dotted paths

#### Scenario: Missing required field

- **WHEN** a required property has no mapped variable or value
- **THEN** the JSON preview MUST be marked not ready
- **AND** the missing field MUST be named

#### Scenario: Type or enum mismatch

- **WHEN** a mapped variable value cannot be converted to the schema type (number/integer/boolean) or is outside an enum
- **THEN** the field MUST be marked invalid
- **AND** the JSON preview MUST NOT be marked ready
- **AND** the workbench MUST NOT silently coerce or invent a value

### Requirement: JSON 必须可以预览并下载

The workbench SHALL render the request JSON from confirmed mappings and SHALL let the operator download it as a `.json` file without sending it.

#### Scenario: Previewing the payload

- **WHEN** the required fields are satisfied
- **THEN** the workbench MUST show the JSON structure that would be sent
- **AND** MUST bind the preview to the selected operation
- **AND** MUST display `Not sent`

#### Scenario: Downloading the file

- **WHEN** the operator chooses download
- **THEN** the browser MUST save a `.json` file derived from the preview
- **AND** the file name MUST identify the operation or schema
- **AND** MUST NOT call the downstream API

#### Scenario: Not ready

- **WHEN** required or invalid fields remain
- **THEN** download MUST be unavailable
- **AND** the workbench MUST explain what is missing

### Requirement: mock send 必须不触网且可模拟成功/失败

The workbench SHALL offer a mock send only for a ready payload bound to an enabled downstream system, SHALL simulate 200/500 without any network request, and SHALL label the receipt as simulated.

#### Scenario: Sending successfully

- **WHEN** the operator selects an enabled system, a valid operation and a ready payload
- **THEN** `Send (mock)` MUST be available
- **AND** clicking it MUST produce a receipt with `200`, a mock request id, the method, the endpoint (`baseUrl + path`), the payload and `Simulated — no network request`
- **AND** MUST NOT call fetch/proxy or read any credential

#### Scenario: Simulating failure

- **WHEN** the operator enables `Simulate failure`
- **THEN** the mock send MUST return `500` with `MOCK_DOWNSTREAM_ERROR`
- **AND** the receipt MUST still be labelled simulated
- **AND** the payload MUST remain downloadable

#### Scenario: Send unavailable

- **WHEN** the payload is not ready, the system is disabled/missing, or no operation is selected
- **THEN** `Send (mock)` MUST be unavailable
- **AND** the workbench MUST explain the missing prerequisite

#### Scenario: No delivery history

- **WHEN** a mock send completes
- **THEN** only the latest receipt needs to be shown
- **AND** no send history/audit record MUST be persisted or claimed

### Requirement: 下游契约能力必须保持诚实边界

The workbench SHALL state the supported OpenAPI subset, SHALL label systems as browser-local and mock sends as simulated, and SHALL NOT claim real delivery, validation or production contract coverage.

#### Scenario: Viewing the OpenAPI mode

- **WHEN** the operator opens the OpenAPI source
- **THEN** the UI MUST state that only OpenAPI 3.x JSON with local `$ref` is supported
- **AND** MUST state that YAML, Swagger 2.0, external `$ref` and `oneOf`/`anyOf` are unsupported
- **AND** MUST state that systems are saved in this browser and parsed locally
- **AND** MUST state that mock send performs no network request

#### Scenario: Attempting real delivery

- **WHEN** the operator looks for a real send/execute action
- **THEN** no real send/execute action MUST be offered
- **AND** only `Send (mock)` MAY be offered
- **AND** the receipt MUST NOT be presented as a real server response