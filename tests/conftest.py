"""pytest 全局夹具与测试环境约定。

测试库切换在最顶部完成（先于任何 app.core.config 导入）：
DB_NAME 环境变量优先级高于 .env，因此 integration/e2e 全部落在 investment_ai_test。
"""

from __future__ import annotations

import os

os.environ["DB_NAME"] = "investment_ai_test"
