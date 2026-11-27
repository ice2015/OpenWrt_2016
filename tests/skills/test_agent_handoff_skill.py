import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / ".agents" / "skills" / "agent-handoff"
SKILL_FILE = SKILL_DIR / "SKILL.md"
TEMPLATE_FILE = SKILL_DIR / "references" / "handoff-template.md"
EVALS_FILE = SKILL_DIR / "evals" / "evals.json"


class AgentHandoffSkillTests(unittest.TestCase):
    def read_skill(self):
        self.assertTrue(SKILL_FILE.is_file())
        text = SKILL_FILE.read_text(encoding="utf-8")
        match = re.match(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", text, re.DOTALL)
        self.assertIsNotNone(match, "SKILL.md must have YAML frontmatter")
        metadata = {}
        for line in match.group(1).splitlines():
            key, separator, value = line.partition(": ")
            self.assertEqual(": ", separator)
            self.assertNotIn(":", value)
            self.assertNotIn(key, metadata)
            metadata[key] = value
        self.assertEqual({"name", "description"}, set(metadata))
        return text, metadata, match.group(2)

    def test_frontmatter_and_repository_discovery(self):
        text, metadata, _ = self.read_skill()
        self.assertEqual("agent-handoff", metadata["name"])
        self.assertTrue(metadata["description"].startswith("Use when"))
        self.assertLessEqual(len(text.splitlines()), 300)
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(".agents/skills/agent-handoff/SKILL.md", agents)

    def test_skill_enforces_truthful_state_and_authorization(self):
        text, _, body = self.read_skill()
        required = (
            "已设计但未实施",
            "未授权/禁止",
            "验证失败",
            "UNRESOLVED",
            "git status --short",
            "不触发 GitHub Actions",
            "不要声称后续任务已经完成",
            "隐藏推理",
            "秘密",
        )
        for item in required:
            with self.subTest(item=item):
                self.assertIn(item, body)
        self.assertIn("references/handoff-template.md", text)

    def test_template_contains_execution_ready_sections(self):
        template = TEMPLATE_FILE.read_text(encoding="utf-8")
        for heading in (
            "## 目标",
            "## 先读文件",
            "## 确认决策",
            "## 当前状态",
            "## 验证证据",
            "## 下一步",
            "## 权限边界",
            "## 工作区与文件归属",
            "## 下一 Agent 启动提示",
            "## 变更摘要",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, template)

    def test_evals_follow_skill_creator_schema(self):
        payload = json.loads(EVALS_FILE.read_text(encoding="utf-8"))
        self.assertEqual("agent-handoff", payload["skill_name"])
        self.assertEqual(3, len(payload["evals"]))
        self.assertEqual([1, 2, 3], [case["id"] for case in payload["evals"]])
        for case in payload["evals"]:
            with self.subTest(case=case["id"]):
                self.assertTrue(case["prompt"])
                self.assertTrue(case["expected_output"])
                self.assertGreaterEqual(len(case["expectations"]), 3)
                self.assertIsInstance(case["files"], list)


if __name__ == "__main__":
    unittest.main()
