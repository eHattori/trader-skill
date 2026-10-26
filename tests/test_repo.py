import json
import os
import re
import unittest

from _load import ROOT

SKILLS = ["trader-copycat", "trader-news", "trader-budget", "trader-pelosi", "trader-analyst",
          "trader-screener", "trader-risk", "trader-broker", "trader-tax", "trader-alerts",
          "trader-rebalance", "trader-insiders"]
ABOUT = ("12 skills do Claude para a B3 e para os EUA: copiam a carteira de fundos e gestores, acompanham "
         "fatos relevantes, insiders e o Congresso americano, dimensionam cada boleta ao seu orçamento, "
         "apuram o IR e nunca enviam uma ordem sem o seu sim.")
# skills that can lead to an order carry the safety block
ORDER_PATH = ["trader-copycat", "trader-budget", "trader-pelosi", "trader-risk", "trader-broker",
              "trader-tax", "trader-alerts", "trader-rebalance", "trader-insiders"]
# shared modules: one source, identical copies (tests/sync_b3.py writes them)
SHARED = {("trader-budget", "b3.py"): ["trader-alerts", "trader-analyst", "trader-broker", "trader-copycat",
                                       "trader-insiders", "trader-news", "trader-rebalance", "trader-risk",
                                       "trader-tax"],
          ("trader-budget", "b3_ativos.json"): ["trader-alerts", "trader-analyst", "trader-broker",
                                                "trader-copycat", "trader-insiders", "trader-news",
                                                "trader-rebalance", "trader-risk", "trader-tax"],
          ("trader-copycat", "cvm.py"): ["trader-analyst", "trader-insiders", "trader-news"]}


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (m.group(1) if m else ""), text


def every_text_file():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for f in files:
            if f.endswith((".md", ".py", ".json", ".csv", ".txt", ".xml")) or f == "LICENSE":
                yield os.path.join(base, f)


class Repo(unittest.TestCase):
    def test_twelve_skill_folders_at_the_root(self):
        found = sorted(d for d in os.listdir(ROOT)
                       if os.path.isfile(os.path.join(ROOT, d, "SKILL.md")))
        self.assertEqual(found, sorted(SKILLS))

    def test_root_matches_the_reel(self):
        root = sorted(d for d in os.listdir(ROOT) if not d.startswith(".git"))
        self.assertEqual(root, sorted([".claude-plugin", "LICENSE", "README.md", "tests"] + SKILLS))

    def test_frontmatter_name_and_description(self):
        for s in SKILLS:
            fm, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            self.assertIn("name: %s\n" % s, fm + "\n", s)
            self.assertRegex(fm, r"description: ", s)
            self.assertGreater(len(fm), 200, "%s description is too thin" % s)
            self.assertGreater(len(text.splitlines()), 60, s)

    def test_order_path_skills_carry_the_safety_rule(self):
        for s in ORDER_PATH:
            _, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            low = " ".join(text.lower().split())
            self.assertIn("não recomendação de investimento", low, s)
            self.assertIn("not financial advice", low, s)
            self.assertIn("\"sim\"", low, s)

    def test_plugin_manifest_points_at_the_root_skills(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json")) as fh:
            plugin = json.load(fh)
        self.assertEqual(plugin["name"], "trader-skill")
        self.assertEqual(plugin["skills"], "./")
        self.assertEqual(plugin["description"], ABOUT)
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")) as fh:
            market = json.load(fh)
        self.assertEqual(market["name"], "trader-skill")
        self.assertEqual(market["plugins"][0]["name"], "trader-skill")

    def test_readme_carries_the_reel_copy(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = " ".join(fh.read().split())
        self.assertTrue(readme.startswith("# The Trader skill"))
        for line in (ABOUT,
                     "https://github.com/eHattori/trader-skill install skill",
                     "/plugin marketplace add eHattori/trader-skill",
                     "/plugin install trader-skill@trader-skill",
                     "Fork de [Jakeschincariol/trader-skill]",
                     "## Letras miúdas"):
            self.assertIn(line, readme)
        for s in SKILLS:
            self.assertIn("/" + s, readme, s)

    def test_no_em_dashes_and_no_personal_email(self):
        for path in every_text_file():
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            rel = os.path.relpath(path, ROOT)
            self.assertNotIn("\u2014", text, rel)
            self.assertNotIn("jakeschincariol" + "@" + "gmail.com", text, rel)  # built, so this file passes too

    def test_shared_modules_are_identical(self):
        for (src_dir, name), users in SHARED.items():
            with open(os.path.join(ROOT, src_dir, name), "rb") as fh:
                src = fh.read()
            for u in users:
                with open(os.path.join(ROOT, u, name), "rb") as fh:
                    self.assertEqual(fh.read(), src, "%s/%s differs from %s: run tests/sync_b3.py" % (u, name, src_dir))

    def test_br_config_example(self):
        with open(os.path.join(ROOT, "trader-budget", "config_br.example.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        self.assertEqual(cfg["market"], "br")
        self.assertIs(cfg["allow_options"], False)
        self.assertIs(cfg["allow_short"], False)

    def test_paper_trading_is_the_default(self):
        with open(os.path.join(ROOT, "trader-budget", "config.example.json")) as fh:
            cfg = json.load(fh)
        self.assertIs(cfg["paper"], True)
        self.assertIs(cfg.get("allow_options", False), False)


if __name__ == "__main__":
    unittest.main()
