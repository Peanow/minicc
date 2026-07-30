# Workspace

CoreCoder 功能验证目录。在此目录下启动 CoreCoder，所有文件操作都在此范围内进行，不会影响项目源码。

## 启动方式

```bash
./dev.sh
```

或手动：

```bash
source ../.venv/bin/activate
corecoder
```

## 验证清单

- `read_file` — 读取 sample.py
- `edit_file` — 修复 sample.py 中的 bug
- `bash` — 运行 python sample.py
- `glob` / `grep` — 搜索文件和内容
- `write_file` — 创建新文件
