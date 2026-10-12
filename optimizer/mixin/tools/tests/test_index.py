"""The lab manual's "Tool and skill index" lists every tool and skill, with the skills that name each tool."""

import re
import unittest
from pathlib import Path

LAB = Path(__file__).resolve().parents[2]


def index_tables():
    """The index section's rows: {tool: skills cell} and {skill: tools cell}."""
    manual = (LAB / "AGENTS.md").read_text()
    section = manual.split("## Tool and skill index", 1)[1].split("\n## ", 1)[0]
    tools, skills = {}, {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 3:
            continue
        tool = re.fullmatch(r"`([\w.]+\.(?:py|sh))`", cells[0])
        skill = re.fullmatch(r"\[`([\w-]+)`\]\(skills/[\w-]+/SKILL\.md\)", cells[0])
        if tool:
            tools[tool.group(1)] = cells[2]
        elif skill:
            skills[skill.group(1)] = cells[2]
    return tools, skills


class IndexTest(unittest.TestCase):
    def setUp(self):
        self.tools, self.skills = index_tables()
        self.skill_text = {path.parent.name: path.read_text() for path in (LAB / "skills").glob("*/SKILL.md")}
        self.tool_names = {path.name for path in (LAB / "tools").iterdir() if path.suffix in (".py", ".sh")}

    def test_every_tool_and_skill_is_listed(self):
        self.assertEqual(set(self.tools), self.tool_names)
        self.assertEqual(set(self.skills), set(self.skill_text))

    def test_skills_cells_match_the_skill_files(self):
        for tool, cell in self.tools.items():
            using = sorted(skill for skill, text in self.skill_text.items() if tool in text)
            expected = ", ".join(f"`{skill}`" for skill in using) or "none (this manual only)"
            self.assertEqual(cell, expected, tool)

    def test_tools_cells_match_the_skill_files(self):
        for skill, cell in self.skills.items():
            named = sorted(tool for tool in self.tool_names if tool in self.skill_text[skill])
            self.assertEqual(cell, ", ".join(f"`{tool}`" for tool in named), skill)

    def test_manifest_names_every_tool(self):
        manifest = (LAB / "MIXIN.md").read_text()
        self.assertEqual([tool for tool in sorted(self.tool_names) if tool not in manifest], [])


if __name__ == "__main__":
    unittest.main()
