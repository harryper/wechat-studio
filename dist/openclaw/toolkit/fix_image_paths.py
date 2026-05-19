#!/usr/bin/env python3
"""
fix_image_paths.py — 将 markdown 中的 image-1---{uuid}.png 占位符
有序替换为静态文件名（cover, img1, img2 ...）。

用法：
    python3 fix_image_paths.py article.md cover.png img1.png img2.png ...

示例：
    python3 fix_image_paths.py output/demo/2026-03-30-dali-travel.md \
        2026-03-30-dali-travel-cover.png \
        2026-03-30-dali-travel-img1.png \
        2026-03-30-dali-travel-img2.png \
        2026-03-30-dali-travel-img3.png \
        2026-03-30-dali-travel-img4.png
"""

import re
import sys

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    md_path = sys.argv[1]
    new_names = sys.argv[2:]

    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 找所有 image-1---{uuid}.png 的出现顺序
    pattern = r'(image-1---[a-f0-9-]+\.png)'
    matches = re.findall(pattern, content)

    if len(matches) != len(new_names):
        print(f"⚠️  警告：markdown 中有 {len(matches)} 张图，但提供了 {len(new_names)} 个文件名，跳过替换")
        return

    for old, new in zip(matches, new_names):
        content = content.replace(old, new, 1)  # 只替换第一次出现，保证有序

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"✅ 替换完成：{len(new_names)} 张图")
    for old, new in zip(matches, new_names):
        print(f"   {old} → {new}")


if __name__ == '__main__':
    main()
