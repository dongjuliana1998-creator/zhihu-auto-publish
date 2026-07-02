#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

"""
ZhihuAuth - 知乎登录 & Cookie 管理
首次运行会打开浏览器让你扫码登录，之后自动保存 Cookie
"""

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


class ZhihuAuth:
    def __init__(self, cookie_file: str = "zhihu_cookies.json", headless: bool = False):
        self.cookie_file = Path(cookie_file)
        self.headless = headless
        self.base_url = "https://www.zhihu.com"

    def login(self) -> bool:
        """打开浏览器，引导用户扫码登录，保存 Cookie"""
        print("🔓 首次登录：请用知乎 App 扫码登录...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.goto(f"{self.base_url}/signin", wait_until="networkidle")
            time.sleep(2)

            print("📱 请使用知乎 App 扫描二维码登录...")
            print("   登录成功后，脚本会自动检测并保存 Cookie。")
            print("   等待中...")

            # 等待登录成功：检测 URL 变化（最可靠）
            try:
                page.wait_for_url(lambda url: "signin" not in url, timeout=120000)
                print("✅ 登录成功（URL 检测）！")
            except PWTimeout:
                print("❌ 登录超时，请重试")
                browser.close()
                return False

            # 额外等待，确保 Cookie 完全写入
            time.sleep(5)

            # 保存 Cookie
            cookies = context.cookies()
            
            # 验证 Cookie 中是否有登录 Token
            has_z_c0 = any(c['name'] == 'z_c0' for c in cookies)
            if not has_z_c0:
                print("⚠️ 警告：Cookie 中未找到 z_c0（登录 Token）")
                print("   可能登录未完全成功，但会继续保存...")
            
            self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cookie_file, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            print(f"💾 Cookie 已保存到 {self.cookie_file}")
            if has_z_c0:
                print("✅ 登录 Token (z_c0) 已保存")

            browser.close()
            return True

    def load_cookies(self, context) -> bool:
        """从文件加载 Cookie"""
        if not self.cookie_file.exists():
            return False
        try:
            with open(self.cookie_file, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            context.add_cookies(cookies)
            return True
        except Exception as e:
            print(f"⚠️ 加载 Cookie 失败: {e}")
            return False

    def test_login(self) -> bool:
        """测试 Cookie 是否有效"""
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context()
            if not self.load_cookies(context):
                print("❌ 没有保存的 Cookie，请先登录")
                browser.close()
                return False
            page = context.new_page()
            page.goto(f"{self.base_url}/notifications", wait_until="networkidle")
            time.sleep(2)
            
            # 检查是否已登录：只检查 URL（最可靠）
            if "signin" in page.url:
                print("❌ Cookie 已失效，请重新登录")
                browser.close()
                return False
            
            print("✅ Cookie 有效，登录状态正常")
            browser.close()
            return True


if __name__ == "__main__":
    auth = ZhihuAuth(headless=False)
    if not auth.test_login():
        auth.login()
    else:
        print("🎉 已登录，无需重新扫码")
