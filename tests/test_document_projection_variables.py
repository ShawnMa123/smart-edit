"""Variable references in the canonical projection (change: automation-workbench-ui, task 1.3).

The same golden fixture is read by `web/src/rich/projection.test.ts`, so the client and the server can
never disagree about a variable's contribution to the audit text.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.documents.projection import project_document

FIXTURE = Path(__file__).parents[1] / "fixtures" / "automation" / "variable_projection.json"


@pytest.fixture(scope="module")
def golden() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_variable_projection_matches_the_shared_golden_fixture(golden):
    projection = project_document(golden["document"])

    assert projection.text == golden["expected_text"]
    assert [
        {"nodeId": block.node_id, "start": block.start_cp, "end": block.end_cp}
        for block in projection.blocks
    ] == golden["expected_blocks"]


def test_empty_variable_projects_as_a_placeholder_never_a_value():
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Beneficiary: "},
                    {
                        "type": "variableReference",
                        "attrs": {
                            "variableId": "var_beneficiary",
                            "label": "beneficiary",
                            "valueType": "string",
                            "required": True,
                            "displayValue": "",
                            "occurrenceId": "occ_1",
                        },
                    },
                ],
            }
        ],
    }

    assert project_document(document).text == "Beneficiary: {{beneficiary}}"


def test_page_break_emoji_and_cjk_are_unchanged(golden):
    projection = project_document(golden["document"])

    assert "😀" in projection.text
    assert "保函" in projection.text
    # Unicode code points, not UTF-16 units: the emoji is one character.
    second = projection.blocks[1]
    assert second.end_cp - second.start_cp == len(
        "Beneficiary: {{beneficiary}} 😀 保函"
    )