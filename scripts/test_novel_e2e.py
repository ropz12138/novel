#!/usr/bin/env python3
"""
小说创作端到端测试脚本

用法:
    python scripts/test_novel_e2e.py

功能:
    1. 登录系统
    2. 创建新作品（生成大纲）
    3. 与agent对话，创作小说
    4. 获取生成的小说内容
    5. 验证小说质量
"""

import json
import requests
import sys
import time
from typing import Optional

# 配置
API_BASE = "http://127.0.0.1:9002/api"
TEST_USER = {
    "email": "test@example.com",
    "password": "test123456"
}

class NovelTestClient:
    def __init__(self):
        self.session = requests.Session()
        self.token = None
        self.user_id = None
        self.work_id = None
        self.session_id = None
    
    def login(self, email: str, password: str) -> bool:
        """登录系统"""
        print(f"[1/7] 正在登录: {email}")
        resp = self.session.post(f"{API_BASE}/auth/login", json={
            "email": email,
            "password": password
        })
        
        if resp.status_code != 200:
            print(f"  ❌ 登录失败: {resp.text}")
            return False
        
        data = resp.json()
        self.token = data["token"]
        self.user_id = data["user"]["id"]
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        print(f"  ✅ 登录成功: {data['user']['username']}")
        return True
    
    def register(self, username: str, email: str, password: str) -> bool:
        """注册新用户"""
        print(f"  正在注册: {username} ({email})")
        resp = self.session.post(f"{API_BASE}/auth/register", json={
            "username": username,
            "email": email,
            "password": password
        })
        
        if resp.status_code != 200:
            print(f"  ❌ 注册失败: {resp.text}")
            return False
        
        data = resp.json()
        self.token = data["token"]
        self.user_id = data["user"]["id"]
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        print(f"  ✅ 注册成功: {data['user']['username']}")
        return True
    
    def generate_outline(self, idea: str, tags: list[str] = None) -> Optional[dict]:
        """生成大纲"""
        print(f"\n[2/7] 正在生成大纲")
        print(f"  创意: {idea[:50]}...")
        print(f"  标签: {tags or []}")
        
        resp = self.session.post(f"{API_BASE}/works/generate-outline-stream", json={
            "idea": idea,
            "tags": tags or []
        }, stream=True)
        
        if resp.status_code != 200:
            print(f"  ❌ 大纲生成失败: {resp.text}")
            return None
        
        work_id = None
        title = None
        for line in resp.iter_lines():
            if line:
                line = line.decode("utf-8")
                if line.startswith("event: "):
                    event = line[7:].strip()
                elif line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if event == "outline_done":
                            work_id = data.get("work_id")
                            title = data.get("title")
                            print(f"  ✅ 大纲生成成功")
                            print(f"  作品ID: {work_id}")
                            print(f"  作品标题: {title}")
                        elif event == "outline_status":
                            print(f"  状态: {data.get('message')}")
                        elif event == "error":
                            print(f"  ❌ 大纲生成错误: {data.get('message')}")
                            return None
                    except json.JSONDecodeError:
                        pass
        
        if work_id:
            self.work_id = work_id
            return {"work_id": work_id, "title": title}
        return None
    
    def start_supervisor(self, message: str) -> bool:
        """启动supervisor会话"""
        print(f"\n[3/7] 正在启动supervisor会话")
        print(f"  消息: {message[:50]}...")
        
        resp = self.session.post(f"{API_BASE}/supervisor/start", json={
            "message": message,
            "work_id": self.work_id,
            "auto_mode": True
        }, stream=True)
        
        if resp.status_code != 200:
            print(f"  ❌ 启动supervisor失败: {resp.text}")
            return False
        
        for line in resp.iter_lines():
            if line:
                line = line.decode("utf-8")
                if line.startswith("event: "):
                    event = line[7:].strip()
                elif line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if event == "session_created":
                            self.session_id = data.get("session_id")
                            print(f"  会话已创建: {self.session_id}")
                        elif event == "stage_start":
                            print(f"  阶段: {data.get('label')}")
                        elif event == "saved":
                            print(f"  ✅ 章节已保存: 第{data.get('chapter_number')}章")
                        elif event == "supervisor_done":
                            print(f"  ✅ supervisor处理完成")
                            return True
                        elif event == "error":
                            print(f"  ❌ supervisor错误: {data.get('message')}")
                            return False
                    except json.JSONDecodeError:
                        pass
        
        return True
    
    def resume_supervisor(self, message: str) -> bool:
        """恢复supervisor会话"""
        if not self.session_id:
            print("  ❌ 没有活跃的会话")
            return False
        
        print(f"\n[4/7] 正在恢复supervisor会话")
        print(f"  消息: {message[:50]}...")
        
        resp = self.session.post(f"{API_BASE}/supervisor/resume", json={
            "session_id": self.session_id,
            "message": message
        }, stream=True)
        
        if resp.status_code != 200:
            print(f"  ❌ 恢复supervisor失败: {resp.text}")
            return False
        
        for line in resp.iter_lines():
            if line:
                line = line.decode("utf-8")
                if line.startswith("event: "):
                    event = line[7:].strip()
                elif line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if event == "stage_start":
                            print(f"  阶段: {data.get('label')}")
                        elif event == "saved":
                            print(f"  ✅ 章节已保存: 第{data.get('chapter_number')}章")
                        elif event == "supervisor_done":
                            print(f"  ✅ supervisor处理完成")
                            return True
                        elif event == "error":
                            print(f"  ❌ supervisor错误: {data.get('message')}")
                            return False
                    except json.JSONDecodeError:
                        pass
        
        return True
    
    def get_work(self) -> Optional[dict]:
        """获取作品信息"""
        if not self.work_id:
            print("  ❌ 没有指定的作品ID")
            return None
        
        resp = self.session.post(f"{API_BASE}/works/get", json={"work_id": self.work_id})
        if resp.status_code != 200:
            print(f"  ❌ 获取作品失败: {resp.text}")
            return None
        
        return resp.json()
    
    def list_chapters(self) -> Optional[list]:
        """获取章节列表"""
        if not self.work_id:
            print("  ❌ 没有指定的作品ID")
            return None
        
        resp = self.session.post(f"{API_BASE}/works/chapters/list", json={"work_id": self.work_id})
        if resp.status_code != 200:
            print(f"  ❌ 获取章节列表失败: {resp.text}")
            return None
        
        return resp.json()
    
    def get_chapter(self, chapter_number: int) -> Optional[dict]:
        """获取章节内容"""
        chapters = self.list_chapters()
        if not chapters:
            return None
        for ch in chapters:
            if ch.get("chapter_number") == chapter_number:
                return ch
        return None

def main():
    """主测试流程"""
    print("="*60)
    print("小说创作端到端测试")
    print("="*60)
    
    client = NovelTestClient()
    
    # 1. 登录或注册
    if not client.login(TEST_USER["email"], TEST_USER["password"]):
        print("  登录失败，尝试注册...")
        if not client.register("test_user", TEST_USER["email"], TEST_USER["password"]):
            print("❌ 注册失败，退出测试")
            return 1
    
    # 2. 生成大纲
    idea = "一个现代都市青年意外穿越到修仙世界，凭借现代知识在修仙界闯出一片天地的故事"
    tags = ["穿越", "修仙", "都市"]
    
    result = client.generate_outline(idea, tags)
    if not result:
        print("❌ 大纲生成失败，退出测试")
        return 1
    
    # 3. 创作第一章
    print("\n" + "="*60)
    print("开始创作第一章")
    print("="*60)
    
    if not client.start_supervisor("请帮我写第一章，根据大纲开始创作"):
        print("❌ 启动创作失败，退出测试")
        return 1
    
    # 4. 创作第二章
    print("\n" + "="*60)
    print("开始创作第二章")
    print("="*60)
    
    if not client.resume_supervisor("请继续写第二章"):
        print("❌ 创作第二章失败，退出测试")
        return 1
    
    # 5. 获取作品信息
    print("\n" + "="*60)
    print("获取作品信息")
    print("="*60)
    
    work = client.get_work()
    if work:
        print(f"  作品标题: {work.get('title')}")
        print(f"  作品类型: {work.get('genre')}")
        print(f"  作品状态: {work.get('status')}")
    
    # 6. 获取章节列表
    print("\n" + "="*60)
    print("获取章节列表")
    print("="*60)
    
    chapters = client.list_chapters()
    if chapters:
        print(f"  共 {len(chapters)} 章:")
        for ch in chapters:
            print(f"    第{ch['chapter_number']}章: {ch['title']}")
    
    # 7. 获取第一章内容
    print("\n" + "="*60)
    print("获取第一章内容")
    print("="*60)
    
    chapter1 = client.get_chapter(1)
    if chapter1:
        print(f"  第一章标题: {chapter1['title']}")
        print(f"  第一章内容长度: {len(chapter1['content'])} 字")
        print("\n  第一章内容预览:")
        print("  " + "-"*50)
        lines = chapter1['content'].split('\n')
        for i, line in enumerate(lines[:10]):
            if line.strip():
                print(f"  {line}")
        print("  " + "-"*50)
    
    # 8. 获取第二章内容
    print("\n" + "="*60)
    print("获取第二章内容")
    print("="*60)
    
    chapter2 = client.get_chapter(2)
    if chapter2:
        print(f"  第二章标题: {chapter2['title']}")
        print(f"  第二章内容长度: {len(chapter2['content'])} 字")
        print("\n  第二章内容预览:")
        print("  " + "-"*50)
        lines = chapter2['content'].split('\n')
        for i, line in enumerate(lines[:10]):
            if line.strip():
                print(f"  {line}")
        print("  " + "-"*50)
    
    # 9. 验证连贯性
    print("\n" + "="*60)
    print("验证小说质量")
    print("="*60)
    
    if chapter1 and chapter2:
        print("\n  连贯性验证:")
        # 检查第一章结尾和第二章开头的连贯性
        ch1_lines = [l for l in chapter1['content'].split('\n') if l.strip()]
        ch2_lines = [l for l in chapter2['content'].split('\n') if l.strip()]
        
        if ch1_lines and ch2_lines:
            ch1_ending = ch1_lines[-1][:50] if ch1_lines else ""
            ch2_beginning = ch2_lines[0][:50] if ch2_lines else ""
            print(f"    第一章结尾: {ch1_ending}...")
            print(f"    第二章开头: {ch2_beginning}...")
        
        print("\n  大纲关联性验证:")
        # 获取大纲信息
        work_data = client.get_work()
        if work_data and 'outline_tree' in work_data:
            outline = work_data['outline_tree']
            timeline = outline.get('timeline', [])
            print(f"    大纲主线节点数: {len(timeline)}")
            if timeline:
                print(f"    第一阶段: {timeline[0].get('development_node', 'N/A')}")
    
    print("\n" + "="*60)
    print("测试完成！")
    print("="*60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
