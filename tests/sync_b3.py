#!/usr/bin/env python3
"""Copia os módulos compartilhados para todas as skills que os usam.

Fonte única: trader-budget/b3.py e b3_ativos.json, trader-copycat/cvm.py.
Rode depois de editar qualquer um deles; tests/test_repo.py falha se as
cópias divergirem.
"""

import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B3_USERS = ["trader-alerts", "trader-analyst", "trader-broker", "trader-copycat", "trader-insiders",
            "trader-news", "trader-rebalance", "trader-risk", "trader-tax"]
CVM_USERS = ["trader-analyst", "trader-insiders", "trader-news"]
SHARED = [("trader-budget", "b3.py", B3_USERS), ("trader-budget", "b3_ativos.json", B3_USERS),
          ("trader-copycat", "cvm.py", CVM_USERS)]


def main():
    for src_dir, name, users in SHARED:
        src = os.path.join(ROOT, src_dir, name)
        for u in users:
            shutil.copyfile(src, os.path.join(ROOT, u, name))
            print("%s/%s <- %s/%s" % (u, name, src_dir, name))


if __name__ == "__main__":
    main()
