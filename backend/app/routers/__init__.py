"""路由包。

⚠️ 本文件【必须保持不 import 任何子模块】。
app/main.py 的 register_routers() 用 pkgutil.iter_modules 扫描本包并逐个
importlib 导入，单个模块失败只记 warning 不崩。若在此处 import 具体 router，
则遍历前就会触发导入，容错机制失效（某个 router 未就绪会导致整个 app 起不来）。
"""
